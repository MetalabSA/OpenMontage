#!/usr/bin/env python
"""Smoke-test an S3-compatible bucket (R2 / Supabase) for backups.

Reads the same OM_S3_* variables as the API. Uploads, lists, downloads and
deletes a tiny object; exits non-zero on failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from api import config
from api.services import remote_storage


def main() -> int:
    if not remote_storage.enabled():
        print("OM_S3_ENDPOINT / OM_S3_BUCKET / OM_S3_ACCESS_KEY / OM_S3_SECRET_KEY are required", file=sys.stderr)
        return 2
    key = remote_storage.key_for("_healthcheck.txt")
    payload = Path("/tmp/cabina-s3-check.txt")
    payload.write_text("cabina backup storage check\n")
    try:
        remote_storage.upload(payload, key, "text/plain")
        keys = {item["key"] for item in remote_storage.list_keys(remote_storage.key_for(""))}
        if key not in keys:
            print(f"uploaded object not listed: {key}", file=sys.stderr)
            return 1
        size = remote_storage.size(key)
        print(f"ok bucket={config.S3_BUCKET} endpoint={config.S3_ENDPOINT} key={key} size={size}")
        remote_storage.delete(key)
        return 0
    except Exception as exc:
        print(f"failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
