"""Resource planning shared by Ansible and offline regression tests (MiB)."""
import math
import re


def as_bool(value):
    return str(value).lower() in ("true", "yes", "1", "on")


def service_memory(snapshot, owned):
    """Read named systemctl properties; never add shared RSS from processes."""
    units = {}
    for block in re.split(r"\n\s*\n", snapshot.strip()):
        props = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        unit = props.get("Id")
        if unit:
            units[unit] = props
    total = 0
    unbounded = []
    included = []
    apps = re.compile(r"^(nginx|squid|unbound|mtg|keepalived|crowdsec.*|postgresql@.*|"
                      r"matrix-synapse.*|coturn|livekit|lk-jwt-service|docker|containerd|redis.*)\.service$")
    for unit, props in units.items():
        if unit in owned or props.get("ActiveState") not in ("active", "activating", "deactivating", "reloading"):
            continue
        limit = props.get("MemoryMax", "infinity")
        if limit in ("infinity", "0", "18446744073709551615"):
            if apps.match(unit):
                unbounded.append(unit)
            continue  # OS services are covered by the explicit system reserve.
        shared_floors = {"crowdsec.service": 192, "crowdsec-firewall-bouncer.service": 32,
                         "nginx.service": 64}
        total += max(int(limit), shared_floors.get(unit, 0) * 1048576)
        included.append(unit)
    return {"reserved_mb": math.ceil(total / 1048576),
            "units": sorted(included), "unbounded": sorted(unbounded)}


def postgres_cluster(rows, port):
    matches = [r.split() for r in rows.splitlines()
               if len(r.split()) >= 4 and r.split()[2] == str(port)]
    if len(matches) > 1:
        raise ValueError("Multiple PostgreSQL clusters on the Synapse port")
    return {"version": matches[0][0], "name": matches[0][1]} if matches else {}


def matrix_memory_plan(ram, config, foreign=0, shared=False, crowdsec_external=False):
    ram, foreign = int(ram), int(foreign)
    shared, crowdsec_external = as_bool(shared), as_bool(crowdsec_external)
    reserve_share = float(config.get("memory_reserve_when_shared_share", .15) if shared
                          else config.get("memory_reserve_share", .25))
    share = float(config.get("memory_share_when_shared", .5))
    if not 0 < reserve_share < 1 or not 0 < share <= 1 or foreign < 0:
        raise ValueError("Invalid memory reserve or project share")
    reserve = max(128, int(config.get("memory_system_min_mb", 128)), math.ceil(ram * reserve_share))
    available = ram - reserve - foreign
    allocation = min(available, int(ram * share)) if shared else available
    users = int(config["max_concurrent_users"])
    if users < 1:
        raise ValueError("max_concurrent_users must be positive")
    floors = {"postgresql": 160, "synapse": 160, "coturn": 40, "livekit": 128,
              "lk_jwt": 48, "nginx": 64, "crowdsec": 192, "crowdsec_bouncer": 32}
    multipliers = {"postgresql": 2, "synapse": 3, "coturn": 1, "livekit": 2}
    shares = {"postgresql": .16, "synapse": .22, "coturn": .04, "livekit": .09,
              "lk_jwt": .03, "nginx": .04, "crowdsec": .11, "crowdsec_bouncer": .03}
    limits = {}
    for name, floor in floors.items():
        fraction = float(config.get("memory_share_" + name, shares[name]))
        if not 0 <= fraction <= 1:
            raise ValueError("Invalid service memory share: " + name)
        limits[name] = max(floor, int(config.get("memory_min_" + name, floor)),
                           users * multipliers.get(name, 0), int(max(allocation, 0) * fraction))
    enabled = ["postgresql", "synapse"]
    if as_bool(config.get("coturn_enabled", True)):
        enabled.append("coturn")
    if as_bool(config.get("livekit_enabled", False)):
        enabled += ["livekit", "lk_jwt"]
    if not shared:
        enabled.append("nginx")
    if as_bool(config.get("crowdsec_enabled", False)) and not crowdsec_external:
        enabled += ["crowdsec", "crowdsec_bouncer"]
    total = sum(limits[n] for n in enabled)
    return {"limits": limits, "total_mb": total, "allocatable_mb": allocation,
            "system_reserved_mb": reserve, "foreign_reserved_mb": foreign,
            "node_total_mb": total + reserve + foreign,
            "fits": total <= allocation and total + reserve + foreign <= ram}


def postgres_resource_plan(memory, users, pool_max=None, pool_min=2):
    memory, users, pool_min = int(memory), int(users), int(pool_min)
    capacity = min(16, max(2, (memory - 96) // 16))
    pool_max = int(pool_max) if pool_max is not None else min(capacity, max(2, math.ceil(users / 3)))
    if not 1 <= pool_min <= pool_max <= capacity:
        raise ValueError("Synapse DB pool exceeds the PostgreSQL memory budget")
    return {"pool_min": pool_min, "pool_max": pool_max, "max_connections": pool_max + 12,
            "shared_buffers_mb": 32 if memory < 512 else min(256, memory // 5),
            "work_mem_mb": 1 if memory < 512 else 2,
            "maintenance_work_mem_mb": 8 if memory < 512 else 16,
            "autovacuum_work_mem_mb": 4 if memory < 512 else 8,
            "autovacuum_max_workers": 1 if memory < 512 else 2,
            "parallel_workers": 0 if memory < 1024 else 1,
            "wal_buffers_mb": 2}


class FilterModule:
    def filters(self):
        return {"service_memory": service_memory, "postgres_cluster": postgres_cluster,
                "matrix_memory_plan": matrix_memory_plan,
                "postgres_resource_plan": postgres_resource_plan}
