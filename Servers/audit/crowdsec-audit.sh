#!/usr/bin/env bash
#==============================================================================
#  crowdsec-audit.sh -- security-отчёт о попытках вторжения за указанную дату
#
#  Источники данных:
#     * CrowdSec LAPI через cscli (алерты, решения, машины, баунсеры, hub)
#     * локальная БД CrowdSec (sqlite) -- точная выборка по суткам и
#       перекрёстная проверка того, что отдал LAPI
#     * журналы движка: crowdsec.log, crowdsec_api.log, journalctl -u crowdsec
#
#  Режим работы строго read-only: скрипт ничего не пишет в БД CrowdSec,
#  не создаёт и не снимает решений, не перезапускает сервисы.
#
#  Результат: <outdir>/report.md  + <outdir>/raw/* (сырые выгрузки)
#
#  Пример:  sudo ./crowdsec-audit.sh -d 2026-08-20 -o /root/audits
#==============================================================================
set -euo pipefail
umask 077
# bash < 4.4 считает пустой массив "unset" при set -u -- отключаем nounset на старых версиях
if [ "${BASH_VERSINFO[0]:-0}" -lt 4 ] \
   || { [ "${BASH_VERSINFO[0]}" -eq 4 ] && [ "${BASH_VERSINFO[1]:-0}" -lt 4 ]; }; then set +u; fi

# %b в crowdsec_api.log всегда английский, а сортировки должны быть байтовыми
export LC_ALL=C

readonly PROG="${0##*/}"
readonly VERSION="2.1.0"

#------------------------------------------------------------------ настройки
DAY_IN="yesterday"                                  # -d
OUTDIR=""                                           # -o
DB="/var/lib/crowdsec/data/crowdsec.db"             # -D
CS_CONFIG="/etc/crowdsec/config.yaml"               # -c
LOGDIR="/var/log"                                   # --logdir
SOURCE="auto"                                       # --source auto|cscli|db
TOP=20                                              # --top
HISTORY_DAYS=30                                     # --history
COLLECT_LOGS=1                                      # --no-logs
COLLECT_STATE=1                                     # --no-state
HOST_CHECK=1                                        # --no-host
DEEP=0                                              # --deep
QUICK=0                                             # --quick
FAIL_ON_CRIT=0                                      # --fail-on-critical
QUIET=0                                             # -q
CSCLI="${CSCLI:-cscli}"

# Классификация сценариев по опасности (регулярки, ERE, нижний регистр).
CRIT_RE='cve|rce|log4j|shellshock|backdoor|webshell|exploit|deserial|command[-_]?inj|spring4shell|proxyshell|traversal|sqli|xxe|ssrf|arbitrary|struts|confluence|fortinet|f5-big-ip|citrix|netgear|vmware|jira|gitlab|zimbra|exchange'
HIGH_RE='bf|brute|slow|probing|crawl|scan|enum|sensitive|bad-user-agent|open-proxy|dos|flood|spam|wordpress|joomla|drupal|magento|phpmyadmin|iptables|port'

usage() {
  cat <<EOF
$PROG $VERSION -- security-отчёт CrowdSec о попытках вторжения за сутки.

ИСПОЛЬЗОВАНИЕ
  $PROG [-d ДАТА] [-o КАТАЛОГ] [опции]

ОСНОВНОЕ
  -d, --date ДАТА        аудируемые сутки: YYYY-MM-DD, "yesterday", "3 days ago"
                         (по умолчанию: $DAY_IN)
  -o, --outdir КАТАЛОГ   куда положить отчёт; будет создан подкаталог
                         crowdsec-audit-<дата> (по умолчанию: текущий каталог)

ИСТОЧНИКИ
      --source РЕЖИМ     auto | cscli | db   (по умолчанию: $SOURCE)
  -D, --db ПУТЬ          sqlite-БД CrowdSec (по умолчанию: $DB)
  -c, --config ПУТЬ      config.yaml CrowdSec (по умолчанию: $CS_CONFIG)
      --logdir ПУТЬ      каталог с crowdsec.log / crowdsec_api.log (по умолчанию: $LOGDIR)
      --no-logs          не собирать журналы движка
      --no-state         не собирать состояние (hub, machines, bouncers, metrics)

ТРИАЖ ХОСТА (проверка машины на признаки компрометации, только чтение)
      --no-host          не выполнять проверку хоста, ограничиться данными CrowdSec
      --quick            пропустить сверку контрольных сумм пакетов (dpkg --verify),
                         самую долгую проверку -- до минуты на типовой системе
      --deep             искать SUID/SGID и capabilities по всей файловой системе,
                         а не только в системных каталогах (минуты на больших дисках)

ОТЧЁТ
      --top N            размер топов в таблицах (по умолчанию: $TOP)
      --history N        сколько суток до даты смотреть для поиска повторных
                         нарушителей (по умолчанию: $HISTORY_DAYS)
      --crit-re RE       своя регулярка критичных сценариев
      --high-re RE       своя регулярка сценариев высокой важности
      --fail-on-critical выйти с кодом 10, если найдены критичные срабатывания
  -q, --quiet            без прогресса на stderr
  -h, --help             эта справка
  -V, --version          версия

КОДЫ ВОЗВРАТА
  0  отчёт построен            2  ошибка аргументов
  1  фатальная ошибка         10  найдены критичные срабатывания (--fail-on-critical)

ЗАВИСИМОСТИ
  обязательно: bash 4+, jq, coreutils(date)
  желательно : cscli, sqlite3 (>=3.33 для -json), journalctl, gzip
  для триажа : штатные пакеты Ubuntu 24.04 -- systemd (journalctl, systemctl),
               util-linux (last, lastb), dpkg, procps, iproute2 (ss), libcap2-bin
               (getcap), e2fsprogs (lsattr); необязательно -- debsums, auditd,
               apparmor (aa-status), ufw/nftables, ubuntu-pro-client (pro)
EOF
}

#------------------------------------------------------------------- аргументы
while [ $# -gt 0 ]; do
  case "$1" in
    -d|--date)            DAY_IN="${2:?нужна дата}"; shift 2 ;;
    -o|--outdir)          OUTDIR="${2:?нужен каталог}"; shift 2 ;;
    -D|--db)              DB="${2:?нужен путь}"; shift 2 ;;
    -c|--config)          CS_CONFIG="${2:?нужен путь}"; shift 2 ;;
    --logdir)             LOGDIR="${2:?нужен путь}"; shift 2 ;;
    --source)             SOURCE="${2:?auto|cscli|db}"; shift 2 ;;
    --top)                TOP="${2:?число}"; shift 2 ;;
    --history)            HISTORY_DAYS="${2:?число}"; shift 2 ;;
    --crit-re)            CRIT_RE="${2:?регулярка}"; shift 2 ;;
    --high-re)            HIGH_RE="${2:?регулярка}"; shift 2 ;;
    --no-logs)            COLLECT_LOGS=0; shift ;;
    --no-state)           COLLECT_STATE=0; shift ;;
    --no-host)            HOST_CHECK=0; shift ;;
    --deep)               DEEP=1; shift ;;
    --quick)              QUICK=1; shift ;;
    --fail-on-critical)   FAIL_ON_CRIT=1; shift ;;
    -q|--quiet)           QUIET=1; shift ;;
    -h|--help)            usage; exit 0 ;;
    -V|--version)         echo "$PROG $VERSION"; exit 0 ;;
    --)                   shift; break ;;
    -*)                   echo "$PROG: неизвестная опция: $1" >&2; usage >&2; exit 2 ;;
    *)                    DAY_IN="$1"; shift ;;
  esac
done

#-------------------------------------------------------------------- хелперы
if [ -t 2 ]; then C_DIM=$'\033[2m'; C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_GRN=$'\033[32m'; C_OFF=$'\033[0m'
else C_DIM=""; C_RED=""; C_YEL=""; C_GRN=""; C_OFF=""; fi

log()  { [ "$QUIET" -eq 1 ] || printf '%s[%s]%s %s\n' "$C_DIM" "$(date +%H:%M:%S)" "$C_OFF" "$*" >&2; }
warn() { printf '%s[warn]%s %s\n' "$C_YEL" "$C_OFF" "$*" >&2; WARNINGS+=("$*"); }
die()  { printf '%s[fail]%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
declare -a WARNINGS=()

# markdown-экранирование содержимого ячеек таблицы
mdq() { printf '%s' "$1" | sed 's/|/\\|/g'; }

#------------------------------------------------------------------- преflight
have jq   || die "не найден jq -- он обязателен (apt install jq / dnf install jq)"
have date || die "не найден date"
date -d "2020-01-01" +%s >/dev/null 2>&1 || die "нужен GNU date (coreutils); на BSD/macOS поставьте gdate и подмените PATH"

# в зонах, где перевод часов приходится на полночь, "date -d ГГГГ-ММ-ДД" (=полночь) не разбирается
DAY="$(date -d "$DAY_IN" +%F 2>/dev/null || true)"
[ -n "$DAY" ] || DAY="$(date -d "$DAY_IN 12:00:00" +%F 2>/dev/null || true)"
[ -n "$DAY" ] || die "не разобрать дату: '$DAY_IN'"
DAY_NEXT="$(date -d "$DAY 12:00:00 +1 day" +%F 2>/dev/null || true)"
[ -n "$DAY_NEXT" ] || die "не вычислить следующие сутки после $DAY"
NOW=$(date +%s)
# в зонах, где перевод часов происходит в полночь, локальной 00:00:00 может не существовать
day_start() { date -d "$1 00:00:00" +%s 2>/dev/null || date -d "$1 01:00:00" +%s 2>/dev/null || date -d "$1 12:00:00" +%s 2>/dev/null; }
FROM="$(day_start "$DAY")"      || true
NEXT="$(day_start "$DAY_NEXT")" || true
[ -n "${FROM:-}" ] && [ -n "${NEXT:-}" ] || die "не вычислить границы суток $DAY в зоне $(date +%Z)"
TO=$(( NEXT - 1 ))
[ "$FROM" -le "$NOW" ] || die "дата $DAY в будущем"

# смещение локальной зоны в секундах на аудируемую дату (учитывает переход на летнее время)
TZOFF_STR="$(date -d "$DAY 12:00:00" +%z)"
_sgn="${TZOFF_STR:0:1}"; _h="${TZOFF_STR:1:2}"; _m="${TZOFF_STR:3:2}"
OFF_SEC=$(( 10#$_h * 3600 + 10#$_m * 60 ))
[ "$_sgn" = "-" ] && OFF_SEC=$(( -OFF_SEC ))
TZNAME="$(date -d "$DAY 12:00:00" +%Z)"
# сутки с переводом часов: времена в отчёте считаются по «полуденному» смещению
DST_SHIFT=0
if [ "$(date -d "@$FROM" +%z)" != "$(date -d "@$TO" +%z)" ]; then
  DST_SHIFT=1
  warn "в сутки $DAY происходит перевод часов -- времена в отчёте посчитаны по смещению $TZOFF_STR, часть из них может быть смещена на час"
fi

HOSTN="$(hostname -f 2>/dev/null || hostname 2>/dev/null || echo unknown)"
STAMP="$(date +%Y%m%d-%H%M%S)"
[ -n "$OUTDIR" ] || OUTDIR="."
OUT="$OUTDIR/crowdsec-audit-$DAY"
RAW="$OUT/raw"
mkdir -p "$RAW" || die "не создать каталог $RAW"
# каталог принадлежит скрипту (имя детерминировано): убираем артефакты прошлого прогона,
# иначе в отчёт попадут устаревшие данные и файлы другого режима сбора
find "$RAW" -maxdepth 1 -type f \( -name '*.json' -o -name '*.log' -o -name '*.txt' -o -name '*.err' \) -delete 2>/dev/null || true
REPORT="$OUT/report.md"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/csaudit.XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

log "дата аудита: $DAY  ($TZNAME, окно $FROM..$TO epoch)"
log "каталог отчёта: $OUT"

[ "$(id -u)" -eq 0 ] || warn "скрипт запущен не от root: cscli и БД CrowdSec обычно недоступны обычному пользователю"

HAVE_CSCLI=0; HAVE_SQLITE=0
have "$CSCLI" && HAVE_CSCLI=1
if have sqlite3 && [ -r "$DB" ]; then
  if sqlite3 -json ":memory:" "select 1 as a" >/dev/null 2>&1; then HAVE_SQLITE=1
  else warn "sqlite3 без поддержки -json (нужна версия >= 3.33) -- путь через БД отключён"; fi
fi

case "$SOURCE" in
  auto) if [ "$HAVE_CSCLI" -eq 1 ]; then SOURCE=cscli; elif [ "$HAVE_SQLITE" -eq 1 ]; then SOURCE=db;
        else die "нет ни cscli, ни читаемой БД $DB -- нечего аудировать"; fi ;;
  cscli) [ "$HAVE_CSCLI" -eq 1 ] || die "cscli не найден" ;;
  db)    [ "$HAVE_SQLITE" -eq 1 ] || die "sqlite3 не найден, или нет доступа к $DB, или нет поддержки -json" ;;
  *)     echo "$PROG: --source должен быть auto|cscli|db" >&2; exit 2 ;;
esac
log "основной источник данных: $SOURCE"

#==============================================================================
#  jq-программы (пишутся во временный каталог, чтобы скрипт остался монолитным)
#==============================================================================
cat >"$WORK/lib.jq" <<'JQEOF'
# --- разбор таймстемпа CrowdSec (RFC3339 из LAPI и "YYYY-MM-DD HH:MM:SS+00:00" из sqlite)
def ep:
  . as $x
  | try (
      ($x | tostring | sub("\\.[0-9]+"; "")) as $t
      | ($t[0:10] + "T" + $t[11:19] + "Z" | fromdateiso8601) as $b
      | ($t[19:] | gsub("[: ]"; "")) as $q
      | if ($q | test("^[+-][0-9]{4}$"))
        then ((($q[1:3] | tonumber) * 3600 + ($q[3:5] | tonumber) * 60)) as $s
             | (if $q[0:1] == "-" then $b + $s else $b - $s end)
        else $b end
    ) catch null;
def nn($v): if ($v == null or $v == "") then "" else ($v | tostring) end;
# --- человекочитаемая длительность из секунд
def hdur($s):
  if ($s == null or (($s | type) != "number") or $s <= 0) then "н/д" else
    (($s | floor) as $t
     | (($t / 86400) | floor) as $d
     | ((($t % 86400) / 3600) | floor) as $h
     | ((($t % 3600) / 60) | floor) as $m
     | ((if $d > 0 then "\($d)d" else "" end)
        + (if $h > 0 then "\($h)h" else "" end)
        + (if ($d == 0 and $m > 0) then "\($m)m" else "" end))
     | if . == "" then "\($t)s" else . end)
  end;
JQEOF

