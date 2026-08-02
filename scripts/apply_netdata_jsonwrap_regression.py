#!/usr/bin/env python3
"""Apply the Netdata jsonwrap regression fixture, then remove this helper."""

from pathlib import Path

path = Path("scripts/test_optional_runtime.py")
text = path.read_text(encoding="utf-8")
old = '''    printf '%s\\n' '{"id":"chart://hosts:test/instance:system.cpu/dimensions:*/after:-10","name":"chart://hosts:test/instance:system.cpu","data":[[1,2.5]]}' >"$output"\n'''
new = '''    printf '%s\\n' '{"id":"chart://hosts:test/instance:system.cpu/dimensions:*/after:-10","name":"chart://hosts:test/instance:system.cpu","result":{"labels":["time","user"],"data":[[1,2.5]]}}' >"$output"\n'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one fixture match, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Netdata jsonwrap regression fixture applied")
