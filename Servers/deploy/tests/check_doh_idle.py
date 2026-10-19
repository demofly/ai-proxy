#!/usr/bin/env python3
"""Optional six-minute native check of real persistent TLS/HTTP2 connections.

Uses the isolated fixture from test_dns_doh; never connects to production.
"""
import importlib.util
import json
from pathlib import Path
import time

spec = importlib.util.spec_from_file_location('doh_native', Path(__file__).with_name('test_dns_doh.py'))
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
fixture = native.NativeDohTests
fixture.setUpClass()
try:
    fixture.bridge_query()
    before = fixture.transit_connections()
    assert before, 'No pooled HTTP/2 connection'
    started = time.monotonic()
    for deadline in (35, 65, 125, 185, 245, 290):
        time.sleep(max(0, deadline - (time.monotonic() - started)))
        assert fixture.transit_connections() == before, 'Connection closed before 300 idle seconds'
        print(json.dumps({'idle_seconds': deadline, 'same_connections': True}), flush=True)
    while time.monotonic() - started < 315:
        if not fixture.transit_connections():
            break
        time.sleep(.2)
    elapsed = time.monotonic() - started
    assert 298 <= elapsed <= 315 and not fixture.transit_connections(), 'Expected closure after five idle minutes'
    fixture.bridge_query()
    after = fixture.transit_connections()
    assert after and before.isdisjoint(after), 'Next request did not establish a fresh connection'
    print(json.dumps({'closed_after_seconds': round(elapsed, 1), 'fresh_connection': True}), flush=True)
finally:
    fixture.cleanup()