# --- нормализация выгрузки cscli alerts list -o json -----------------------
cat >"$WORK/norm_cscli.jq" <<'JQEOF'
(. // [])
| map({
    id:          (.id // 0),
    ts:          (.created_at // .start_at // ""),
    scenario:    (.scenario // "-"),
    machine:     (.machine_id // "-"),
    scope:       (.source.scope // "-"),
    value:       ((.source.value // .source.ip // "-") | tostring),
    cn:          nn(.source.cn),
    as:          nn(.source.as_name),
    asn:         nn(.source.as_number),
    events:      (try ((.events_count // 0) | tonumber) catch 0),
    remediation: (.remediation // ((.decisions // []) | length > 0)),
    simulated:   (.simulated // false),
    dec: [ (.decisions // [])[]
           | { type: nn(.type), duration: nn(.duration), origin: nn(.origin),
               scope: nn(.scope), value: nn(.value), simulated: (.simulated // false) } ]
  })
| map(. + { e: (.ts | ep) })
JQEOF

# --- нормализация выгрузки из sqlite --------------------------------------
cat >"$WORK/norm_db.jq" <<'JQEOF'
((.machines // []) | map({key: (.id|tostring), value: (.machine_id // "-")}) | from_entries) as $M
| ((.decisions // []) | group_by(.alert_decisions | tostring)
   | map({key: (.[0].alert_decisions | tostring),
          value: [ .[] | { type: nn(.type),
                           duration: (hdur( ((.until | ep) // 0) - ((.created_at | ep) // 0) )),
                           until: nn(.until), origin: nn(.origin),
                           scope: nn(.scope), value: nn(.value),
                           simulated: ((.simulated // 0) == 1) } ] })
   | from_entries) as $DEC
| ((.alerts // []) | map({
      id:          (.id // 0),
      ts:          (.created_at // .started_at // ""),
      scenario:    (.scenario // "-"),
      machine:     ($M[(.machine_alerts // "" | tostring)] // "-"),
      scope:       (nn(.source_scope) | if . == "" then "-" else . end),
      value:       (nn(.source_value) | if . == "" then nn(.source_ip) else . end),
      cn:          nn(.source_country),
      as:          nn(.source_as_name),
      asn:         nn(.source_as_number),
      events:      (try ((.events_count // 0) | tonumber) catch 0),
      remediation: ((.remediation // 0) == 1),
      simulated:   ((.simulated // 0) == 1),
      dec:         ($DEC[(.id|tostring)] // [])
    }))
| map(. + { e: (.ts | ep),
            value: (.value | tostring),
            remediation: (.remediation or ((.dec | length) > 0)) })
JQEOF

# --- вычисление фактов -----------------------------------------------------
cat >"$WORK/facts.jq" <<'JQEOF'
def sev($s): ($s | tostring | ascii_downcase) as $l
  | if   ($l | test($critre)) then "critical"
    elif ($l | test($highre)) then "high"
    else "medium" end;

($all[0] // [])  as $A
| ($actv[0] // []) as $ACT
| ($ACT | reduce .[] as $v ({}; .[$v] = true)) as $ACTI
| ($A | map(select(.e != null and .e >= $from and .e <= $to)))  as $D
| ($A | map(select(.e != null and .e <  $from)))                as $H
| ($H | group_by(.value)
      | map({ key: (.[0].value),
              value: { alerts: length,
                       days: (map(((.e + $off) / 86400) | floor) | unique | length),
                       first: (map(.e) | min) } })
      | from_entries) as $HI
| ($D | map(.dec[]?)) as $DEC
| ($D | group_by(.value)
      | map(. as $g | ($g[0].value) as $v | {
          value: $v,
          scope: $g[0].scope,
          cn:  (($g | map(.cn)  | map(select(. != "")) | .[0]) // ""),
          as:  (($g | map(.as)  | map(select(. != "")) | .[0]) // ""),
          asn: (($g | map(.asn) | map(select(. != "")) | .[0]) // ""),
          alerts: ($g | length),
          events: (($g | map(.events) | add) // 0),
          first:  ($g | map(.e) | min),
          last:   ($g | map(.e) | max),
          scenarios: ($g | map(.scenario) | unique),
          sev: (($g | map(sev(.scenario))) as $sl
                | if ($sl | index("critical")) then "critical"
                  elif ($sl | index("high"))   then "high"
                  else "medium" end),
          banned: ($g | map(.remediation) | any),
          decs:   ($g | map(.dec[]?) | length),
          active_now: ($ACTI[$v] // false),
          prior: ($HI[$v] // null) })
      | sort_by([- .alerts, - .events])) as $SRC
| ($D | group_by((((.e + $off) / 3600) | floor) % 24)
      | map({ h: ((((.[0].e + $off) / 3600) | floor) % 24),
              n: length,
              srcs: (map(.value) | unique | length) })) as $BH
| {
  window: { day: $day, from: $from, to: $to, off: $off, tz: $tz,
            hist_days: $histdays, source: $source, generated: $gen },
  totals: {
    alerts:           ($D | length),
    events:           (($D | map(.events) | add) // 0),
    sources:          ($SRC | length),
    banned_sources:   ($SRC | map(select(.banned)) | length),
    unbanned_sources: ($SRC | map(select(.banned | not)) | length),
    still_active:     ($SRC | map(select(.active_now)) | length),
    simulated:        ($D | map(select(.simulated)) | length),
    decisions:        ($DEC | length),
    critical:         ($D | map(select(sev(.scenario) == "critical")) | length),
    high:             ($D | map(select(sev(.scenario) == "high")) | length),
    scenarios:        ($D | map(.scenario) | unique | length),
    countries:        ($D | map(.cn) | map(select(. != "")) | unique | length),
    machines:         ($D | map(.machine) | unique | length),
    repeat_sources:   ($SRC | map(select(.prior != null)) | length),
    new_sources:      ($SRC | map(select(.prior == null)) | length),
    hist_alerts:      ($H | length)
  },
  by_hour: [ range(0; 24) as $h
             | (($BH | map(select(.h == $h)) | .[0]) // { h: $h, n: 0, srcs: 0 }) ],
  scenarios: ($D | group_by(.scenario)
    | map({ name: .[0].scenario, sev: sev(.[0].scenario), alerts: length,
            sources: (map(.value) | unique | length),
            events: ((map(.events) | add) // 0),
            banned: (map(select(.remediation)) | length),
            first: (map(.e) | min), last: (map(.e) | max) })
    | sort_by([- .alerts, - .sources])),
  sources: $SRC,
  countries: ($D | map(select(.cn != "")) | group_by(.cn)
    | map({ k: .[0].cn, n: length, srcs: (map(.value) | unique | length) })
    | sort_by(- .n)),
  asns: ($D | map(select(.as != "")) | group_by(.as)
    | map({ k: .[0].as, asn: (.[0].asn), n: length, srcs: (map(.value) | unique | length) })
    | sort_by(- .n)),
  machines: ($D | group_by(.machine)
    | map({ k: .[0].machine, n: length, srcs: (map(.value) | unique | length),
            crit: (map(select(sev(.scenario) == "critical")) | length) })
    | sort_by(- .n)),
  scopes: ($D | group_by(.scope)
    | map({ k: .[0].scope, n: length }) | sort_by(- .n)),
  decisions: {
    total:       ($DEC | length),
    simulated:   ($DEC | map(select(.simulated)) | length),
    by_type:     ($DEC | group_by(.type)     | map({ k: .[0].type,     n: length }) | sort_by(- .n)),
    by_origin:   ($DEC | group_by(.origin)   | map({ k: .[0].origin,   n: length }) | sort_by(- .n)),
    by_duration: ($DEC | group_by(.duration) | map({ k: .[0].duration, n: length }) | sort_by(- .n))
  },
  critical_alerts: ($D | map(select(sev(.scenario) == "critical")) | sort_by(.e)
    | map({ id, e, scenario, value, cn, as, events, machine, remediation,
            dec: (.dec | map(.type + "/" + .duration)) })),
  unbanned: ($SRC | map(select(.banned | not)) | sort_by(- .alerts)),
  repeat:   ($SRC | map(select(.prior != null)) | sort_by([- (.prior.days), - .alerts]))
}
JQEOF

# --- рендер отчёта в markdown ---------------------------------------------
cat >"$WORK/render.jq" <<'JQEOF'
def rep($c; $n): if (($n // 0) | floor) > 0 then ($c * (($n // 0) | floor)) else "" end;
def esc:      (. // "") | tostring | gsub("\\|"; "\\|");
def hm($e):   if $e == null then "-" else (($e + $off) | strftime("%H:%M:%S")) end;
def dt($e):   if $e == null then "-" else (($e + $off) | strftime("%Y-%m-%d %H:%M")) end;
def sevlab($s): if $s == "critical" then "**КРИТ**" elif $s == "high" then "ВЫС" else "сред" end;
def yn($b):   if $b then "да" else "нет" end;
def cut($n):  (. // "") | tostring | if (length > $n) then (.[0:$n-1] + "…") else . end;
def dash:     (. // "") | tostring | if . == "" then "-" else . end;
def pl($n; $a; $b; $c):
  (($n // 0) % 100) as $h | (($n // 0) % 10) as $t
  | if   ($h >= 11 and $h <= 14) then $c
    elif $t == 1                 then $a
    elif ($t >= 2 and $t <= 4)   then $b
    else $c end;

. as $F
| $F.totals as $T
| ($F.by_hour | map(.n) | max) as $HMAX
| ($F.by_hour | max_by(.n)) as $PEAK
| [

"## 1. Сводка",
"",
"| Показатель | Значение |",
"| --- | ---: |",
"| Алертов за сутки | \($T.alerts) |",
"| Событий в логах, породивших алерты | \($T.events) |",
"| Уникальных источников атак | \($T.sources) |",
"| Уникальных сценариев | \($T.scenarios) |",
"| Стран-источников | \($T.countries) |",
"| Критичных срабатываний | \($T.critical) |",
"| Срабатываний высокой важности | \($T.high) |",
"| Выдано решений (блокировок) | \($T.decisions) |",
"| Источников с блокировкой | \($T.banned_sources) |",
"| Источников **без** блокировки | \($T.unbanned_sources) |",
"| Из них заблокировано на момент аудита | \($T.still_active) |",
"| Алертов в режиме симуляции | \($T.simulated) |",
"| Повторные нарушители (были в предыдущие \($F.window.hist_days) сут.) | \($T.repeat_sources) |",
"| Источники, замеченные впервые | \($T.new_sources) |",
"| Затронуто машин (machine_id) | \($T.machines) |",
""
]
+ ( [ "**Выводы:**", "" ]
    + (if $T.alerts == 0 then
        [ "- За указанные сутки CrowdSec не зафиксировал ни одного срабатывания.",
          "- Прежде чем считать это тишиной, проверьте: попадает ли дата в retention БД (`db_config.flush.max_age`), был ли движок запущен, и читались ли нужные логи (`cscli metrics` -> секция acquisition, раздел 11-12 отчёта)." ]
       else [] end)
    + (if $T.critical > 0 then
        [ "- **КРИТИЧНО:** \($T.critical) \(pl($T.critical; "срабатывание"; "срабатывания"; "срабатываний")) по сценариям эксплуатации уязвимостей и веб-атак. Разбор в разделе 6, по каждому есть готовая команда `cscli alerts inspect`." ]
       else [] end)
    + (if $T.unbanned_sources > 0 then
        [ "- \($T.unbanned_sources) \(pl($T.unbanned_sources; "источник обнаружен"; "источника обнаружены"; "источников обнаружено")) без выданного решения (раздел 8). Причины обычно: сценарий без remediation, whitelist, режим simulation или профиль в `profiles.yaml`." ]
       else [] end)
    + (if $T.simulated > 0 then
        [ "- \($T.simulated) \(pl($T.simulated; "алерт помечен"; "алерта помечены"; "алертов помечены")) как simulated: решения по ним не применялись (`cscli simulation status`)." ]
       else [] end)
    + (if $T.repeat_sources > 0 then
        [ "- \($T.repeat_sources) \(pl($T.repeat_sources; "источник уже встречался"; "источника уже встречались"; "источников уже встречались")) в предыдущие \($F.window.hist_days) сут. -- это не разовый шум, а возвращающиеся сканеры и боты (раздел 9)." ]
       else [] end)
    + (if $T.still_active > 0 then
        [ "- \($T.still_active) из них \(pl($T.still_active; "заблокирован"; "заблокированы"; "заблокированы")) прямо сейчас." ]
       else [] end)
    + (if ($T.alerts > 0 and $PEAK != null and $PEAK.n > 0) then
        [ "- Пик активности: \($PEAK.h | tostring | (if length < 2 then "0" + . else . end)):00 -- \($PEAK.n) \(pl($PEAK.n; "алерт"; "алерта"; "алертов")) от \($PEAK.srcs) \(pl($PEAK.srcs; "источника"; "источников"; "источников"))." ]
       else [] end)
    + [ "" ] )
+ [
"## 2. Активность по часам (\($F.window.tz))",
"",
"```"
]
+ ( $F.by_hour | map(
      ((.h | tostring) | (if length < 2 then "0" + . else . end)) as $hh
      | (if ($HMAX // 0) > 0 and .n > 0
         then (((.n * 44) / $HMAX) | floor) as $w | rep("#"; (if $w < 1 then 1 else $w end))
         else "" end) as $bar
      | "\($hh):00 | \($bar) \(.n)\(if .n > 0 then "  (\(.srcs) ист.)" else "" end)" ) )
+ [ "```", "" ]

+ [ "## 3. Сценарии атак", "" ]
+ (if ($F.scenarios | length) == 0 then [ "_Нет данных._", "" ] else
   [ "| Сценарий | Важность | Алертов | Источников | Событий | С блокировкой | Первый | Последний |",
     "| --- | :---: | ---: | ---: | ---: | ---: | --- | --- |" ]
   + ($F.scenarios | .[0:$top] | map(
       "| `\(.name|esc)` | \(sevlab(.sev)) | \(.alerts) | \(.sources) | \(.events) | \(.banned) | \(hm(.first)) | \(hm(.last)) |"))
   + (if ($F.scenarios | length) > $top then [ "", "_Показаны \($top) из \($F.scenarios|length); полный список -- в `raw/facts.json`._" ] else [] end)
   + [ "" ] end)

+ [ "## 4. Источники атак", "" ]
+ (if ($F.sources | length) == 0 then [ "_Нет данных._", "" ] else
   [ "| Источник | Scope | Страна | AS | Алертов | Событий | Сценарии | Первый | Последний | Блок. | Активен сейчас | Ранее |",
     "| --- | :---: | :---: | --- | ---: | ---: | --- | --- | --- | :---: | :---: | :---: |" ]
   + ($F.sources | .[0:$top] | map(
       "| `\(.value|esc)` | \(.scope|esc) | \(if .cn == "" then "-" else (.cn|esc) end) | \(.as|cut(28)|dash|esc) | \(.alerts) | \(.events) | \(.scenarios | map(sub("^crowdsecurity/";"")) | join(", ") | cut(60) | esc) | \(hm(.first)) | \(hm(.last)) | \(yn(.banned)) | \(yn(.active_now)) | \(if .prior == null then "-" else "\(.prior.days) сут." end) |"))
   + (if ($F.sources | length) > $top then [ "", "_Показаны \($top) из \($F.sources|length); полный список -- в `raw/facts.json`._" ] else [] end)
   + [ "" ] end)

+ [ "## 5. География и сети", "" ]
+ (if ($F.countries | length) == 0 then [ "_Нет данных о геолокации (нет geoip-обогащения либо источники приватные)._", "" ] else
   [ "| Страна | Алертов | Источников |", "| :---: | ---: | ---: |" ]
   + ($F.countries | .[0:$top] | map("| \(.k|esc) | \(.n) | \(.srcs) |")) + [ "" ] end)
+ (if ($F.asns | length) == 0 then [] else
   [ "| Автономная система | Алертов | Источников |", "| --- | ---: | ---: |" ]
   + ($F.asns | .[0:$top] | map("| \(.k|cut(48)|esc)\(if (.asn // "") == "" then "" else " (AS\(.asn))" end) | \(.n) | \(.srcs) |")) + [ "" ] end)

+ [ "## 6. Критичные срабатывания", "" ]
+ (if ($F.critical_alerts | length) == 0 then
     [ "_Сценариев из категории «эксплуатация уязвимостей / веб-атаки» за сутки не сработало._", "" ]
   else
     [ "| Время | ID | Источник | Страна | Сценарий | Событий | Решение | Машина |",
       "| --- | ---: | --- | :---: | --- | ---: | --- | --- |" ]
     + ($F.critical_alerts | .[0:100] | map(
         "| \(hm(.e)) | \(.id) | `\(.value|esc)` | \(if .cn == "" then "-" else (.cn|esc) end) | `\(.scenario|esc)` | \(.events) | \(if (.dec|length) == 0 then (if .remediation then "было, истекло" else "**нет**" end) else (.dec | join(", ") | esc) end) | \(.machine|cut(20)|esc) |"))
     + [ "",
         "Детальный разбор конкретного срабатывания (сырые строки лога, разобранные поля, решения):",
         "",
         "```bash" ]
     + ($F.critical_alerts | .[0:15] | map("cscli alerts inspect \(.id) -d"))
     + [ "```", "" ] end)

+ [ "## 7. Выданные решения", "" ]
+ (if $F.decisions.total == 0 then
     [ "_За сутки решений не выдавалось._",
       "",
       "Обратите внимание: истёкшие решения удаляются из БД, поэтому для прошедшей даты этот раздел может быть пуст, даже если блокировки были. Признак «блокировка выдавалась» -- поле remediation у алерта (колонка «Блок.» в разделе 4).",
       "" ]
   else
     [ "Всего решений: **\($F.decisions.total)** (из них в симуляции: \($F.decisions.simulated)).", "",
       "| Тип | Кол-во |", "| --- | ---: |" ]
     + ($F.decisions.by_type | map("| \(.k|esc) | \(.n) |")) + [ "" ]
     + [ "| Источник решения (origin) | Кол-во |", "| --- | ---: |" ]
     + ($F.decisions.by_origin | map("| \(.k|esc) | \(.n) |")) + [ "" ]
     + [ "| Длительность | Кол-во |", "| --- | ---: |" ]
     + ($F.decisions.by_duration | .[0:10] | map("| \(.k|esc) | \(.n) |")) + [ "" ] end)

+ [ "## 8. Обнаружено, но не заблокировано", "" ]
+ (if ($F.unbanned | length) == 0 then [ "_Все источники за сутки получили решение._", "" ] else
   [ "Источники, по которым сработали сценарии, но решение не выдавалось. Это либо ожидаемо (whitelist, сценарий без remediation), либо дыра в профилях.",
     "",
     "| Источник | Страна | Алертов | Сценарии | Важность |", "| --- | :---: | ---: | --- | :---: |" ]
   + ($F.unbanned | .[0:$top] | map(
       "| `\(.value|esc)` | \(if .cn == "" then "-" else (.cn|esc) end) | \(.alerts) | \(.scenarios | map(sub("^crowdsecurity/";"")) | join(", ") | cut(60) | esc) | \(sevlab(.sev)) |"))
   + [ "", "Проверить причину: `cscli whitelists list` (если установлены), `cat /etc/crowdsec/profiles.yaml`, `cscli simulation status`.", "" ] end)

+ [ "## 9. Повторные нарушители", "" ]
+ (if ($F.repeat | length) == 0 then
     [ "_Ни один из источников не встречался в предыдущие \($F.window.hist_days) суток (в пределах retention БД)._", "" ]
   else
   [ "| Источник | Страна | Алертов за сутки | Дней активности ранее | Алертов ранее | Впервые замечен |",
     "| --- | :---: | ---: | ---: | ---: | --- |" ]
   + ($F.repeat | .[0:$top] | map(
       "| `\(.value|esc)` | \(if .cn == "" then "-" else (.cn|esc) end) | \(.alerts) | \(.prior.days) | \(.prior.alerts) | \(dt(.prior.first)) |"))
   + [ "" ] end)

+ [ "## 10. Затронутые машины и типы источников", "" ]
+ (if ($F.machines | length) == 0 then [ "_Нет данных._", "" ] else
   [ "| machine_id | Алертов | Источников | Критичных |", "| --- | ---: | ---: | ---: |" ]
   + ($F.machines | .[0:$top] | map("| `\(.k|esc)` | \(.n) | \(.srcs) | \(.crit) |")) + [ "" ] end)
+ (if ($F.scopes | length) == 0 then [] else
   [ "| Scope решения/алерта | Кол-во |", "| --- | ---: |" ]
   + ($F.scopes | map("| \(.k|esc) | \(.n) |")) + [ "" ] end)

| join("\n")
JQEOF

#==============================================================================
#  Сбор данных
#==============================================================================
case "$TOP"          in ''|*[!0-9]*) echo "$PROG: --top должен быть числом" >&2; exit 2 ;; esac
case "$HISTORY_DAYS" in ''|*[!0-9]*) echo "$PROG: --history должен быть числом" >&2; exit 2 ;; esac

declare -a CMDLOG=()
note_cmd() { CMDLOG+=("$1"); }

cat "$WORK/lib.jq" "$WORK/norm_cscli.jq" > "$WORK/nc.jq"
cat "$WORK/lib.jq" "$WORK/norm_db.jq"    > "$WORK/nd.jq"

FETCH_FROM=$(( FROM - HISTORY_DAYS * 86400 ))
FETCH_MIN=$(( (NOW - FETCH_FROM) / 60 + 2 ))
FROM_UTC="$(date -u -d "@$FETCH_FROM" '+%Y-%m-%d %H:%M:%S')"
DAY_FROM_UTC="$(date -u -d "@$FROM" '+%Y-%m-%d %H:%M:%S')"
DAY_TO_UTC="$(date -u -d "@$TO"  '+%Y-%m-%d %H:%M:%S')"

json_or_empty() { # файл -> гарантированно валидный JSON-массив
  local f="$1"
  if [ ! -s "$f" ] || ! jq -e 'type' "$f" >/dev/null 2>&1; then printf '[]' > "$f"; fi
  jq -e 'type == "array"' "$f" >/dev/null 2>&1 || printf '[]' > "$f"
}

#--------------------------------------------------------------- путь cscli --
CSCLI_DAY_COUNT=""
collect_cscli() {
  log "cscli: выгрузка алертов за $(( (NOW - FETCH_FROM) / 86400 + 1 )) сут (включая историю)…"
  note_cmd "$CSCLI alerts list --since ${FETCH_MIN}m -l 0 -o json"
  if ! "$CSCLI" alerts list --since "${FETCH_MIN}m" -l 0 -o json \
        >"$RAW/alerts_cscli.json" 2>"$RAW/cscli_alerts.err"; then
    warn "cscli alerts list вернул ошибку -- см. raw/cscli_alerts.err"
  fi
  json_or_empty "$RAW/alerts_cscli.json"

  log "cscli: выгрузка действующих решений…"
  note_cmd "$CSCLI decisions list -l 0 -o json"
  "$CSCLI" decisions list -l 0 -o json >"$RAW/decisions_active.json" 2>"$RAW/cscli_decisions.err" \
    || warn "cscli decisions list вернул ошибку -- см. raw/cscli_decisions.err"
  json_or_empty "$RAW/decisions_active.json"

  jq -f "$WORK/nc.jq" "$RAW/alerts_cscli.json" > "$WORK/norm.json"
}

#------------------------------------------------------------------ путь БД --
collect_db() {
  log "sqlite: выборка alerts/decisions из $DB…"
  local q_alerts q_dec
  q_alerts="SELECT * FROM alerts WHERE replace(substr(created_at,1,19),'T',' ') BETWEEN '$FROM_UTC' AND '$DAY_TO_UTC';"
  q_dec="SELECT d.* FROM decisions d JOIN alerts a ON d.alert_decisions = a.id \
WHERE replace(substr(a.created_at,1,19),'T',' ') BETWEEN '$FROM_UTC' AND '$DAY_TO_UTC';"
  note_cmd "sqlite3 -readonly -json \"$DB\" \"${q_alerts}\""
  sqlite3 -readonly -json "$DB" "$q_alerts"          >"$RAW/db_alerts.json"    2>"$RAW/db.err" || warn "sqlite: ошибка выборки alerts"
  sqlite3 -readonly -json "$DB" "$q_dec"             >"$RAW/db_decisions.json" 2>>"$RAW/db.err" || warn "sqlite: ошибка выборки decisions"
  sqlite3 -readonly -json "$DB" "SELECT id, machine_id FROM machines;" >"$RAW/db_machines.json" 2>>"$RAW/db.err" || true
  json_or_empty "$RAW/db_alerts.json"; json_or_empty "$RAW/db_decisions.json"; json_or_empty "$RAW/db_machines.json"

  jq -n --slurpfile a "$RAW/db_alerts.json" --slurpfile d "$RAW/db_decisions.json" \
        --slurpfile m "$RAW/db_machines.json" \
        '{alerts: ($a[0] // []), decisions: ($d[0] // []), machines: ($m[0] // [])}' \
    | jq -f "$WORK/nd.jq" > "$WORK/norm.json"

  if [ ! -s "$RAW/decisions_active.json" ]; then
    if [ "$HAVE_CSCLI" -eq 1 ]; then
      "$CSCLI" decisions list -l 0 -o json >"$RAW/decisions_active.json" 2>/dev/null || echo '[]' >"$RAW/decisions_active.json"
    else
      sqlite3 -readonly -json "$DB" \
        "SELECT value FROM decisions WHERE replace(substr(until,1,19),'T',' ') > '$(date -u '+%Y-%m-%d %H:%M:%S')';" \
        >"$RAW/db_active.json" 2>/dev/null || echo '[]' >"$RAW/db_active.json"
      json_or_empty "$RAW/db_active.json"
      jq '[ .[] | {decisions: [ {value: .value} ]} ]' "$RAW/db_active.json" >"$RAW/decisions_active.json"
    fi
    json_or_empty "$RAW/decisions_active.json"
  fi
}

if [ "$SOURCE" = "cscli" ]; then collect_cscli; else collect_db; fi

# перекрёстная проверка: сколько алертов за сутки видит БД напрямую
DB_DAY_COUNT=""
if [ "$HAVE_SQLITE" -eq 1 ]; then
  DB_DAY_COUNT="$(sqlite3 -readonly "$DB" \
    "SELECT count(*) FROM alerts WHERE replace(substr(created_at,1,19),'T',' ') BETWEEN '$DAY_FROM_UTC' AND '$DAY_TO_UTC';" 2>/dev/null || echo "")"
fi

# --- активные решения -> плоский список значений
jq '[ (. // [])[] | (.decisions // [])[] | (.value // empty) ] | unique' \
   "$RAW/decisions_active.json" > "$WORK/active_values.json" 2>/dev/null || echo '[]' > "$WORK/active_values.json"

# --- границы данных в БД (для проверки retention)
DB_MIN_E=""
if [ "$HAVE_SQLITE" -eq 1 ]; then
  _dbmin="$(sqlite3 -readonly "$DB" "SELECT min(created_at) FROM alerts;" 2>/dev/null || true)"
  if [ -n "${_dbmin:-}" ] && [ "$_dbmin" != "" ]; then
    DB_MIN_E="$(date -d "$(printf '%s' "$_dbmin" | tr 'T' ' ')" +%s 2>/dev/null || true)"
  fi
fi

OLDEST_E="$(jq -r '[ .[] | .e | select(. != null) ] | if length == 0 then "" else (min|tostring) end' "$WORK/norm.json")"
NEWEST_E="$(jq -r '[ .[] | .e | select(. != null) ] | if length == 0 then "" else (max|tostring) end' "$WORK/norm.json")"

#==============================================================================
#  Вычисление фактов
#==============================================================================
log "анализ…"
jq -n -f "$WORK/facts.jq" \
   --slurpfile all  "$WORK/norm.json" \
   --slurpfile actv "$WORK/active_values.json" \
   --argjson from "$FROM" --argjson to "$TO" --argjson off "$OFF_SEC" \
   --argjson histdays "$HISTORY_DAYS" \
   --arg critre "$CRIT_RE" --arg highre "$HIGH_RE" \
   --arg day "$DAY" --arg tz "$TZNAME" --arg source "$SOURCE" \
   --arg gen "$(date '+%Y-%m-%d %H:%M:%S %Z')" \
   > "$RAW/facts.json"

TOT_ALERTS="$(jq -r '.totals.alerts'           "$RAW/facts.json")"
TOT_SRC="$(jq -r '.totals.sources'             "$RAW/facts.json")"
TOT_CRIT="$(jq -r '.totals.critical'           "$RAW/facts.json")"
TOT_DEC="$(jq -r '.totals.decisions'           "$RAW/facts.json")"
TOT_UNBAN="$(jq -r '.totals.unbanned_sources'  "$RAW/facts.json")"

#==============================================================================
#  Журналы движка за указанные сутки
#==============================================================================
DAY_APACHE="$(date -d "$DAY 12:00:00" '+%d/%b/%Y')"
SEC_LOGS="$WORK/sec_logs.md"
: > "$SEC_LOGS"

cat_logs() {
  local f
  for f in "$@"; do
    [ -r "$f" ] || continue
    case "$f" in
      *.gz)  gzip -dc  -- "$f" 2>/dev/null || true ;;
      *.zst) zstd -dc  -- "$f" 2>/dev/null || true ;;
      *.xz)  xz   -dc  -- "$f" 2>/dev/null || true ;;
      *)     cat        -- "$f" 2>/dev/null || true ;;
    esac
  done
}

collect_logs() {
  { echo "## 11. Журналы движка за $DAY"; echo; } >>"$SEC_LOGS"

  #--- systemd -------------------------------------------------------------
  local units=() u
  if have systemctl; then
    while read -r u; do [ -n "$u" ] && units+=("$u"); done < <(
      systemctl list-units --type=service --all --no-legend 'crowdsec*' 2>/dev/null \
        | sed 's/^[^a-zA-Z0-9]*//' | awk '{print $1}' | grep -E '\.service$' || true)
  fi
  if have journalctl && [ "${#units[@]}" -gt 0 ]; then
    { echo "| Юнит | Строк за сутки | error | warning | Стартов |"; echo "| --- | ---: | ---: | ---: | ---: |"; } >>"$SEC_LOGS"
    for u in "${units[@]}"; do
      local f="$RAW/journal_${u%.service}.log"
      note_cmd "journalctl -u $u --since @$FROM --until @$TO --no-pager   # = $DAY, $TZNAME"
      journalctl -u "$u" --since "@$FROM" --until "@$TO" --no-pager -o short-iso \
        >"$f" 2>/dev/null || true
      local n e w s
      n=$(wc -l <"$f" 2>/dev/null || echo 0)
      e=$(grep -ac 'level=error\|level=fatal' "$f" 2>/dev/null || true); e=${e:-0}
      w=$(grep -ac 'level=warning'             "$f" 2>/dev/null || true); w=${w:-0}
      s=$(grep -ac 'Starting processing data'  "$f" 2>/dev/null || true); s=${s:-0}
      printf '| `%s` | %s | %s | %s | %s |\n' "$u" "$n" "$e" "$w" "$s" >>"$SEC_LOGS"
    done
    echo >>"$SEC_LOGS"
  else
    { echo "_journalctl недоступен или юниты crowdsec не найдены._"; echo; } >>"$SEC_LOGS"
  fi

  #--- crowdsec.log --------------------------------------------------------
  shopt -s nullglob
  local cslogs=( "$LOGDIR"/crowdsec.log* )
  local apilogs=( "$LOGDIR"/crowdsec_api.log* )
  shopt -u nullglob

  if [ "${#cslogs[@]}" -gt 0 ]; then
    note_cmd "grep 'time=\"$DAY' $LOGDIR/crowdsec.log*   (включая ротированные)"
    cat_logs "${cslogs[@]}" | grep -a "time=\"$DAY" >"$RAW/crowdsec_day.log" 2>/dev/null || true
    [ -s "$RAW/crowdsec_day.log" ] || cat_logs "${cslogs[@]}" | grep -a "$DAY" >"$RAW/crowdsec_day.log" 2>/dev/null || true
    local ln er wr st
    ln=$(wc -l <"$RAW/crowdsec_day.log" 2>/dev/null || echo 0)
    er=$(grep -ac 'level=error\|level=fatal' "$RAW/crowdsec_day.log" 2>/dev/null || true); er=${er:-0}
    wr=$(grep -ac 'level=warning'            "$RAW/crowdsec_day.log" 2>/dev/null || true); wr=${wr:-0}
    st=$(grep -ac 'Starting processing data' "$RAW/crowdsec_day.log" 2>/dev/null || true); st=${st:-0}
    { echo "**crowdsec.log:** строк за сутки — $ln, ошибок — $er, предупреждений — $wr, запусков движка — $st."; echo; } >>"$SEC_LOGS"
    if [ "$er" -gt 0 ] || [ "$wr" -gt 0 ]; then
      { echo "Топ сообщений об ошибках и предупреждениях:"; echo; echo '```'; } >>"$SEC_LOGS"
      grep -a 'level=error\|level=fatal\|level=warning' "$RAW/crowdsec_day.log" 2>/dev/null \
        | sed 's/^time="[^"]*"[[:space:]]*//' | sed 's/[0-9]\{1,3\}\(\.[0-9]\{1,3\}\)\{3\}/<ip>/g' \
        | sort | uniq -c | sort -rn | head -15 >>"$SEC_LOGS" || true
      { echo '```'; echo; } >>"$SEC_LOGS"
    fi
  else
    { echo "_$LOGDIR/crowdsec.log не найден (возможно, логирование идёт только в journald)._"; echo; } >>"$SEC_LOGS"
  fi

  #--- crowdsec_api.log ----------------------------------------------------
  if [ "${#apilogs[@]}" -gt 0 ]; then
    note_cmd "grep '\\[$DAY_APACHE:' $LOGDIR/crowdsec_api.log*"
    cat_logs "${apilogs[@]}" | grep -a "\[$DAY_APACHE:" >"$RAW/crowdsec_api_day.log" 2>/dev/null || true
    local an
    an=$(wc -l <"$RAW/crowdsec_api_day.log" 2>/dev/null || echo 0)
    { echo "**crowdsec_api.log:** запросов к LAPI за сутки — $an."; echo; } >>"$SEC_LOGS"
    if [ "$an" -gt 0 ]; then
      { echo "| Клиент LAPI (машина/баунсер) | Запросов | Уник. IP | Не-2xx |"; echo "| --- | ---: | ---: | ---: |"; } >>"$SEC_LOGS"
      awk -F'"' '{
             split($1, a, " "); ip = a[1]; user = a[3];
             split($3, b, " "); st = b[1];
             if (user == "" || user == "-") user = "(аноним)";
             cnt[user]++; seen[user "|" ip] = 1;
             if (st !~ /^2/) bad[user]++;
           }
           END {
             for (u in cnt) {
               uips = 0; for (k in seen) { split(k, p, "|"); if (p[1] == u) uips++ }
               printf "| `%s` | %d | %d | %d |\n", u, cnt[u], uips, (u in bad ? bad[u] : 0)
             }
           }' "$RAW/crowdsec_api_day.log" 2>/dev/null | sort -t'|' -k3 -rn | head -20 >>"$SEC_LOGS" || true
      echo >>"$SEC_LOGS"
      { echo "Коды ответов LAPI:"; echo; echo '```'; } >>"$SEC_LOGS"
      awk -F'"' '{split($3,b," "); if (b[1] != "") print b[1]}' "$RAW/crowdsec_api_day.log" 2>/dev/null \
        | sort | uniq -c | sort -rn | head -10 >>"$SEC_LOGS" || true
      { echo '```'; echo; } >>"$SEC_LOGS"
    fi
  else
    { echo "_$LOGDIR/crowdsec_api.log не найден._"; echo; } >>"$SEC_LOGS"
  fi
}

if [ "$COLLECT_LOGS" -eq 1 ]; then log "сбор журналов движка…"; collect_logs; fi

#==============================================================================
#  Состояние движка на момент аудита
#==============================================================================
SEC_STATE="$WORK/sec_state.md"
: > "$SEC_STATE"

collect_state() {
  { echo "## 12. Состояние движка на момент аудита"; echo; } >>"$SEC_STATE"
  local ver lapi
  ver="$( { "$CSCLI" version 2>/dev/null || true; } | head -3 | tr '\n' ' ' | sed 's/  */ /g; s/ *$//' )"
  [ -n "$ver" ] || ver="неизвестно"
  "$CSCLI" version  >"$RAW/state_version.txt" 2>&1 || true
  "$CSCLI" metrics  >"$RAW/state_metrics.txt" 2>&1 || true
  "$CSCLI" simulation status >"$RAW/state_simulation.txt" 2>&1 || true
  note_cmd "$CSCLI version; $CSCLI lapi status; $CSCLI machines list; $CSCLI bouncers list; $CSCLI hub list; $CSCLI metrics"

  if "$CSCLI" lapi status >"$RAW/state_lapi.txt" 2>&1; then lapi="доступен"; else lapi="**недоступен** (см. raw/state_lapi.txt)"; fi
  { echo "- Версия: \`$ver\`"; echo "- LAPI: $lapi"; } >>"$SEC_STATE"

  # из выгрузок вычищаются любые поля, похожие на ключи/пароли -- отчёт не должен содержать секретов
  local scrub
  scrub='if type == "array" then map(with_entries(select(.key | test("api_?key|password|passwd|token|secret|credential"; "i") | not))) else . end'
  { "$CSCLI" machines list -o json 2>/dev/null || echo '[]'; } | jq "$scrub" >"$RAW/state_machines.json" 2>/dev/null || echo '[]' >"$RAW/state_machines.json"
  { "$CSCLI" bouncers list -o json 2>/dev/null || echo '[]'; } | jq "$scrub" >"$RAW/state_bouncers.json" 2>/dev/null || echo '[]' >"$RAW/state_bouncers.json"
  "$CSCLI" hub list       -o json >"$RAW/state_hub.json"      2>/dev/null || echo '{}' >"$RAW/state_hub.json"

  local nm nb
  nm="$(jq -r 'if type=="array" then length else 0 end' "$RAW/state_machines.json" 2>/dev/null || echo 0)"
  nb="$(jq -r 'if type=="array" then length else 0 end' "$RAW/state_bouncers.json" 2>/dev/null || echo 0)"
  case "$nm" in ''|*[!0-9]*) nm=0 ;; esac
  case "$nb" in ''|*[!0-9]*) nb=0 ;; esac
  { echo "- Зарегистрировано машин: $nm, баунсеров: $nb"; } >>"$SEC_STATE"

  local hubtot hubtaint hubupd
  hubtot="$(jq -r '[ (if type=="object" then (.[] | select(type=="array") | .[]) else .[] end) ] | length' "$RAW/state_hub.json" 2>/dev/null || echo 0)"
  hubtaint="$(jq -r '[ (if type=="object" then (.[] | select(type=="array") | .[]) else .[] end) | select((.status // "") | test("tainted")) ] | length' "$RAW/state_hub.json" 2>/dev/null || echo 0)"
  hubupd="$(jq -r '[ (if type=="object" then (.[] | select(type=="array") | .[]) else .[] end) | select((.status // "") | test("update")) ] | length' "$RAW/state_hub.json" 2>/dev/null || echo 0)"
  { echo "- Элементов hub установлено: $hubtot (изменённых/tainted: $hubtaint, требуют обновления: $hubupd)"; echo; } >>"$SEC_STATE"

  if [ "$nb" -gt 0 ]; then
    { echo "| Баунсер | Тип | Версия | Последний запрос к LAPI |"; echo "| --- | --- | --- | --- |"; } >>"$SEC_STATE"
    jq -r 'def esc: (. // "-") | tostring | gsub("\\|"; "\\|");
           .[] | "| `\(.name|esc)` | \(.type|esc) | \(.version|esc) | \(.last_pull|esc) |"' \
       "$RAW/state_bouncers.json" 2>/dev/null >>"$SEC_STATE" || true
    echo >>"$SEC_STATE"
  fi
  if [ "$nm" -gt 0 ]; then
    { echo "| Машина | IP | Версия | Последнее обновление | Валидирована |"; echo "| --- | --- | --- | --- | :---: |"; } >>"$SEC_STATE"
    jq -r 'def esc: (. // "-") | tostring | gsub("\\|"; "\\|");
           .[] | "| `\((.machineId // .machine_id)|esc)` | \((.ipAddress // .ip_address)|esc) | \(.version|esc) | \((.updated_at // .lastUpdate)|esc) | \((.isValidated // .validated)|esc) |"' \
       "$RAW/state_machines.json" 2>/dev/null >>"$SEC_STATE" || true
    echo >>"$SEC_STATE"
  fi
  if [ -s "$RAW/state_simulation.txt" ]; then
    { echo "Режим симуляции:"; echo; echo '```'; head -20 "$RAW/state_simulation.txt"; echo '```'; echo; } >>"$SEC_STATE"
  fi
}

if [ "$COLLECT_STATE" -eq 1 ] && [ "$HAVE_CSCLI" -eq 1 ]; then log "снятие состояния движка…"; collect_state; fi


#==============================================================================
#  ТРИАЖ ХОСТА: проверка признаков компрометации штатными средствами Ubuntu
#  Все проверки только на чтение. Ничего не устанавливается и не изменяется.
#==============================================================================
HOSTDIR="$RAW/host"
FINDINGS="$WORK/findings.tsv"
SEC_HOSTSUM="$WORK/s13_hostsum.md"
SEC_CORR="$WORK/s14_corr.md"
SEC_AUTH="$WORK/s15_auth.md"
SEC_PERS="$WORK/s16_persist.md"
SEC_INTEG="$WORK/s17_integrity.md"
SEC_PROC="$WORK/s18_proc.md"
SEC_CHG="$WORK/s19_changes.md"
SEC_POST="$WORK/s20_posture.md"
: >"$FINDINGS"
declare -a SKIPPED=()

# Маскировка паролей и токенов в дампах, которые попадут в отчёт и raw/
scrub_secrets() {
  sed -E -e 's/(-p)[^[:space:]"'"'"']{3,}/\1***/g' \
         -e 's/((password|passwd|pwd|token|secret|api[_-]?key)[=:[:space:]]+)[^[:space:]"'"'"']+/\1***/Ig' \
         -e 's/(Authorization:[[:space:]]*[A-Za-z]+[[:space:]]+)[^[:space:]"'"'"']+/\1***/Ig'
}

mdcell() { printf '%s' "${1:-}" | tr '\n\t' '  ' | sed 's/|/\\|/g'; }
# add_finding ВАЖНОСТЬ КАТЕГОРИЯ ОПИСАНИЕ [КОМАНДА-ПРОВЕРКА]
add_finding() {
  local desc; desc="$(mdcell "$3")"
  [ "${#desc}" -gt 240 ] && desc="${desc:0:237}…"
  printf '%s\t%s\t%s\t%s\n' "$1" "$(mdcell "$2")" "$desc" "$(mdcell "${4:-}")" >>"$FINDINGS"
}
# краткий список из файла: первые 5 значений и счётчик остальных
list5() {
  local f="$1" cnt
  [ -s "$f" ] || return 0
  cnt=$(wc -l <"$f" 2>/dev/null || echo 0)
  head -5 "$f" 2>/dev/null | tr '\n' ' '
  [ "${cnt:-0}" -gt 5 ] && printf '… (всего %s)' "$cnt"
  return 0
}
skip_tool() { SKIPPED+=("$1 -- $2"); }
# блок кода в отчёте из файла: файл, лимит строк, куда писать
md_code() {
  local f="$1" n="$2" dst="$3"
  [ -s "$f" ] || return 0
  { echo '```'; head -n "$n" "$f"; [ "$(wc -l <"$f")" -gt "$n" ] && echo "... (всего $(wc -l <"$f") строк, полностью -- в raw/host/$(basename "$f"))"; echo '```'; echo; } >>"$dst"
  return 0
}
# файлы, изменённые в аудируемые сутки
mtime_in_window() { # каталог/файл...
  find "$@" -xdev -newermt "@$FROM" ! -newermt "@$(( TO + 1 ))" 2>/dev/null || true
}
# Жёсткие признаки: загрузка кода с передачей в интерпретатор, reverse shell,
# майнер, зачистка следов, запуск из временных каталогов. Подобраны так, чтобы не
# срабатывать на штатных скриптах Ubuntu (apt-compat, motd-news, profile.d и т.п.).
# Файлы, которых нет в базе dpkg даже на эталонной Ubuntu (создаются в postinst
# пакета base-files и подобных) -- иначе они дают вечное срабатывание "вне пакетов".
KNOWN_UNOWNED='^/etc/profile$|^/root/\.(profile|bashrc)$|^/etc/update-motd\.d/60-unminimize$|^/etc/skel/|^/etc/rc\.local$'
SUSPECT_HARD='(curl|wget)[^|;&]*\|[[:space:]]*(ba|z|d)?sh|base64[[:space:]]+(-d|--decode)[^|;&]*\|[[:space:]]*(ba)?sh|/dev/tcp/|(^|[^[:alnum:]_])(nc|ncat|netcat)[[:space:]]+-[[:alnum:]]*e|(ba)?sh[[:space:]]+-i[[:space:]]*>&|stratum\+tcp|xmrig|minerd|history[[:space:]]+-c([[:space:]]|$)|chattr[[:space:]]+\+i|(ba)?sh[[:space:]]+-c[[:space:]]*["'"'"']?\$\((curl|wget)|python3?[[:space:]]+-c[[:space:]].*(base64|socket|os\.system|subprocess)|perl[[:space:]]+-e[[:space:]].*(Socket|exec)|setsid[[:space:]]+/(tmp|var/tmp|dev/shm)/|(^|[;&|][[:space:]]*|(ba)?sh[[:space:]]+|source[[:space:]]+|\.[[:space:]]+)/(tmp|var/tmp|dev/shm)/'
# В cron-строке команда идёт после расписания и имени пользователя, поэтому путь
# во временном каталоге там подозрителен сам по себе.
CRON_TMP_RE='[[:space:]]/(tmp|var/tmp|dev/shm)/[^[:space:]]+'

# dpkg_unowned СПИСОК_ПУТЕЙ ФАЙЛ_РЕЗУЛЬТАТА -- пути, которых нет в базе dpkg.
# xargs режет вызов на порции: список путей может быть длиннее ARG_MAX.
dpkg_unowned() {
  local src="$1" dst="$2" err="$WORK/dpkg_unowned.err"
  : >"$dst"; : >"$err"
  have dpkg || return 0
  [ -s "$src" ] || return 0
  tr '\n' '\0' <"$src" | xargs -0 -r -n 200 dpkg -S 2>>"$err" >/dev/null || true
  sed -n 's/^dpkg-query: no path found matching pattern \(.*\)$/\1/p' "$err" | sort -u >"$WORK/dpkg_miss1.txt" || true
  [ -s "$WORK/dpkg_miss1.txt" ] || return 0
  # usrmerge: часть пакетов записана как /bin, /sbin, /lib -- проверяем альтернативную форму пути,
  # иначе штатные файлы (напр. /usr/bin/fusermount3 из пакета fuse3) выглядят как "ничьи"
  awk '{ p = $0; alt = ""
         if (p ~ /^\/usr\/(bin|sbin|lib|libexec)\//)  { alt = p; sub(/^\/usr/, "", alt) }
         else if (p ~ /^\/(bin|sbin|lib|libexec)\//)   { alt = "/usr" p }
         if (alt != "") print alt }' "$WORK/dpkg_miss1.txt" | sort -u >"$WORK/dpkg_alt.txt" || true
  : >"$WORK/dpkg_miss2.txt"
  if [ -s "$WORK/dpkg_alt.txt" ]; then
    : >"$WORK/dpkg_alt.err"
    tr '\n' '\0' <"$WORK/dpkg_alt.txt" | xargs -0 -r -n 200 dpkg -S 2>>"$WORK/dpkg_alt.err" >/dev/null || true
    sed -n 's/^dpkg-query: no path found matching pattern \(.*\)$/\1/p' "$WORK/dpkg_alt.err" | sort -u >"$WORK/dpkg_miss2.txt" || true
  fi
  { echo "__нет_альтернативных_путей__"; cat "$WORK/dpkg_miss2.txt"; } >"$WORK/dpkg_miss2s.txt"
  awk 'NR == FNR { miss2[$0] = 1; next }
       { p = $0; alt = ""
         if (p ~ /^\/usr\/(bin|sbin|lib|libexec)\//)  { alt = p; sub(/^\/usr/, "", alt) }
         else if (p ~ /^\/(bin|sbin|lib|libexec)\//)   { alt = "/usr" p }
         if (alt == "" || (alt in miss2)) print p }' \
      "$WORK/dpkg_miss2s.txt" "$WORK/dpkg_miss1.txt" | sort -u >"$dst" || true
  return 0
}

mkdir -p "$HOSTDIR" 2>/dev/null || true
LAST_SINCE="$(date -d "@$FROM" '+%Y-%m-%d %H:%M:%S')"
LAST_UNTIL="$(date -d "@$TO"   '+%Y-%m-%d %H:%M:%S')"
IS_ROOT=0; [ "$(id -u)" -eq 0 ] && IS_ROOT=1

#------------------------------------------------------------------------------
# Источник событий аутентификации: journald (по умолчанию в 24.04) или auth.log
#------------------------------------------------------------------------------
AUTH_SRC="нет"
collect_auth_events() {
  : >"$HOSTDIR/auth_events.txt"
  if have journalctl; then
    journalctl --since "@$FROM" --until "@$TO" --no-pager -o short-iso \
      SYSLOG_FACILITY=10 + SYSLOG_FACILITY=4 2>/dev/null >>"$HOSTDIR/auth_events.txt" || true
    [ -s "$HOSTDIR/auth_events.txt" ] && AUTH_SRC="journald (SYSLOG_FACILITY=auth,authpriv)"
  fi
  shopt -s nullglob
  local authfiles=( /var/log/auth.log* /var/log/secure* )
  shopt -u nullglob
  # auth.log читаем ТОЛЬКО если journald ничего не дал: при работающем rsyslog
  # события дублируются в обоих источниках и все счётчики удваиваются
  if [ "${#authfiles[@]}" -gt 0 ] && [ "$AUTH_SRC" = "нет" ]; then
    local tmpf="$WORK/authfile.txt"
    cat_logs "${authfiles[@]}" 2>/dev/null \
      | grep -a -E "^($(date -d "@$FROM" '+%b %e')|$(date -d "@$FROM" '+%Y-%m-%d')|$DAY)" >"$tmpf" 2>/dev/null || true
    if [ -s "$tmpf" ]; then
      cat "$tmpf" >>"$HOSTDIR/auth_events.txt"
      if [ "$AUTH_SRC" = "нет" ]; then AUTH_SRC="/var/log/auth.log"; else AUTH_SRC="$AUTH_SRC + /var/log/auth.log"; fi
    fi
  fi
  if [ "$AUTH_SRC" = "нет" ]; then
    add_finding CRIT "аудитопригодность" \
      "За $DAY нет ни одного события аутентификации: журнал не покрывает дату (journald без постоянного хранилища и/или отсутствует auth.log). Проверить компрометацию по логам за эту дату невозможно." \
      "journalctl --since '$LAST_SINCE' --until '$LAST_UNTIL' SYSLOG_FACILITY=10; ls -la /var/log/journal /var/log/auth.log*"
  fi
}

#------------------------------------------------------------------------------
# 15. Аутентификация и учётные записи
#------------------------------------------------------------------------------
check_auth() {
  { echo "## 15. Аутентификация и учётные записи"; echo;
    echo "Источник событий: \`$AUTH_SRC\`."; echo; } >>"$SEC_AUTH"

  # --- успешные SSH-входы
  grep -a -oE 'Accepted (password|publickey|keyboard-interactive[^ ]*) for [^ ]+ from [0-9a-fA-F.:]+ port [0-9]+' \
      "$HOSTDIR/auth_events.txt" 2>/dev/null | sort | uniq -c | sort -rn >"$HOSTDIR/ssh_accepted.txt" || true
  grep -a -oE 'Accepted [^ ]+ for [^ ]+ from [0-9a-fA-F.:]+' "$HOSTDIR/auth_events.txt" 2>/dev/null \
      | awk '{print $NF}' | sort -u >"$WORK/login_ips.txt" || true
  : >"$WORK/login_ips.txt.chk"; [ -s "$WORK/login_ips.txt" ] || : >"$WORK/login_ips.txt"

  local nacc; nacc=$(wc -l <"$HOSTDIR/ssh_accepted.txt" 2>/dev/null || echo 0)
  if [ "${nacc:-0}" -gt 0 ]; then
    { echo "**Успешные входы по SSH за сутки** (уникальных комбинаций: $nacc):"; echo; } >>"$SEC_AUTH"
    md_code "$HOSTDIR/ssh_accepted.txt" 25 "$SEC_AUTH"
    if grep -aqE 'Accepted [^ ]+ for root from' "$HOSTDIR/auth_events.txt" 2>/dev/null; then
      add_finding HIGH "аутентификация" "В эти сутки был успешный вход по SSH под root" \
        "grep 'Accepted .* for root from' -- в journalctl SYSLOG_FACILITY=10 за $DAY"
    fi
    if grep -aqE 'Accepted password for' "$HOSTDIR/auth_events.txt" 2>/dev/null; then
      add_finding INFO "аутентификация" "Есть успешные входы по паролю (не по ключу) -- парольная аутентификация SSH включена" \
        "sshd -T | grep -i passwordauthentication"
    fi
  else
    { echo "_Успешных SSH-входов за сутки не зафиксировано._"; echo; } >>"$SEC_AUTH"
  fi

  # --- неудачные попытки
  # одна попытка порождает и "Invalid user", и "Failed password for invalid user" --
  # считаем только вторую строку, чтобы не завышать цифру вдвое
  grep -a -oE 'Failed password for (invalid user )?[^ ]+ from [0-9a-fA-F.:]+' \
      "$HOSTDIR/auth_events.txt" 2>/dev/null >"$HOSTDIR/ssh_failed_raw.txt" || true
  local nfail ninv
  nfail=$(wc -l <"$HOSTDIR/ssh_failed_raw.txt" 2>/dev/null || echo 0)
  ninv=$(grep -ac 'Invalid user ' "$HOSTDIR/auth_events.txt" 2>/dev/null || true); ninv=${ninv:-0}
  { echo "**Неудачных парольных попыток за сутки:** ${nfail:-0}; обращений с несуществующими именами пользователей: ${ninv}."; echo; } >>"$SEC_AUTH"
  if [ "${nfail:-0}" -gt 0 ]; then
    awk '{print $NF}' "$HOSTDIR/ssh_failed_raw.txt" | sort | uniq -c | sort -rn | head -15 >"$HOSTDIR/ssh_failed_top.txt" || true
    { echo "Топ источников неудачных попыток:"; echo; } >>"$SEC_AUTH"
    md_code "$HOSTDIR/ssh_failed_top.txt" 15 "$SEC_AUTH"
  fi

  # --- btmp / wtmp
  if have lastb && [ "$IS_ROOT" -eq 1 ]; then
    lastb -F -w -s "$LAST_SINCE" -t "$LAST_UNTIL" >"$HOSTDIR/lastb.txt" 2>/dev/null || true
    sed -i '/^$/d;/^btmp begins/d' "$HOSTDIR/lastb.txt" 2>/dev/null || true
  else
    [ "$IS_ROOT" -eq 1 ] || skip_tool "lastb" "нужен root"
  fi
  if have last; then
    last -F -w -s "$LAST_SINCE" -t "$LAST_UNTIL" >"$HOSTDIR/last.txt" 2>/dev/null || true
    sed -i '/^$/d;/^wtmp begins/d' "$HOSTDIR/last.txt" 2>/dev/null || true
    if [ -s "$HOSTDIR/last.txt" ]; then
      { echo "**Сессии из wtmp за сутки** (\`last\`):"; echo; } >>"$SEC_AUTH"
      md_code "$HOSTDIR/last.txt" 25 "$SEC_AUTH"
      # IP из wtmp тоже идут в корреляцию
      awk '{for (i=1;i<=NF;i++) if ($i ~ /^([0-9]{1,3}\.){3}[0-9]{1,3}$/) print $i}' "$HOSTDIR/last.txt" \
        | sort -u >>"$WORK/login_ips.txt" || true
      sort -u -o "$WORK/login_ips.txt" "$WORK/login_ips.txt" || true
    fi
    last -x -F -w -s "$LAST_SINCE" -t "$LAST_UNTIL" 2>/dev/null | grep -aE 'reboot|shutdown' >"$HOSTDIR/reboots.txt" || true
    if [ -s "$HOSTDIR/reboots.txt" ]; then
      add_finding INFO "аудитопригодность" "В аудируемые сутки система перезагружалась или выключалась -- часть состояния (процессы, /tmp, сессии) относится уже к другому запуску" "last -x -s '$LAST_SINCE' -t '$LAST_UNTIL'"
    fi
  else
    skip_tool "last" "не установлен (util-linux)"
  fi

  # --- sudo и повышение привилегий
  grep -a -E 'sudo(\[[0-9]+\])?:.*COMMAND=|su(\[[0-9]+\])?:.*session opened|pkexec(\[[0-9]+\])?:' "$HOSTDIR/auth_events.txt" 2>/dev/null \
    >"$HOSTDIR/privesc.txt" || true
  if [ -s "$HOSTDIR/privesc.txt" ]; then
    { echo "**Повышение привилегий (sudo/su/pkexec) за сутки:** $(wc -l <"$HOSTDIR/privesc.txt") событий."; echo; } >>"$SEC_AUTH"
    md_code "$HOSTDIR/privesc.txt" 20 "$SEC_AUTH"
    if grep -aqE 'COMMAND=.*('"$SUSPECT_HARD"')' "$HOSTDIR/privesc.txt" 2>/dev/null; then
      add_finding HIGH "аутентификация" "Через sudo выполнялись команды загрузки и запуска стороннего кода" "см. raw/host/privesc.txt"
    fi
  fi
  # счёт PAM-отказов не зависит от наличия событий sudo
  local nsf; nsf=$(grep -ac 'authentication failure' "$HOSTDIR/auth_events.txt" 2>/dev/null || true)
  [ "${nsf:-0}" -gt 0 ] && add_finding INFO "аутентификация" "Событий 'authentication failure' за сутки: ${nsf}" "journalctl --since '$LAST_SINCE' --until '$LAST_UNTIL' SYSLOG_FACILITY=10 | grep 'authentication failure'"

  # --- изменения учётных записей
  grep -a -E 'useradd|usermod|userdel|groupadd|gpasswd|chpasswd|passwd\[[0-9]+\]:.*password changed' \
    "$HOSTDIR/auth_events.txt" 2>/dev/null >"$HOSTDIR/account_changes.txt" || true
  if [ -s "$HOSTDIR/account_changes.txt" ]; then
    add_finding HIGH "учётные записи" "В аудируемые сутки создавались/изменялись учётные записи или пароли ($(wc -l <"$HOSTDIR/account_changes.txt") событий)" "см. raw/host/account_changes.txt"
    { echo "**Изменения учётных записей за сутки:**"; echo; } >>"$SEC_AUTH"
    md_code "$HOSTDIR/account_changes.txt" 20 "$SEC_AUTH"
  fi

  # --- аккаунты с UID 0 и пустыми паролями
  awk -F: '$3 == 0 && $1 != "root" {print $1}' /etc/passwd 2>/dev/null >"$WORK/uid0.txt" || true
  if [ -s "$WORK/uid0.txt" ]; then
    add_finding CRIT "учётные записи" "Кроме root есть учётные записи с UID 0: $(tr '\n' ' ' <"$WORK/uid0.txt")" "awk -F: '\$3==0' /etc/passwd"
  fi
  if [ "$IS_ROOT" -eq 1 ] && [ -r /etc/shadow ]; then
    awk -F: '($2 == "" ) {print $1}' /etc/shadow 2>/dev/null >"$WORK/nopass.txt" || true
    if [ -s "$WORK/nopass.txt" ]; then
      add_finding CRIT "учётные записи" "Учётные записи с пустым паролем: $(tr '\n' ' ' <"$WORK/nopass.txt")" "awk -F: '\$2==\"\"' /etc/shadow"
    fi
  else
    skip_tool "/etc/shadow" "нужен root -- не проверены пустые пароли"
  fi

  # --- пользователи с оболочкой входа
  getent passwd 2>/dev/null | awk -F: '$7 !~ /(nologin|false|sync)$/ {printf "| `%s` | %s | %s | `%s` |\n", $1, $3, $6, $7}' \
    >"$WORK/shell_users.txt" || true
  if [ -s "$WORK/shell_users.txt" ]; then
    { echo "**Учётные записи с оболочкой входа:**"; echo;
      echo "| Пользователь | UID | Домашний каталог | Оболочка |"; echo "| --- | ---: | --- | --- |"; } >>"$SEC_AUTH"
    cat "$WORK/shell_users.txt" >>"$SEC_AUTH"; echo >>"$SEC_AUTH"
  fi

  # --- изменения критичных файлов учёта
  local acctf
  for acctf in /etc/passwd /etc/shadow /etc/group /etc/gshadow /etc/sudoers; do
    [ -e "$acctf" ] || continue
    if [ -n "$(mtime_in_window "$acctf")" ]; then
      add_finding HIGH "учётные записи" "Файл $acctf изменялся в аудируемые сутки ($(stat -c '%y' "$acctf" 2>/dev/null | cut -d. -f1))" "stat $acctf; ls -la /etc/*-  # резервные копии с прошлым содержимым"
    fi
  done
  if [ -d /etc/sudoers.d ] && [ -n "$(mtime_in_window /etc/sudoers.d)" ]; then
    add_finding HIGH "учётные записи" "Каталог /etc/sudoers.d изменялся в аудируемые сутки" "ls -la /etc/sudoers.d; grep -r NOPASSWD /etc/sudoers.d"
  fi
  grep -rlsE 'NOPASSWD' /etc/sudoers /etc/sudoers.d 2>/dev/null >"$WORK/nopasswd.txt" || true
  if [ -s "$WORK/nopasswd.txt" ]; then
    add_finding INFO "учётные записи" "Правила sudo с NOPASSWD присутствуют в: $(tr '\n' ' ' <"$WORK/nopasswd.txt")" "grep -r NOPASSWD /etc/sudoers /etc/sudoers.d"
  fi

  # --- SSH-ключи
  : >"$HOSTDIR/authorized_keys.txt"
  local home u akf
  while IFS=: read -r u _ uid _ _ home _; do
    [ -d "$home" ] || continue
    for akf in "$home/.ssh/authorized_keys" "$home/.ssh/authorized_keys2"; do
      [ -r "$akf" ] || continue
      { echo "### $u ($akf), изменён: $(stat -c '%y' "$akf" 2>/dev/null | cut -d. -f1)"; } >>"$HOSTDIR/authorized_keys.txt"
      if have ssh-keygen; then ssh-keygen -lf "$akf" 2>/dev/null >>"$HOSTDIR/authorized_keys.txt" || true
      else awk '{print $1, $NF}' "$akf" >>"$HOSTDIR/authorized_keys.txt"; fi
      if [ -n "$(mtime_in_window "$akf")" ]; then
        add_finding CRIT "постоянство" "Файл SSH-ключей $akf изменён в аудируемые сутки -- возможна установка ключа злоумышленника" "ssh-keygen -lf $akf; stat $akf"
      fi
      [ "$u" = "root" ] && add_finding INFO "постоянство" "У root есть authorized_keys ($(grep -c '^ssh-\|^ecdsa\|^sk-' "$akf" 2>/dev/null || echo 0) ключей)" "ssh-keygen -lf $akf"
    done
  done < <(getent passwd 2>/dev/null || cat /etc/passwd)
  if [ -s "$HOSTDIR/authorized_keys.txt" ]; then
    { echo "**Установленные SSH-ключи:**"; echo; } >>"$SEC_AUTH"
    md_code "$HOSTDIR/authorized_keys.txt" 30 "$SEC_AUTH"
  fi

  # --- эффективная конфигурация sshd
  if have sshd && [ "$IS_ROOT" -eq 1 ]; then
    sshd -T 2>/dev/null | grep -iE '^(port|permitrootlogin|passwordauthentication|permitemptypasswords|pubkeyauthentication|allowusers|allowgroups|x11forwarding|allowtcpforwarding|permittunnel|maxauthtries)' \
      >"$HOSTDIR/sshd_effective.txt" || true
    if [ -s "$HOSTDIR/sshd_effective.txt" ]; then
      { echo "**Действующая конфигурация sshd:**"; echo; } >>"$SEC_AUTH"
      md_code "$HOSTDIR/sshd_effective.txt" 20 "$SEC_AUTH"
      grep -qi '^permitrootlogin yes' "$HOSTDIR/sshd_effective.txt" && \
        add_finding MED "конфигурация" "sshd разрешает вход root по SSH (PermitRootLogin yes)" "sshd -T | grep permitrootlogin"
      grep -qi '^permitemptypasswords yes' "$HOSTDIR/sshd_effective.txt" && \
        add_finding CRIT "конфигурация" "sshd разрешает вход с пустым паролем (PermitEmptyPasswords yes)" "sshd -T | grep permitemptypasswords"
    fi
  fi
  return 0
}

#------------------------------------------------------------------------------
# 16. Механизмы постоянства
#------------------------------------------------------------------------------
check_persistence() {
  { echo "## 16. Механизмы закрепления в системе"; echo; } >>"$SEC_PERS"

  # --- ld.so.preload: классический признак руткита пользовательского уровня
  if [ -e /etc/ld.so.preload ]; then
    add_finding CRIT "постоянство" "Существует /etc/ld.so.preload (содержимое: $(tr '\n' ' ' </etc/ld.so.preload 2>/dev/null)) -- в штатной Ubuntu этого файла нет" "cat /etc/ld.so.preload"
  fi
  grep -sqE 'LD_PRELOAD|LD_LIBRARY_PATH' /etc/environment 2>/dev/null && \
    add_finding HIGH "постоянство" "В /etc/environment задан LD_PRELOAD/LD_LIBRARY_PATH" "cat /etc/environment"

  # --- cron
  : >"$HOSTDIR/cron.txt"
  shopt -s nullglob
  local cronf cronfiles=( /etc/crontab /etc/cron.d/* /etc/cron.hourly/* /etc/cron.daily/* /etc/cron.weekly/* /etc/cron.monthly/* /var/spool/cron/crontabs/* /etc/anacrontab )
  shopt -u nullglob
  : >"$HOSTDIR/cron_changed.txt"; : >"$WORK/cron_paths.txt"
  for cronf in "${cronfiles[@]}"; do
    [ -r "$cronf" ] || continue
    { echo "===== $cronf (изменён $(stat -c '%y' "$cronf" 2>/dev/null | cut -d. -f1)) ====="; scrub_secrets <"$cronf"; } >>"$HOSTDIR/cron.txt" 2>/dev/null || true
    [ -n "$(mtime_in_window "$cronf")" ] && echo "$cronf" >>"$HOSTDIR/cron_changed.txt"
    case "$cronf" in /var/spool/cron/crontabs/*) ;; *) echo "$cronf" >>"$WORK/cron_paths.txt" ;; esac
    if grep -qsE "$CRON_TMP_RE" "$cronf" 2>/dev/null; then
      add_finding HIGH "постоянство" "Задание cron $cronf ссылается на файл во временном каталоге (/tmp, /var/tmp, /dev/shm)" "cat $cronf"
    fi
    if grep -qsE "$SUSPECT_HARD" "$cronf" 2>/dev/null; then
      add_finding CRIT "постоянство" "В задании cron $cronf есть команда загрузки и запуска стороннего кода" "cat $cronf   # искать: curl|wget в пайпе на sh, /dev/tcp/, nc -e, запуск из /tmp"
    fi
  done
  { echo "Заданий cron найдено: ${#cronfiles[@]} (полный дамп -- в \`raw/host/cron.txt\`)."; echo; } >>"$SEC_PERS"
  if [ -s "$HOSTDIR/cron_changed.txt" ]; then
    add_finding HIGH "постоянство" "Задания cron изменены в аудируемые сутки: $(list5 "$HOSTDIR/cron_changed.txt")" "stat <файл>; cat <файл>"
  fi
  # пользовательские crontab существуют только если их кто-то создал
  shopt -s nullglob
  local ucron=( /var/spool/cron/crontabs/* )
  shopt -u nullglob
  [ "${#ucron[@]}" -gt 0 ] && add_finding INFO "постоянство" "Есть пользовательские crontab: $(printf '%s ' "${ucron[@]##*/}")" "crontab -l -u <пользователь>"
  # системные cron-файлы, не принадлежащие пакетам
  if [ -s "$WORK/cron_paths.txt" ] && have dpkg; then
    dpkg_unowned "$WORK/cron_paths.txt" "$HOSTDIR/cron_unowned.txt"
    if [ -s "$HOSTDIR/cron_unowned.txt" ]; then
      add_finding MED "постоянство" "Системные задания cron вне пакетов ($(wc -l <"$HOSTDIR/cron_unowned.txt")): $(list5 "$HOSTDIR/cron_unowned.txt")" "cat raw/host/cron_unowned.txt"
    fi
  fi
  if have atq; then
    atq >"$HOSTDIR/atq.txt" 2>/dev/null || true
    [ -s "$HOSTDIR/atq.txt" ] && add_finding MED "постоянство" "Есть отложенные задания at ($(wc -l <"$HOSTDIR/atq.txt"))" "atq; at -c <номер>"
  fi

  # --- systemd
  if have systemctl; then
    systemctl list-unit-files --state=enabled --no-legend --no-pager 2>/dev/null | awk '{print $1}' >"$WORK/enabled_units.txt" || true
    systemctl list-timers --all --no-pager 2>/dev/null >"$HOSTDIR/timers.txt" || true
    systemctl list-units --failed --no-pager 2>/dev/null >"$HOSTDIR/failed_units.txt" || true
    local nu; nu=$(wc -l <"$WORK/enabled_units.txt" 2>/dev/null || echo 0)
    { echo "Включённых юнитов systemd: ${nu:-0}. Таймеры -- в \`raw/host/timers.txt\`."; echo; } >>"$SEC_PERS"

    # юниты, чьи файлы изменены в аудируемые сутки
    mtime_in_window /etc/systemd/system /usr/local/lib/systemd/system /run/systemd/system 2>/dev/null >"$HOSTDIR/units_changed.txt" || true
    if [ -s "$HOSTDIR/units_changed.txt" ]; then
      add_finding HIGH "постоянство" "Файлы юнитов systemd изменены в аудируемые сутки: $(list5 "$HOSTDIR/units_changed.txt")" "find /etc/systemd/system -newermt '@$FROM' ! -newermt '@$((TO+1))'"
      { echo "**Изменённые в эти сутки юниты systemd:**"; echo; } >>"$SEC_PERS"
      md_code "$HOSTDIR/units_changed.txt" 20 "$SEC_PERS"
    fi

    # включённые юниты, файлы которых не принадлежат ни одному пакету
    if [ "${nu:-0}" -gt 0 ] && have dpkg; then
      : >"$WORK/unit_paths.txt"
      # один вызов systemctl show на все юниты сразу
      # shellcheck disable=SC2046
      systemctl show -p Id -p FragmentPath $(tr '\n' ' ' <"$WORK/enabled_units.txt") --no-pager 2>/dev/null \
        | awk -F= '/^FragmentPath=/ && $2 != "" {print $2}' >"$WORK/unit_paths.txt" || true
      if [ -s "$WORK/unit_paths.txt" ]; then
        dpkg_unowned "$WORK/unit_paths.txt" "$WORK/units_unowned.raw"
        grep -v '^/run/' "$WORK/units_unowned.raw" >"$HOSTDIR/units_unowned.txt" 2>/dev/null || true
        if [ -s "$HOSTDIR/units_unowned.txt" ]; then
          add_finding MED "постоянство" "Включены юниты systemd, не принадлежащие ни одному пакету ($(wc -l <"$HOSTDIR/units_unowned.txt")) -- это может быть как локальная настройка, так и закрепление" "cat raw/host/units_unowned.txt; systemctl cat <юнит>"
          { echo "**Включённые юниты вне пакетов** (локальные или добавленные):"; echo; } >>"$SEC_PERS"
          md_code "$HOSTDIR/units_unowned.txt" 20 "$SEC_PERS"
        fi
      fi
    fi
    # содержимое юнитов: ExecStart с загрузкой и запуском стороннего кода
    find /etc/systemd/system /usr/local/lib/systemd/system /run/systemd/system \
         -maxdepth 2 -type f \( -name '*.service' -o -name '*.timer' -o -name '*.path' \) 2>/dev/null \
      >"$WORK/unit_files.txt" || true
    if [ -s "$WORK/unit_files.txt" ]; then
      while read -r uf; do
        [ -r "$uf" ] || continue
        if grep -qsE "$SUSPECT_HARD" "$uf" 2>/dev/null; then
          add_finding CRIT "постоянство" "В юните systemd $uf есть команда загрузки и запуска стороннего кода" "systemctl cat $(basename "$uf"); cat $uf"
        fi
      done <"$WORK/unit_files.txt"
    fi

    # пользовательские юниты
    shopt -s nullglob
    local uu=( /home/*/.config/systemd/user/*.service /root/.config/systemd/user/*.service )
    shopt -u nullglob
    if [ "${#uu[@]}" -gt 0 ]; then
      printf '%s\n' "${uu[@]}" >"$HOSTDIR/user_units.txt"
      add_finding MED "постоянство" "Найдены пользовательские юниты systemd (${#uu[@]}) -- частый способ закрепления без прав root" "cat raw/host/user_units.txt"
    fi
  else
    skip_tool "systemctl" "недоступен -- юниты и таймеры не проверены"
  fi

  # --- скрипты автозапуска и профили оболочек
  : >"$HOSTDIR/startup_changed.txt"
  shopt -s nullglob
  local sfiles=( /etc/rc.local /etc/profile /etc/profile.d/* /etc/bash.bashrc /root/.bashrc /root/.profile /home/*/.bashrc /home/*/.profile /home/*/.bash_profile /etc/update-motd.d/* )
  shopt -u nullglob
  local sf
  : >"$WORK/startup_paths.txt"
  for sf in "${sfiles[@]}"; do
    [ -r "$sf" ] || continue
    [ -n "$(mtime_in_window "$sf")" ] && echo "$sf" >>"$HOSTDIR/startup_changed.txt"
    case "$sf" in /home/*|/root/*) ;; *) echo "$sf" >>"$WORK/startup_paths.txt" ;; esac
    if grep -qsE "$SUSPECT_HARD" "$sf" 2>/dev/null; then
      add_finding CRIT "постоянство" "В скрипте автозапуска $sf есть команда загрузки и запуска стороннего кода" "cat $sf   # искать: curl|wget в пайпе на sh, /dev/tcp/, nc -e, history -c"
    fi
  done
  if [ -s "$WORK/startup_paths.txt" ] && have dpkg; then
    dpkg_unowned "$WORK/startup_paths.txt" "$WORK/startup_unowned.raw"
    grep -vE "$KNOWN_UNOWNED" "$WORK/startup_unowned.raw" >"$HOSTDIR/startup_unowned.txt" 2>/dev/null || true
    if [ -s "$HOSTDIR/startup_unowned.txt" ]; then
      add_finding MED "постоянство" "Файлы автозапуска вне пакетов ($(wc -l <"$HOSTDIR/startup_unowned.txt")): $(list5 "$HOSTDIR/startup_unowned.txt")" "cat raw/host/startup_unowned.txt"
    fi
  fi
  if [ -s "$HOSTDIR/startup_changed.txt" ]; then
    add_finding HIGH "постоянство" "Изменены скрипты автозапуска/профили оболочек: $(list5 "$HOSTDIR/startup_changed.txt")" "stat <файл>; diff с резервной копией"
    { echo "**Изменённые в эти сутки скрипты автозапуска:**"; echo; } >>"$SEC_PERS"
    md_code "$HOSTDIR/startup_changed.txt" 15 "$SEC_PERS"
  fi
  [ -e /etc/rc.local ] && add_finding INFO "постоянство" "Присутствует /etc/rc.local (в Ubuntu 24.04 по умолчанию его нет)" "cat /etc/rc.local"
  return 0
}

#------------------------------------------------------------------------------
# 17. Целостность пакетов, файлов и ядра
#------------------------------------------------------------------------------
check_integrity() {
  { echo "## 17. Целостность пакетов, системных файлов и ядра"; echo; } >>"$SEC_INTEG"

  # --- сверка контрольных сумм файлов пакетов
  if [ "$QUICK" -eq 1 ]; then
    skip_tool "dpkg --verify" "пропущено из-за --quick"
    { echo "_Сверка контрольных сумм пропущена (\`--quick\`)._"; echo; } >>"$SEC_INTEG"
  elif have dpkg; then
    log "проверка целостности файлов пакетов (dpkg --verify, может занять до минуты)…"
    dpkg --verify >"$HOSTDIR/dpkg_verify.txt" 2>/dev/null || true
    # строки вида "??5??????   /path" ; символ 'c' в 2-й колонке = конфигурационный файл
    grep -v ' c /' "$HOSTDIR/dpkg_verify.txt" 2>/dev/null | grep -E '^[?M5][?M5]|^missing' >"$HOSTDIR/dpkg_verify_bin.txt" || true
    local nver ncfg
    nver=$(wc -l <"$HOSTDIR/dpkg_verify_bin.txt" 2>/dev/null || echo 0)
    ncfg=$(grep -c ' c /' "$HOSTDIR/dpkg_verify.txt" 2>/dev/null || true); ncfg=${ncfg:-0}
    local nmiss; nmiss=$(grep -c '^missing' "$HOSTDIR/dpkg_verify.txt" 2>/dev/null || true); nmiss=${nmiss:-0}
    { echo "Проверка \`dpkg --verify\`: расхождений в файлах пакетов -- **${nver:-0}** (из них отсутствующих файлов -- ${nmiss}), плюс ${ncfg} изменённых конфигурационных файлов, что штатно."; echo; } >>"$SEC_INTEG"
    if [ "${nver:-0}" -gt 500 ]; then
      add_finding INFO "целостность" "dpkg --verify показывает ${nver} расхождений -- такой масштаб почти всегда означает, что база dpkg не соответствует образу (контейнер, образ собран распаковкой, минимизированный rootfs), а не подмену файлов. Разбирать точечно по важным пакетам" "dpkg --verify openssh-server coreutils systemd bash"
    elif [ "${nver:-0}" -gt 0 ]; then
      add_finding HIGH "целостность" "Файлы из пакетов не совпадают с контрольными суммами dpkg (${nver} шт.) -- возможна подмена системных программ" "dpkg --verify; dpkg -S <файл>; apt install --reinstall <пакет>"
      md_code "$HOSTDIR/dpkg_verify_bin.txt" 25 "$SEC_INTEG"
    fi
    if have debsums; then
      debsums -c >"$HOSTDIR/debsums.txt" 2>/dev/null || true
      [ -s "$HOSTDIR/debsums.txt" ] && add_finding HIGH "целостность" "debsums сообщает о расхождениях ($(wc -l <"$HOSTDIR/debsums.txt") файлов)" "debsums -c"
    else
      skip_tool "debsums" "не установлен; dpkg --verify покрывает только файлы с записанными суммами"
    fi
  fi

  # --- SUID/SGID вне пакетов
  # /usr/lib -- самое удобное место спрятать SUID-бэкдор среди тысяч файлов, поэтому входит в базовый список
  local suidroots="/usr/bin /usr/sbin /usr/lib /usr/libexec /usr/local /opt /srv /var/lib /var/tmp /tmp /home /root"
  local capsroots="$suidroots"
  [ "$DEEP" -eq 1 ] && suidroots="/"
  if [ "$DEEP" -eq 1 ]; then log "поиск SUID/SGID по всей файловой системе (--deep, это долго)…"
  else log "поиск SUID/SGID-файлов в системных каталогах…"; fi
  # shellcheck disable=SC2086
  find $suidroots -xdev \( -perm -4000 -o -perm -2000 \) -type f -print 2>/dev/null | sort >"$HOSTDIR/suid.txt" || true
  if [ -s "$HOSTDIR/suid.txt" ] && have dpkg; then
    dpkg_unowned "$HOSTDIR/suid.txt" "$HOSTDIR/suid_unowned.txt"
    if [ -s "$HOSTDIR/suid_unowned.txt" ]; then
      add_finding CRIT "целостность" "SUID/SGID-файлы, которых нет в базе dpkg ($(wc -l <"$HOSTDIR/suid_unowned.txt")): $(head -3 "$HOSTDIR/suid_unowned.txt" | tr '\n' ' ') -- либо установлены не пакетом, либо оставлены злоумышленником для возврата прав root" "cat raw/host/suid_unowned.txt; ls -la <файл>"
      { echo "**SUID/SGID вне пакетов:**"; echo; } >>"$SEC_INTEG"
      md_code "$HOSTDIR/suid_unowned.txt" 20 "$SEC_INTEG"
    else
      { echo "SUID/SGID-файлов найдено $(wc -l <"$HOSTDIR/suid.txt"), все принадлежат установленным пакетам."; echo; } >>"$SEC_INTEG"
    fi
  fi
  # свежие SUID-файлы
  local newsuid; newsuid="$(mtime_in_window $suidroots -perm -4000 -type f 2>/dev/null | head -20 || true)"
  [ -n "$newsuid" ] && add_finding CRIT "целостность" "SUID-файлы с датой изменения в аудируемые сутки: $(printf '%s' "$newsuid" | tr '\n' ' ' | cut -c1-200)" "ls -la <файл>; dpkg -S <файл>"

  # --- POSIX capabilities
  if have getcap; then
    # shellcheck disable=SC2086
    getcap -r $capsroots 2>/dev/null >"$HOSTDIR/capabilities.txt" || true
    if [ -s "$HOSTDIR/capabilities.txt" ]; then
      { echo "**Файлы с POSIX capabilities:**"; echo; } >>"$SEC_INTEG"
      md_code "$HOSTDIR/capabilities.txt" 15 "$SEC_INTEG"
      grep -qE 'cap_sys_admin|cap_sys_ptrace|cap_sys_module|cap_dac_override' "$HOSTDIR/capabilities.txt" 2>/dev/null && \
        add_finding MED "целостность" "Есть файлы с опасными capabilities (cap_sys_admin/ptrace/module/dac_override)" "getcap -r /"
    fi
  else
    skip_tool "getcap" "не установлен (libcap2-bin)"
  fi

  # --- неизменяемые атрибуты на файлах учёта (приём сокрытия правок)
  if have lsattr; then
    lsattr /etc/passwd /etc/shadow /etc/group /etc/crontab /etc/ld.so.preload 2>/dev/null >"$HOSTDIR/lsattr.txt" || true
    if grep -qE '^....i|^-{4}i' "$HOSTDIR/lsattr.txt" 2>/dev/null; then
      add_finding HIGH "целостность" "На системных файлах установлен атрибут immutable (i) -- часто используется, чтобы закрепить подменённый файл" "lsattr /etc/passwd /etc/shadow; chattr -i <файл>"
    fi
  fi

  # --- ядро: taint и модули
  if [ -r /proc/sys/kernel/tainted ]; then
    local taint; taint="$(cat /proc/sys/kernel/tainted 2>/dev/null || echo 0)"
    { echo "Флаг taint ядра: \`$taint\` (0 -- ядро «чистое»)."; echo; } >>"$SEC_INTEG"
    if [ "${taint:-0}" -ne 0 ]; then
      if [ $(( taint & 8192 )) -ne 0 ]; then
        add_finding HIGH "ядро" "Ядро помечено как загрузившее НЕПОДПИСАННЫЙ модуль (taint bit 13, значение $taint)" "cat /proc/sys/kernel/tainted; journalctl -k | grep -i 'module verification\\|taint'"
      fi
      if [ $(( taint & 4096 )) -ne 0 ]; then
        add_finding MED "ядро" "Ядро помечено как загрузившее модуль вне дерева ядра (taint bit 12, значение $taint) -- обычно DKMS-драйверы" "modinfo <модуль>; dkms status"
      fi
    fi
  fi
  if have lsmod; then
    lsmod >"$HOSTDIR/lsmod.txt" 2>/dev/null || true
    if have modinfo && have dpkg && [ -s "$HOSTDIR/lsmod.txt" ]; then
      : >"$WORK/modpaths.txt"
      local m
      while read -r m _; do
        [ "$m" = "Module" ] && continue
        modinfo -n "$m" 2>/dev/null >>"$WORK/modpaths.txt" || true
      done <"$HOSTDIR/lsmod.txt"
      if [ -s "$WORK/modpaths.txt" ]; then
        dpkg_unowned "$WORK/modpaths.txt" "$HOSTDIR/modules_unowned.txt"
        if [ -s "$HOSTDIR/modules_unowned.txt" ]; then
          add_finding MED "ядро" "Загружены модули ядра, не принадлежащие пакетам ($(wc -l <"$HOSTDIR/modules_unowned.txt")) -- это либо DKMS, либо посторонний модуль" "cat raw/host/modules_unowned.txt; modinfo <модуль>"
        fi
      fi
    fi
  fi

  # --- сервисы, работающие с устаревшими/удалёнными библиотеками
  if have needrestart; then
    # -r l и NEEDRESTART_MODE=l гарантируют режим "только список": без них
    # needrestart при restart=a в конфиге ПЕРЕЗАПУСТИТ службы, а скрипт обязан быть read-only
    NEEDRESTART_MODE=l needrestart -r l -b >"$HOSTDIR/needrestart.txt" 2>/dev/null || true
    grep -q '^NEEDRESTART-SVC' "$HOSTDIR/needrestart.txt" 2>/dev/null && \
      add_finding INFO "целостность" "Есть службы, работающие со старыми версиями библиотек ($(grep -c '^NEEDRESTART-SVC' "$HOSTDIR/needrestart.txt")) -- после подмены или обновления файлов их стоит перезапустить" "needrestart -b"
  fi
  return 0
}

#------------------------------------------------------------------------------
# 18. Процессы и сеть (состояние на момент аудита)
#------------------------------------------------------------------------------
check_procnet() {
  { echo "## 18. Процессы и сеть (состояние на момент запуска скрипта)"; echo;
    echo "> Раздел описывает систему **сейчас**, а не в аудируемые сутки: процессы и соединения за прошедшую дату не восстановимы штатными средствами."; echo; } >>"$SEC_PROC"

  ps -eo pid,ppid,user,etimes,rss,stat,args --sort=-etimes 2>/dev/null | scrub_secrets >"$HOSTDIR/ps.txt" || true

  # --- процессы с удалённым исполняемым файлом
  : >"$HOSTDIR/proc_deleted.txt"; : >"$HOSTDIR/proc_tmp.txt"
  local pid exe
  for pid in /proc/[0-9]*; do
    exe="$(readlink "$pid/exe" 2>/dev/null || true)"
    [ -n "$exe" ] || continue
    case "$exe" in
      *"(deleted)") printf '%s\t%s\t%s\n' "${pid#/proc/}" "$exe" "$(tr '\0' ' ' <"$pid/cmdline" 2>/dev/null | cut -c1-120)" >>"$HOSTDIR/proc_deleted.txt" ;;
    esac
    case "$exe" in
      /tmp/*|/var/tmp/*|/dev/shm/*|/run/user/*|/home/*/.cache/*)
        printf '%s\t%s\t%s\n' "${pid#/proc/}" "$exe" "$(tr '\0' ' ' <"$pid/cmdline" 2>/dev/null | cut -c1-120)" >>"$HOSTDIR/proc_tmp.txt" ;;
    esac
  done
  if [ -s "$HOSTDIR/proc_deleted.txt" ]; then
    add_finding HIGH "процессы" "Работают процессы, чей исполняемый файл удалён с диска ($(wc -l <"$HOSTDIR/proc_deleted.txt")) -- типично для запущенного и подчищённого за собой вредоноса (но бывает и после обновления пакетов)" "cat raw/host/proc_deleted.txt; ls -l /proc/<PID>/exe"
    { echo "**Процессы с удалённым исполняемым файлом:**"; echo; } >>"$SEC_PROC"
    md_code "$HOSTDIR/proc_deleted.txt" 15 "$SEC_PROC"
  fi
  if [ -s "$HOSTDIR/proc_tmp.txt" ]; then
    add_finding CRIT "процессы" "Работают процессы, запущенные из временных каталогов (/tmp, /var/tmp, /dev/shm, /run/user)" "cat raw/host/proc_tmp.txt; ls -l /proc/<PID>/exe"
    { echo "**Процессы из временных каталогов:**"; echo; } >>"$SEC_PROC"
    md_code "$HOSTDIR/proc_tmp.txt" 15 "$SEC_PROC"
  fi

  # --- сокеты
  : >"$HOSTDIR/listen.txt"; : >"$HOSTDIR/estab.txt"
  if have ss; then
    ss -tulpnH >"$HOSTDIR/listen.txt" 2>/dev/null || true
    ss -tunpH state established >"$HOSTDIR/estab.txt" 2>/dev/null || true
  elif have netstat; then
    netstat -tulpn 2>/dev/null | tail -n +3 >"$HOSTDIR/listen.txt" || true
    netstat -tunp 2>/dev/null | grep -a ESTABLISHED >"$HOSTDIR/estab.txt" || true
  else
    skip_tool "ss/netstat" "не установлены (iproute2/net-tools) -- используется разбор /proc/net/tcp"
    local f h
    for f in /proc/net/tcp /proc/net/tcp6; do
      [ -r "$f" ] || continue
      awk 'NR>1 && $4=="0A" {split($2,a,":"); print a[2]}' "$f" 2>/dev/null | while read -r h; do
        printf 'LISTEN\tпорт %d\n' "0x$h" >>"$HOSTDIR/listen.txt"
      done
    done
    sort -u -o "$HOSTDIR/listen.txt" "$HOSTDIR/listen.txt" 2>/dev/null || true
  fi
  if [ -s "$HOSTDIR/listen.txt" ]; then
    { echo "**Слушающие сокеты:**"; echo; } >>"$SEC_PROC"
    md_code "$HOSTDIR/listen.txt" 30 "$SEC_PROC"
  fi

  # --- программы за слушающими сокетами: принадлежат ли они пакетам
  if [ -s "$HOSTDIR/listen.txt" ] && have dpkg; then
    grep -oE 'pid=[0-9]+' "$HOSTDIR/listen.txt" 2>/dev/null | cut -d= -f2 | sort -u >"$WORK/listen_pids.txt" || true
    : >"$WORK/listen_exes.txt"
    while read -r pid; do
      [ -n "$pid" ] || continue
      exe="$(readlink "/proc/$pid/exe" 2>/dev/null || true)"
      [ -n "$exe" ] && printf '%s\n' "${exe% (deleted)}" >>"$WORK/listen_exes.txt"
    done <"$WORK/listen_pids.txt"
    if [ -s "$WORK/listen_exes.txt" ]; then
      sort -u -o "$WORK/listen_exes.txt" "$WORK/listen_exes.txt"
      dpkg_unowned "$WORK/listen_exes.txt" "$HOSTDIR/listen_unowned.txt"
      if [ -s "$HOSTDIR/listen_unowned.txt" ]; then
        add_finding MED "сеть" "Сетевые порты слушают программы вне пакетов: $(list5 "$HOSTDIR/listen_unowned.txt")" "ss -tulpn; dpkg -S <путь>"
      fi
    fi
  fi
  if [ -s "$HOSTDIR/estab.txt" ]; then
    { echo "**Установленные соединения:** $(wc -l <"$HOSTDIR/estab.txt") (полностью -- в \`raw/host/estab.txt\`)."; echo; } >>"$SEC_PROC"
    md_code "$HOSTDIR/estab.txt" 20 "$SEC_PROC"
    grep -aoE '[0-9]{1,3}(\.[0-9]{1,3}){3}:(4444|1337|31337|6667|9001|8888|23|2323)\b' "$HOSTDIR/estab.txt" 2>/dev/null >"$WORK/badports.txt" || true
    [ -s "$WORK/badports.txt" ] && add_finding MED "сеть" "Есть соединения на порты, характерные для управляющих каналов: $(list5 "$WORK/badports.txt")" "ss -tunp state established"
  fi

  # --- активные сессии
  if have who; then who >"$HOSTDIR/who.txt" 2>/dev/null || true; fi
  if have loginctl; then loginctl list-sessions --no-pager >"$HOSTDIR/sessions.txt" 2>/dev/null || true; fi
  if [ -s "$HOSTDIR/who.txt" ]; then
    { echo "**Активные сессии сейчас:**"; echo; } >>"$SEC_PROC"
    md_code "$HOSTDIR/who.txt" 15 "$SEC_PROC"
  fi
  return 0
}

#------------------------------------------------------------------------------
# 19. Изменения в системе за аудируемые сутки
#------------------------------------------------------------------------------
check_changes() {
  { echo "## 19. Изменения в системе за $DAY"; echo; } >>"$SEC_CHG"

  # --- пакеты: dpkg.log ведётся в локальном времени
  shopt -s nullglob
  local dpkglogs=( /var/log/dpkg.log* )
  shopt -u nullglob
  if [ "${#dpkglogs[@]}" -gt 0 ]; then
    cat_logs "${dpkglogs[@]}" | grep -a "^$DAY " >"$HOSTDIR/dpkg_day.log" 2>/dev/null || true
    local ninst nrem
    ninst=$(grep -ac ' install \| upgrade ' "$HOSTDIR/dpkg_day.log" 2>/dev/null || true); ninst=${ninst:-0}
    nrem=$(grep -ac ' remove \| purge '   "$HOSTDIR/dpkg_day.log" 2>/dev/null || true); nrem=${nrem:-0}
    { echo "**Пакеты:** операций установки/обновления -- $ninst, удаления -- $nrem."; echo; } >>"$SEC_CHG"
    if [ "$ninst" -gt 0 ] || [ "$nrem" -gt 0 ]; then
      grep -aE ' (install|upgrade|remove|purge) ' "$HOSTDIR/dpkg_day.log" 2>/dev/null | awk '{print $1, $2, $3, $4, $5}' >"$HOSTDIR/dpkg_day_short.txt" || true
      md_code "$HOSTDIR/dpkg_day_short.txt" 25 "$SEC_CHG"
      add_finding INFO "изменения" "В аудируемые сутки менялся состав пакетов (установок/обновлений: $ninst, удалений: $nrem)" "grep '^$DAY ' /var/log/dpkg.log*"
    fi
  fi

  # --- apt: кто и какой командой это запускал
  shopt -s nullglob
  local aptlogs=( /var/log/apt/history.log* )
  shopt -u nullglob
  if [ "${#aptlogs[@]}" -gt 0 ]; then
    cat_logs "${aptlogs[@]}" | awk -v d="$DAY" '
      /^Start-Date:/ { keep = ($2 == d); buf = "" }
      keep { buf = buf $0 "\n" }
      /^End-Date:/ { if (keep) printf "%s", buf; keep = 0 }' >"$HOSTDIR/apt_day.log" 2>/dev/null || true
    if [ -s "$HOSTDIR/apt_day.log" ]; then
      { echo "**Команды apt за эти сутки:**"; echo; } >>"$SEC_CHG"
      md_code "$HOSTDIR/apt_day.log" 40 "$SEC_CHG"
      grep -a 'Requested-By:' "$HOSTDIR/apt_day.log" 2>/dev/null | sort -u >"$WORK/apt_by.txt" || true
      [ -s "$WORK/apt_by.txt" ] && add_finding INFO "изменения" "Пакеты в эти сутки ставились от имени: $(tr '\n' ' ' <"$WORK/apt_by.txt")" "grep -A3 '^Start-Date: $DAY' /var/log/apt/history.log"
    fi
  fi

  # --- snap
  if have snap; then
    snap changes 2>/dev/null | grep -a "$DAY" >"$HOSTDIR/snap_day.txt" || true
    [ -s "$HOSTDIR/snap_day.txt" ] && { echo "**Изменения snap за сутки:**"; echo; } >>"$SEC_CHG" && md_code "$HOSTDIR/snap_day.txt" 15 "$SEC_CHG"
  fi

  # --- изменённые системные файлы
  log "поиск файлов, изменённых в аудируемые сутки…"
  mtime_in_window /etc -type f 2>/dev/null | head -300 >"$HOSTDIR/changed_etc.txt" || true
  mtime_in_window /usr/bin /usr/sbin /usr/lib /usr/local /opt -type f 2>/dev/null | head -300 >"$HOSTDIR/changed_bin.txt" || true
  mtime_in_window /root /home -maxdepth 5 -type f 2>/dev/null | grep -vE '\.(cache|log|swp)$' | head -200 >"$HOSTDIR/changed_home.txt" || true
  mtime_in_window /boot -type f 2>/dev/null >"$HOSTDIR/changed_boot.txt" || true
  local nec nbc
  nec=$(wc -l <"$HOSTDIR/changed_etc.txt" 2>/dev/null || echo 0)
  nbc=$(wc -l <"$HOSTDIR/changed_bin.txt" 2>/dev/null || echo 0)
  local trunc=""; { [ "${nec:-0}" -ge 300 ] || [ "${nbc:-0}" -ge 300 ]; } && trunc=" (списки обрезаны, показаны первые 300 -- фактически файлов может быть больше)"
  { echo "**Файлы, изменённые в эти сутки${trunc}:** /etc -- ${nec:-0}, системные каталоги программ -- ${nbc:-0}, /root и /home -- $(wc -l <"$HOSTDIR/changed_home.txt" 2>/dev/null || echo 0), /boot -- $(wc -l <"$HOSTDIR/changed_boot.txt" 2>/dev/null || echo 0)."; echo; } >>"$SEC_CHG"
  [ "${nec:-0}" -gt 0 ] && md_code "$HOSTDIR/changed_etc.txt" 25 "$SEC_CHG"
  if [ "${nbc:-0}" -gt 0 ]; then
    # изменение программ вне пакетных операций -- главный признак подмены
    if [ ! -s "$HOSTDIR/dpkg_day.log" ]; then
      add_finding HIGH "изменения" "В системных каталогах программ изменено ${nbc} файлов, при этом операций dpkg в эти сутки не было -- подмена вне менеджера пакетов" "cat raw/host/changed_bin.txt; dpkg -S <файл>; dpkg --verify"
    else
      add_finding INFO "изменения" "В системных каталогах программ изменено ${nbc} файлов (в эти же сутки были операции dpkg -- скорее всего это они)" "cat raw/host/changed_bin.txt"
    fi
    md_code "$HOSTDIR/changed_bin.txt" 25 "$SEC_CHG"
  fi
  [ -s "$HOSTDIR/changed_boot.txt" ] && add_finding HIGH "изменения" "Изменены файлы в /boot (ядро, initramfs, загрузчик)" "cat raw/host/changed_boot.txt"

  # --- файлы во временных каталогах
  mtime_in_window /tmp /var/tmp /dev/shm -type f -not -path "$WORK/*" 2>/dev/null | head -100 >"$HOSTDIR/tmp_files.txt" || true
  if [ -s "$HOSTDIR/tmp_files.txt" ]; then
    { echo "**Файлы во временных каталогах с датой изменения в эти сутки:**"; echo; } >>"$SEC_CHG"
    md_code "$HOSTDIR/tmp_files.txt" 20 "$SEC_CHG"
    mtime_in_window /tmp /var/tmp /dev/shm -type f -perm -u+x -not -path "$WORK/*" 2>/dev/null >"$HOSTDIR/tmp_exec.txt" || true
    [ -s "$HOSTDIR/tmp_exec.txt" ] && add_finding HIGH "изменения" "Во временных каталогах появились исполняемые файлы: $(list5 "$HOSTDIR/tmp_exec.txt")" "file <путь>; sha256sum <путь>; полный список -- raw/host/tmp_files.txt"
  fi
  return 0
}

#------------------------------------------------------------------------------
# 20. Защитные подсистемы и обновления безопасности
#------------------------------------------------------------------------------
check_posture() {
  { echo "## 20. Защитные подсистемы и обновления безопасности"; echo; } >>"$SEC_POST"

  # --- пригодность журнала для ретроспективы
  if [ -d /var/log/journal ]; then
    { echo "- journald: постоянное хранилище включено (\`/var/log/journal\`), ретроспектива за прошлые даты доступна."; } >>"$SEC_POST"
  else
    { echo "- journald: **постоянное хранилище выключено** -- журнал живёт в памяти и обнуляется при перезагрузке."; } >>"$SEC_POST"
    add_finding MED "аудитопригодность" "journald пишет только в память (нет /var/log/journal): после перезагрузки события за прошлые даты недоступны" "mkdir -p /var/log/journal && systemd-tmpfiles --create --prefix /var/log/journal && systemctl restart systemd-journald"
  fi
  if have journalctl; then
    journalctl --disk-usage >"$HOSTDIR/journal_usage.txt" 2>/dev/null || true
    journalctl --list-boots --no-pager >"$HOSTDIR/boots.txt" 2>/dev/null || true
  fi

  # --- AppArmor
  if have aa-status; then
    aa-status >"$HOSTDIR/apparmor.txt" 2>/dev/null || true
    if [ -s "$HOSTDIR/apparmor.txt" ]; then
      local unconf; unconf="$(grep -oE '[0-9]+ processes are unconfined[^.]*' "$HOSTDIR/apparmor.txt" | head -1 || true)"
      { echo "- AppArmor: $(head -1 "$HOSTDIR/apparmor.txt")${unconf:+, $unconf}"; } >>"$SEC_POST"
      grep -qE '[1-9][0-9]* profiles are in complain mode' "$HOSTDIR/apparmor.txt" 2>/dev/null && \
        add_finding INFO "защита" "Часть профилей AppArmor в режиме complain (только журналирование, без блокировки)" "aa-status"
    fi
  else
    { echo "- AppArmor: \`aa-status\` недоступен (нужен root и пакет apparmor)."; } >>"$SEC_POST"
    skip_tool "aa-status" "не установлен или нужен root"
  fi

  # --- межсетевой экран
  if have ufw && [ "$IS_ROOT" -eq 1 ]; then
    ufw status verbose >"$HOSTDIR/ufw.txt" 2>/dev/null || true
    if grep -q 'Status: inactive' "$HOSTDIR/ufw.txt" 2>/dev/null; then
      { echo "- ufw: **выключен**"; } >>"$SEC_POST"
      add_finding INFO "защита" "Межсетевой экран ufw выключен" "ufw status verbose"
    else
      { echo "- ufw: $(grep -m1 'Status:' "$HOSTDIR/ufw.txt" 2>/dev/null || echo '?')"; } >>"$SEC_POST"
    fi
  fi
  if have nft && [ "$IS_ROOT" -eq 1 ]; then
    nft list ruleset >"$HOSTDIR/nftables.txt" 2>/dev/null || true
    local nnft; nnft=$(wc -l <"$HOSTDIR/nftables.txt" 2>/dev/null || echo 0); nnft=${nnft:-0}
    if [ "$nnft" -eq 0 ]; then
      { echo "- nftables: набор правил пуст или недоступен для чтения"; } >>"$SEC_POST"
    else
      { echo "- nftables: строк в наборе правил -- $nnft (дамп в \`raw/host/nftables.txt\`)"; } >>"$SEC_POST"
    fi
    # баунсер CrowdSec должен создавать свои наборы
    if [ -s "$HOSTDIR/nftables.txt" ] && ! grep -qi 'crowdsec' "$HOSTDIR/nftables.txt" 2>/dev/null; then
      add_finding INFO "защита" "В наборе правил nftables нет цепочек CrowdSec -- решения о блокировке, возможно, никем не применяются" "nft list ruleset | grep -i crowdsec; cscli bouncers list"
    fi
  fi

  # --- аудит ядра
  if have auditctl && [ "$IS_ROOT" -eq 1 ]; then
    auditctl -l >"$HOSTDIR/auditctl.txt" 2>/dev/null || true
    if grep -q 'No rules' "$HOSTDIR/auditctl.txt" 2>/dev/null; then
      add_finding INFO "аудитопригодность" "auditd установлен, но правил нет -- события доступа к файлам и запуска процессов не записываются" "auditctl -l; /etc/audit/rules.d/"
    fi
  elif ! have auditctl; then
    { echo "- auditd: не установлен (в Ubuntu 24.04 по умолчанию отсутствует)."; } >>"$SEC_POST"
    add_finding INFO "аудитопригодность" "auditd не установлен: нет журнала запуска процессов и доступа к файлам, ретроспективный разбор ограничен" "apt install auditd audispd-plugins"
  else
    { echo "- auditd: установлен, но правила не прочитаны (нужен root)."; } >>"$SEC_POST"
    skip_tool "auditctl -l" "нужен root"
  fi

  # --- необновлённые пакеты
  if [ -x /usr/lib/update-notifier/apt-check ]; then
    /usr/lib/update-notifier/apt-check --human-readable >"$HOSTDIR/apt_check.txt" 2>/dev/null || true
    # реальный текст: "N of these updates is a standard security update." / "... are ESM Apps security updates."
    local nsec; nsec="$(grep -oE '[0-9]+ of these updates (is|are)[^.]*security' "$HOSTDIR/apt_check.txt" 2>/dev/null | grep -oE '^[0-9]+' | head -1 || true)"
    if [ -n "${nsec:-}" ] && [ "${nsec:-0}" -gt 0 ]; then
      add_finding MED "обновления" "Не установлено обновлений безопасности: $nsec" "apt update && apt upgrade; pro security-status"
    fi
    { echo "- Обновления: $(tr '\n' ' ' <"$HOSTDIR/apt_check.txt" 2>/dev/null)"; } >>"$SEC_POST"
  fi
  if have pro; then
    # команда обращается к contracts.canonical.com: ограничиваем ожидание
    timeout 15 pro security-status >"$HOSTDIR/pro_security_status.txt" 2>/dev/null || true
    [ -s "$HOSTDIR/pro_security_status.txt" ] && { echo "- Ubuntu Pro: $(grep -m1 -E 'packages? (are|is)' "$HOSTDIR/pro_security_status.txt" 2>/dev/null || echo 'см. raw/host/pro_security_status.txt')"; } >>"$SEC_POST"
  fi
  # --- автоматические обновления
  shopt -s nullglob
  local uulogs=( /var/log/unattended-upgrades/unattended-upgrades.log* )
  shopt -u nullglob
  if [ "${#uulogs[@]}" -gt 0 ]; then
    cat_logs "${uulogs[@]}" | grep -a "^$DAY" >"$HOSTDIR/unattended_day.log" 2>/dev/null || true
    [ -s "$HOSTDIR/unattended_day.log" ] && { echo "- unattended-upgrades: в эти сутки работал ($(wc -l <"$HOSTDIR/unattended_day.log") строк, см. raw/host/)"; } >>"$SEC_POST"
  fi
  { echo; echo "Версия ядра: \`$(uname -r)\`, система: \`$(grep -m1 '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2- | tr -d '"' || echo '?')\`, окружение: \`$( (have systemd-detect-virt && systemd-detect-virt) 2>/dev/null || echo '?')\`."; echo; } >>"$SEC_POST"
  return 0
}

#------------------------------------------------------------------------------
# 14. Корреляция данных CrowdSec с состоянием хоста
#------------------------------------------------------------------------------
check_correlation() {
  { echo "## 14. Корреляция: атаки CrowdSec против состояния хоста"; echo; } >>"$SEC_CORR"
  [ -s "$RAW/facts.json" ] || { echo "_Нет данных CrowdSec для сопоставления._" >>"$SEC_CORR"; echo >>"$SEC_CORR"; return 0; }

  jq -r '.sources[]?.value' "$RAW/facts.json" 2>/dev/null | sort -u >"$WORK/attacker_ips.txt" || true
  local natt; natt=$(wc -l <"$WORK/attacker_ips.txt" 2>/dev/null || echo 0)

  # --- 1. атакующий IP, который успешно вошёл в систему
  : >"$WORK/matched_login.txt"
  if [ -s "$WORK/attacker_ips.txt" ] && [ -s "$WORK/login_ips.txt" ]; then
    comm -12 "$WORK/attacker_ips.txt" "$WORK/login_ips.txt" >"$WORK/matched_login.txt" 2>/dev/null || true
  fi
  if [ -s "$WORK/matched_login.txt" ]; then
    add_finding CRIT "корреляция" "IP-адреса, по которым CrowdSec фиксировал атаку в эти сутки, ЗАРЕГИСТРИРОВАЛИСЬ в системе успешно: $(list5 "$WORK/matched_login.txt")" "grep <IP> в journalctl SYSLOG_FACILITY=10; cscli alerts list -i <IP>"
    { echo "> **Совпадение по входам.** Следующие адреса и атаковали машину, и успешно прошли аутентификацию:"; echo ">"; } >>"$SEC_CORR"
    sed 's/^/> - `/; s/$/`/' "$WORK/matched_login.txt" >>"$SEC_CORR"
    echo >>"$SEC_CORR"
  else
    { echo "- Успешных входов с адресов, атаковавших машину в эти сутки, не обнаружено (сверено $natt адресов из CrowdSec с журналом аутентификации)."; echo; } >>"$SEC_CORR"
  fi

  # --- 2. атакующий IP среди текущих соединений
  if [ -s "$WORK/attacker_ips.txt" ] && [ -s "$HOSTDIR/estab.txt" ]; then
    grep -aoFf "$WORK/attacker_ips.txt" "$HOSTDIR/estab.txt" 2>/dev/null | sort -u >"$WORK/matched_conn.txt" || true
    if [ -s "$WORK/matched_conn.txt" ]; then
      add_finding HIGH "корреляция" "С атаковавшими адресами прямо сейчас установлены сетевые соединения: $(list5 "$WORK/matched_conn.txt")" "ss -tunp state established | grep <IP>"
    fi
  fi

  # --- 3. изменения в системе рядом по времени с критичными срабатываниями
  jq -r '.critical_alerts[]?.e' "$RAW/facts.json" 2>/dev/null >"$WORK/crit_epochs.txt" || true
  if [ -s "$WORK/crit_epochs.txt" ]; then
    : >"$WORK/changes_ts.txt"
    local d
    for d in "$HOSTDIR/changed_etc.txt" "$HOSTDIR/changed_bin.txt" "$HOSTDIR/changed_home.txt"; do
      [ -s "$d" ] || continue
      while read -r p; do
        [ -e "$p" ] || continue
        printf '%s\t%s\n' "$p" "$(stat -c '%Y' "$p" 2>/dev/null || echo 0)" >>"$WORK/changes_ts.txt"
      done <"$d"
    done
    if [ -s "$WORK/changes_ts.txt" ]; then
      awk -F'\t' -v W=3600 'NR==FNR { a[++n] = $1 + 0; next }
                     { for (i = 1; i <= n; i++) { d = $2 - a[i]; if (d < 0) d = -d; if (d <= W) { print $1 "\t" $2; break } } }' \
          "$WORK/crit_epochs.txt" "$WORK/changes_ts.txt" >"$HOSTDIR/changes_near_alerts.txt" || true
      if [ -s "$HOSTDIR/changes_near_alerts.txt" ]; then
        add_finding HIGH "корреляция" "Файлы изменялись в пределах часа от критичных срабатываний CrowdSec ($(wc -l <"$HOSTDIR/changes_near_alerts.txt") шт.) -- проверить, не результат ли это успешной эксплуатации" "cat raw/host/changes_near_alerts.txt"
        { echo "**Изменения файлов в пределах ±1 ч от критичных срабатываний:**"; echo; } >>"$SEC_CORR"
        { echo '```'; \
          while IFS=$'\t' read -r p ts; do printf '%s  %s\n' "$(date -d "@$ts" '+%Y-%m-%d %H:%M:%S')" "$p"; done <"$HOSTDIR/changes_near_alerts.txt" | head -25; echo '```'; echo; } >>"$SEC_CORR"
      fi
    fi
  fi
  return 0
}

#------------------------------------------------------------------------------
# 13. Сводка признаков компрометации
#------------------------------------------------------------------------------
render_findings() {
  local ncrit nhigh nmed ninfo ntot
  awk -F'\t' '!seen[$1 FS $3]++' "$FINDINGS" >"$WORK/findings_uniq.tsv" 2>/dev/null || cp "$FINDINGS" "$WORK/findings_uniq.tsv"
  mv "$WORK/findings_uniq.tsv" "$FINDINGS"
  ncrit=$(grep -c '^CRIT' "$FINDINGS" 2>/dev/null || true); ncrit=${ncrit:-0}
  nhigh=$(grep -c '^HIGH' "$FINDINGS" 2>/dev/null || true); nhigh=${nhigh:-0}
  nmed=$(grep -c '^MED'   "$FINDINGS" 2>/dev/null || true); nmed=${nmed:-0}
  ninfo=$(grep -c '^INFO' "$FINDINGS" 2>/dev/null || true); ninfo=${ninfo:-0}
  ntot=$(wc -l <"$FINDINGS" 2>/dev/null || echo 0)
  HOST_CRIT="$ncrit"; HOST_HIGH="$nhigh"; HOST_MED="$nmed"; HOST_INFO="$ninfo"; HOST_TOTAL="$ntot"

  { echo "## 13. Триаж хоста: признаки, требующие проверки"; echo;
    echo "| Важность | Что означает | Найдено |"; echo "| :---: | --- | ---: |";
    echo "| **КРИТ** | требует немедленной проверки: прямые признаки постороннего доступа | $ncrit |";
    echo "| **ВЫС** | сильный признак: либо компрометация, либо объяснимое администратором действие | $nhigh |";
    echo "| СРЕД | отклонение от типовой конфигурации, требует объяснения | $nmed |";
    echo "| СПРАВ | контекст и слабые сигналы, полезные при разборе | $ninfo |";
    echo; } >>"$SEC_HOSTSUM"

  if [ "$ntot" -eq 0 ]; then
    { echo "Проверки не дали срабатываний. Это не доказывает отсутствие компрометации: см. ограничения в последнем разделе."; echo; } >>"$SEC_HOSTSUM"
    if [ "${#SKIPPED[@]}" -gt 0 ]; then
      { echo "**Важно: часть проверок не выполнялась:**"; echo; } >>"$SEC_HOSTSUM"
      printf -- '- %s\n' "${SKIPPED[@]}" >>"$SEC_HOSTSUM"
      { echo; } >>"$SEC_HOSTSUM"
    fi
    return 0
  fi

  { echo "| # | Важность | Категория | Признак | Как проверить |"; echo "| ---: | :---: | :---: | --- | --- |"; } >>"$SEC_HOSTSUM"
  awk -F'\t' 'BEGIN { OFS = "\t"; r["CRIT"] = 1; r["HIGH"] = 2; r["MED"] = 3; r["INFO"] = 4 }
              !seen[$1 FS $3]++ { print (r[$1] ? r[$1] : 9), $1, $2, $3, $4 }' "$FINDINGS" \
    | sort -t"$(printf '\t')" -k1,1n -k3,3 \
    | awk -F'\t' 'BEGIN { l["CRIT"] = "**КРИТ**"; l["HIGH"] = "**ВЫС**"; l["MED"] = "СРЕД"; l["INFO"] = "СПРАВ" }
                  { n++; printf "| %d | %s | %s | %s | %s |\n", n, (l[$2] ? l[$2] : $2), $3, $4, ($5 == "" ? "-" : "`" $5 "`") }' \
    >>"$SEC_HOSTSUM"
  { echo; } >>"$SEC_HOSTSUM"

  if [ "$ncrit" -gt 0 ] || [ "$nhigh" -gt 0 ]; then
    { echo "**Что делать с находками уровня КРИТ и ВЫС.** Каждая из них -- это гипотеза, а не приговор: сначала проверьте, нет ли законного объяснения (работы администратора, обновление, DKMS-модуль, локальный юнит). Если объяснения нет, при разборе не перезагружайте машину и не удаляйте файлы: снимите копии \`raw/\`, журналы и, по возможности, образ диска -- перезагрузка уничтожает процессы, сетевые соединения и содержимое /tmp."; echo; } >>"$SEC_HOSTSUM"
  fi
  if [ "${#SKIPPED[@]}" -gt 0 ]; then
    { echo "**Проверки, которые не удалось выполнить:**"; echo; } >>"$SEC_HOSTSUM"
    printf -- '- %s\n' "${SKIPPED[@]}" >>"$SEC_HOSTSUM"
    { echo; } >>"$SEC_HOSTSUM"
  fi
  return 0
}

#------------------------------------------------------------------------------
#  Запуск триажа
#------------------------------------------------------------------------------
run_host_triage() {
  note_cmd "# --- триаж хоста ---"
  note_cmd "journalctl --since '$LAST_SINCE' --until '$LAST_UNTIL' SYSLOG_FACILITY=10 + SYSLOG_FACILITY=4"
  note_cmd "last -F -w -s '$LAST_SINCE' -t '$LAST_UNTIL'   # и lastb для неудачных попыток"
  note_cmd "dpkg --verify   # сверка контрольных сумм файлов пакетов"
  note_cmd "dpkg -S <пути>  # принадлежность файлов пакетам (SUID, юниты, cron, модули)"
  note_cmd "find <каталоги> -newermt '@$FROM' ! -newermt '@$(( TO + 1 ))'   # изменения за сутки"
  note_cmd "systemctl list-unit-files --state=enabled; systemctl list-timers --all"
  note_cmd "ss -tulpn; ss -tunp state established; ps -eo pid,ppid,user,etimes,rss,stat,args"
  note_cmd "readlink /proc/*/exe   # процессы из временных каталогов и с удалённым файлом"
  log "триаж хоста: сбор событий аутентификации…"
  collect_auth_events || warn "сбор событий аутентификации завершился с ошибкой"
  log "триаж хоста: учётные записи и входы…"
  check_auth        || warn "проверка аутентификации завершилась с ошибкой"
  log "триаж хоста: механизмы закрепления…"
  check_persistence || warn "проверка постоянства завершилась с ошибкой"
  log "триаж хоста: целостность файлов…"
  check_integrity   || warn "проверка целостности завершилась с ошибкой"
  log "триаж хоста: процессы и сеть…"
  check_procnet     || warn "проверка процессов и сети завершилась с ошибкой"
  log "триаж хоста: изменения в системе…"
  check_changes     || warn "проверка изменений завершилась с ошибкой"
  log "триаж хоста: защитные подсистемы…"
  check_posture     || warn "проверка защитных подсистем завершилась с ошибкой"
  log "триаж хоста: корреляция с CrowdSec…"
  check_correlation || warn "корреляция завершилась с ошибкой"
  render_findings   || warn "не удалось построить сводку признаков"
  cp -f "$FINDINGS" "$HOSTDIR/findings.tsv" 2>/dev/null || true
  return 0
}

HOST_CRIT=0; HOST_HIGH=0; HOST_MED=0; HOST_INFO=0; HOST_TOTAL=0
if [ "$HOST_CHECK" -eq 1 ]; then
  if [ "$(uname -s)" != "Linux" ]; then
    warn "триаж хоста рассчитан на Linux -- пропущен"
    HOST_CHECK=0
  else
    run_host_triage
  fi
fi

#==============================================================================
#  Retention и перекрёстные проверки
#==============================================================================
RET_AGE="$(sed -n '/^[[:space:]]*flush:/,/^[^[:space:]]/p' "$CS_CONFIG" 2>/dev/null \
           | grep -E '^[[:space:]]*max_age:' | head -1 | sed 's/.*max_age:[[:space:]]*//' | tr -d '"'"'"' ' || true)"
RET_ITEMS="$(sed -n '/^[[:space:]]*flush:/,/^[^[:space:]]/p' "$CS_CONFIG" 2>/dev/null \
           | grep -E '^[[:space:]]*max_items:' | head -1 | sed 's/.*max_items:[[:space:]]*//' | tr -d '"'"'"' ' || true)"
if [ ! -r "$CS_CONFIG" ]; then
  RET_AGE="конфиг недоступен"; RET_ITEMS="конфиг недоступен"
else
  [ -n "$RET_AGE" ]   || RET_AGE="не задан явно (по умолчанию 7d)"
  [ -n "$RET_ITEMS" ] || RET_ITEMS="не задан явно (по умолчанию 5000)"
fi

RETENTION_ALARM=0
OLDEST_H="-"; NEWEST_H="-"
[ -n "$OLDEST_E" ] && OLDEST_H="$(date -d "@$OLDEST_E" '+%Y-%m-%d %H:%M')"
[ -n "$NEWEST_E" ] && NEWEST_H="$(date -d "@$NEWEST_E" '+%Y-%m-%d %H:%M')"
if [ -n "${DB_MIN_E:-}" ]; then
  # самая старая запись во всей БД -- надёжный признак того, что сутки вычищены
  [ "$DB_MIN_E" -gt "$TO" ] && RETENTION_ALARM=1
  OLDEST_H="$(date -d "@$DB_MIN_E" '+%Y-%m-%d %H:%M')"
elif [ -n "$OLDEST_E" ] && [ "$OLDEST_E" -gt "$TO" ]; then
  RETENTION_ALARM=1
fi

#==============================================================================
#  Сборка отчёта
#==============================================================================
log "сборка отчёта…"
w() { printf '%s\n' "$*" >>"$REPORT"; }
: > "$REPORT"

w "# Отчёт о попытках вторжения — \`$HOSTN\` — $DAY"
w ""
w "| | |"
w "| --- | --- |"
w "| Аудируемые сутки | **$DAY** 00:00:00 – 23:59:59 ($TZNAME) |"
w "| Хост | \`$HOSTN\` |"
w "| Источник данных | $( [ "$SOURCE" = cscli ] && echo 'CrowdSec LAPI через cscli' || echo "БД CrowdSec напрямую (\`$DB\`)" ) |"
w "| Окно истории для повторных нарушителей | $HISTORY_DAYS сут. до даты |"
w "| Отчёт сформирован | $(date '+%Y-%m-%d %H:%M:%S %Z') |"
w "| Инструмент | \`$PROG $VERSION\` (режим read-only) |"
w ""
if [ "$RETENTION_ALARM" -eq 1 ]; then
  w "> **ВНИМАНИЕ: данных за $DAY в базе нет.** Самая старая запись в БД — $OLDEST_H, то есть позже конца аудируемых суток."
  if [ -r "$CS_CONFIG" ]; then
    w "> Скорее всего дата уже вычищена по retention: \`db_config.flush.max_age\` = $RET_AGE, \`max_items\` = $RET_ITEMS. Отчёт ниже будет пустым."
  else
    w "> Скорее всего дата уже вычищена по retention (по умолчанию CrowdSec держит алерты 7 суток). Отчёт ниже будет пустым."
  fi
  w "> Восстановить картину можно только повторным прогоном ротированных логов через движок — см. раздел «Методика»."
  w ""
fi
TOC="1 Сводка · 2 Активность по часам · 3 Сценарии · 4 Источники · 5 География · 6 Критичное · 7 Решения · 8 Без блокировки · 9 Повторные · 10 Машины"
if [ -s "$SEC_LOGS"  ]; then TOC="$TOC · 11 Журналы";   fi
if [ -s "$SEC_STATE" ]; then TOC="$TOC · 12 Состояние"; fi
if [ "$HOST_CHECK" -eq 1 ]; then
  TOC="$TOC · **13 Признаки компрометации** · 14 Корреляция · 15 Учётные записи · 16 Закрепление · 17 Целостность · 18 Процессы и сеть · 19 Изменения · 20 Защита"
fi
TOC="$TOC · 21 Методика"
if [ "$HOST_CHECK" -eq 1 ]; then
  if [ "${HOST_CRIT:-0}" -gt 0 ] || [ "${HOST_HIGH:-0}" -gt 0 ]; then
    w "> **Триаж хоста: требуется разбор.** Признаков уровня КРИТ -- ${HOST_CRIT}, высокой важности -- ${HOST_HIGH} (всего срабатываний: ${HOST_TOTAL}). Список с командами проверки -- в разделе 13, сопоставление с атаками CrowdSec -- в разделе 14."
    w ""
  else
    w "> **Триаж хоста: явных признаков компрометации не найдено** (срабатываний уровня СРЕД -- ${HOST_MED:-0}, справочных -- ${HOST_INFO:-0}). Это не доказательство чистоты машины: перечень ограничений -- в последнем разделе."
    w ""
  fi
fi
w "**Содержание:** $TOC"
w ""
w "---"
w ""

jq -r -f "$WORK/render.jq" \
   --argjson off "$OFF_SEC" --argjson top "$TOP" \
   "$RAW/facts.json" >>"$REPORT"

[ -s "$SEC_LOGS" ]  && cat "$SEC_LOGS"  >>"$REPORT"
[ -s "$SEC_STATE" ] && cat "$SEC_STATE" >>"$REPORT"
for _sec in "${SEC_HOSTSUM:-}" "${SEC_CORR:-}" "${SEC_AUTH:-}" "${SEC_PERS:-}" \
            "${SEC_INTEG:-}" "${SEC_PROC:-}" "${SEC_CHG:-}" "${SEC_POST:-}"; do
  [ -n "$_sec" ] && [ -s "$_sec" ] && cat "$_sec" >>"$REPORT"
done

#--------------------------------------------------------------- раздел 21 --
w "## 21. Методика, ограничения и сырые данные"
w ""
w "### Как собраны данные"
w ""
w "- Аудируемое окно: \`$FROM\`–\`$TO\` (epoch), то есть $DAY 00:00:00–23:59:59 по $TZNAME; в БД CrowdSec время хранится в UTC, пересчёт выполнен скриптом."
w "- Основной источник: **$SOURCE**. Алерты нормализованы в единый формат, затем посчитаны агрегаты."
w "- Границы данных в выборке: от $OLDEST_H до $NEWEST_H."
if [ "${DST_SHIFT:-0}" -eq 1 ]; then
  w "- **В эти сутки происходит перевод часов.** Времена в разделах 2-9 приведены по смещению $TZOFF_STR (действует большую часть суток); события до перевода могут быть смещены на час. Точные значения -- в \`raw/facts.json\` (epoch, UTC)."
fi
if [ -r "$CS_CONFIG" ]; then
  w "- Retention БД (из \`$CS_CONFIG\`): \`db_config.flush.max_age\` = $RET_AGE, \`max_items\` = $RET_ITEMS."
else
  w "- Retention БД: файл \`$CS_CONFIG\` недоступен, значения не прочитаны (по умолчанию CrowdSec держит алерты 7 суток / 5000 записей)."
fi
if [ -n "$DB_DAY_COUNT" ]; then
  w "- Перекрёстная проверка: LAPI/выборка дала **$TOT_ALERTS** алертов за сутки, прямой запрос к sqlite — **$DB_DAY_COUNT**."
  if [ "$SOURCE" = "cscli" ] && [ "$DB_DAY_COUNT" != "$TOT_ALERTS" ]; then
    w "  Расхождение обычно означает, что cscli работает с удалённым LAPI, а локальная БД принадлежит другому инстансу, либо часть алертов пришла из CAPI."
  fi
fi
w ""
w "### Что этот отчёт не показывает"
w ""
cat >>"$REPORT" <<'MDEOF'
- **Только то, что попало в логи и было распознано парсерами.** Если сервис не логируется или для него не установлена коллекция, атака на него в отчёте не появится (`cscli metrics` -> секция acquisition показывает, какие источники реально читаются).
- **Истёкшие решения удаляются из БД.** Для прошедшей даты раздел 7 может быть пуст, хотя блокировки были: признак «решение выдавалось» — поле `remediation` у алерта (колонка «Блок.» в разделе 4).
- **Успешность атаки не оценивается.** CrowdSec фиксирует попытку, а не факт компрометации. Критичные срабатывания из раздела 6 нужно проверять по логам самого приложения.
- **Алерты из CAPI/blocklists** (репутационные списки) — это не атаки на вашу машину, а решения, полученные из сообщества; в разделе 7 они видны по `origin` = `CAPI`/`lists`.
- Геоданные и AS появляются только при установленной коллекции обогащения (`crowdsecurity/geoip-enrich`).
MDEOF
w ""
if [ "$HOST_CHECK" -eq 1 ]; then
  w "### Чем выполнен триаж хоста и чего он не может"
  w ""
  cat >>"$REPORT" <<'MDEOF'
Проверки сделаны штатными средствами Ubuntu 24.04, без установки чего-либо: `journalctl` (события `auth`/`authpriv` из systemd-journald -- в 24.04 это основной, а часто и единственный источник событий аутентификации), `last`/`lastb` (wtmp/btmp), `dpkg --verify` и `dpkg -S` (целостность и принадлежность файлов пакетам), `systemctl` (юниты и таймеры), `find` по времени изменения, `ps` и `/proc` (процессы), `ss` (сокеты), `getcap`, `lsattr`, `/proc/sys/kernel/tainted` и `lsmod` (ядро и модули), `aa-status`, `ufw`/`nft`, `auditctl`, `apt-check`/`pro security-status`. Отсутствующие в системе инструменты перечислены в разделе 13 -- соответствующие проверки не выполнялись.

Ограничения, которые важно понимать перед тем, как делать выводы:

- **Процессы, соединения и содержимое /tmp относятся к моменту запуска скрипта, а не к аудируемой дате.** Штатными средствами Linux состояние процессов и сокетов за прошедшие сутки не восстанавливается: без auditd или EDR этих данных просто нет.
- **Отсутствие находок не доказывает отсутствие компрометации.** Злоумышленник с правами root может подчистить журналы (`journalctl --rotate --vacuum-time`), подменить `last`/`ps`/`ss`, обнулить btmp. Совпадение контрольных сумм dpkg тоже не гарантия: суммы записаны локально и при наличии root могут быть переписаны.
- **Триаж выполняется на живой системе, которой нельзя доверять.** Если находки уровня КРИТ подтверждаются, дальше корректно работать не с этой машиной, а со снятым образом диска и внешним анализом; перезагрузка или «чистка» уничтожат следы.
- **Многие признаки имеют законное объяснение.** Юниты вне пакетов, модули ядра DKMS, изменённые конфигурационные файлы, процессы с удалённым исполняемым файлом после обновления -- всё это встречается на здоровых системах. Признак -- повод спросить «кто и зачем», а не вывод.
- **Проверяется только текущий корневой раздел** (`find -xdev`): содержимое контейнеров, отдельных точек монтирования и сетевых ФС не сканируется.
MDEOF
  w ""
fi
w "### Если даты нет в базе (retention) — повторный прогон логов"
w ""
cat >>"$REPORT" <<'MDEOF'
Движок умеет читать старые логи «машиной времени»: таймстемпы берутся из самих строк. Чтобы не трогать боевую базу и никого не забанить, прогон делается с отдельным конфигом и своей БД (без `-no-api`):

```bash
DAY=YYYY-MM-DD
zcat -f /var/log/nginx/access.log* | grep "\[$(date -d "$DAY 12:00" '+%d/%b/%Y'):" > "/tmp/$DAY-nginx.log"
zcat -f /var/log/auth.log*         | grep "^$(date -d "$DAY 12:00" '+%b %e')"      > "/tmp/$DAY-auth.log"

sudo crowdsec -c /etc/crowdsec/user.yaml -dsn "file:///tmp/$DAY-nginx.log" -type nginx
sudo crowdsec -c /etc/crowdsec/user.yaml -dsn "file:///tmp/$DAY-auth.log"  -type syslog
```

Проверить, что строки вообще разбираются: `cscli explain --file /tmp/$DAY-nginx.log --type nginx --verbose`.
MDEOF
w ""
w "### Выполненные команды"
w ""
w '```bash'
if [ "${#CMDLOG[@]}" -gt 0 ]; then printf '%s\n' "${CMDLOG[@]}" >>"$REPORT"; fi
w '```'
w ""
w "### Сырые данные"
w ""
w "Каталог \`raw/\` рядом с этим отчётом:"
w ""
w '```'
( cd "$OUT" && ls -la raw/ 2>/dev/null | sed '1d' ) >>"$REPORT" || true
w '```'
w ""
if [ "$HOST_CHECK" -eq 1 ]; then
  w "> **Каталог \`raw/\` содержит чувствительные данные.** Там лежат журнал аутентификации за сутки, дамп cron, список процессов с аргументами и конфигурация служб. Пароли и токены в дампах cron и ps замаскированы, но полагаться на это как на полную очистку нельзя: перед передачей отчёта третьим лицам просмотрите содержимое. Файлы созданы с правами 0600 в каталоге 0700."
  w ""
  w "Находки триажа в машиночитаемом виде — \`raw/host/findings.tsv\` (важность, категория, описание, команда проверки)."
  w ""
fi
w "Главный машиночитаемый артефакт — \`raw/facts.json\`: в нём лежат **все** агрегаты целиком, без обрезки по \`--top\`."
w ""
if [ "${#WARNINGS[@]}" -gt 0 ]; then
  w "### Предупреждения при сборе"
  w ""
  for wmsg in "${WARNINGS[@]}"; do w "- $wmsg"; done
  w ""
fi
w "---"
w ""
w "_Сформировано \`$PROG $VERSION\` $(date '+%Y-%m-%d %H:%M:%S %Z'). Скрипт работает только на чтение: он не создаёт и не снимает блокировки, не меняет конфигурацию и не перезапускает сервисы._"

#==============================================================================
#  Итог
#==============================================================================
log "готово"
printf '%s\n' "──────────────────────────────────────────────────────────────"
printf 'Отчёт:      %s\n' "$REPORT"
printf 'Сырые данные: %s\n' "$RAW"
printf 'CrowdSec за %s (%s): алертов %s | источников %s | критичных %s | решений %s | без блокировки %s\n' \
       "$DAY" "$TZNAME" "$TOT_ALERTS" "$TOT_SRC" "$TOT_CRIT" "$TOT_DEC" "$TOT_UNBAN"
if [ "$HOST_CHECK" -eq 1 ]; then
  printf 'Триаж хоста: КРИТ %s | ВЫС %s | СРЕД %s | справочно %s\n' \
         "${HOST_CRIT:-0}" "${HOST_HIGH:-0}" "${HOST_MED:-0}" "${HOST_INFO:-0}"
  if [ "${HOST_CRIT:-0}" -gt 0 ]; then
    printf '%s\n' "ВНИМАНИЕ: есть признаки уровня КРИТ -- см. раздел 13 отчёта до любых действий с машиной."
  fi
fi
if [ "$RETENTION_ALARM" -eq 1 ]; then
  printf '%s\n' "ВНИМАНИЕ: данных за эту дату в БД нет (retention). См. раздел «Методика» отчёта."
fi
printf '%s\n' "──────────────────────────────────────────────────────────────"

if [ "$FAIL_ON_CRIT" -eq 1 ] && { [ "${TOT_CRIT:-0}" -gt 0 ] || [ "${HOST_CRIT:-0}" -gt 0 ]; }; then exit 10; fi
exit 0
