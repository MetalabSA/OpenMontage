"""S3-compatible remote backup storage (Cloudflare R2 / Supabase Storage)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from api import config


def enabled() -> bool:
    return bool(
        config.S3_ENDPOINT
        and config.S3_BUCKET
        and config.S3_ACCESS_KEY
        and config.S3_SECRET_KEY
    )


def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT,
        region_name=config.S3_REGION or "auto",
        aws_access_key_id=config.S3_ACCESS_KEY,
        aws_secret_access_key=config.S3_SECRET_KEY,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if config.S3_FORCE_PATH_STYLE else "virtual"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def key_for(name: str) -> str:
    prefix = (config.S3_PREFIX or "cabina/backups").strip("/")
    return f"{prefix}/{name}" if prefix else name


def upload(path: Path, key: str, content_type: str = "application/gzip") -> None:
    _client().upload_file(
        str(path),
        config.S3_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )


def download(key: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _client().download_file(config.S3_BUCKET, key, str(destination))


def get_json(key: str) -> dict[str, Any] | None:
    try:
        body = _client().get_object(Bucket=config.S3_BUCKET, Key=key)["Body"].read()
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def delete(key: str) -> None:
    _client().delete_object(Bucket=config.S3_BUCKET, Key=key)


def list_keys(prefix: str | None = None) -> list[dict[str, Any]]:
    base = key_for("") if prefix is None else prefix
    paginator = _client().get_paginator("list_objects_v2")
    items: list[dict[str, Any]] = []
    for page in paginator.paginate(Bucket=config.S3_BUCKET, Prefix=base):
        for item in page.get("Contents", []):
            items.append(
                {
                    "key": item["Key"],
                    "size": int(item.get("Size") or 0),
                    "last_modified": item["LastModified"].isoformat() if item.get("LastModified") else None,
                }
            )
    return items


def stream(key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    body = _client().get_object(Bucket=config.S3_BUCKET, Key=key)["Body"]
    while True:
        chunk = body.read(chunk_size)
        if not chunk:
            break
        yield chunk


def size(key: str) -> int | None:
    try:
        return int(_client().head_object(Bucket=config.S3_BUCKET, Key=key)["ContentLength"])
    except Exception:
        return None
