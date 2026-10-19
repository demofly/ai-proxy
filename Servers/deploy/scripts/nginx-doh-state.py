#!/usr/bin/env python3
"""Fingerprint owned nginx fragments; acknowledge only after a real DoH query."""
import hashlib
import json
from pathlib import Path
import sys

digest = hashlib.sha256(b''.join(Path(path).read_bytes() for path in json.loads(sys.argv[1]))).hexdigest()
marker = Path(sys.argv[2])
print(json.dumps({'digest': digest, 'needs_apply': not marker.exists() or marker.read_text().strip() != digest}))
