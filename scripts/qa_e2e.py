#!/usr/bin/env python
"""Drive a production project through the pipeline and verify the MP4.

Usage:
    OM_API_BASE=https://studio.metalabia.com/api \
    OM_API_TOKEN=om_... \
    python scripts/qa_e2e.py --slug modelo-real-2

Auto-approves the intermediate gates (scene_plan, assets, edit, compose) and
stops at publish unless --approve-publish is passed. Exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import requests

BASE = os.environ.get("OM_API_BASE", "https://studio.metalabia.com/api").rstrip("/")
TOKEN = os.environ.get("OM_API_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
AUTO_GATES = ("scene_plan", "assets", "edit", "compose")


def checkpoints(slug: str) -> dict:
    response = requests.get(f"{BASE}/projects/{slug}/checkpoints", headers=HEADERS, timeout=30)
    response.raise_for_status()
    return {item["stage"]: item for item in response.json()["data"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug", required=True)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--approve-publish", action="store_true")
    args = parser.parse_args()
    if not TOKEN:
        print("OM_API_TOKEN is required", file=sys.stderr)
        return 2

    deadline = time.time() + args.timeout
    approved: set[str] = set()
    while time.time() < deadline:
        stages = checkpoints(args.slug)
        for gate in AUTO_GATES:
            checkpoint = stages.get(gate)
            if checkpoint and checkpoint["status"] == "awaiting_human" and gate not in approved:
                response = requests.post(
                    f"{BASE}/projects/{args.slug}/gates/{gate}/approve",
                    headers=HEADERS,
                    json={"note": "QA E2E automatizado"},
                    timeout=60,
                )
                print(f"approve {gate}: {response.status_code}", flush=True)
                approved.add(gate)
        if args.approve_publish and stages.get("publish", {}).get("status") == "awaiting_human":
            requests.post(
                f"{BASE}/projects/{args.slug}/gates/publish/approve",
                headers=HEADERS,
                json={"note": "QA E2E automatizado"},
                timeout=60,
            )
            print("approve publish", flush=True)

        compose = stages.get("compose", {}).get("status")
        if compose == "completed":
            board = requests.get(f"{BASE}/projects/{args.slug}/board", headers=HEADERS, timeout=30).json()
            renders = board.get("renders") or []
            print(f"compose completed; renders: {[item['path'] for item in renders]}", flush=True)
            return 0 if renders else 1
        failed = [name for name, checkpoint in stages.items() if checkpoint.get("status") == "failed"]
        if failed:
            print(f"failed stages: {failed}", file=sys.stderr)
            return 1
        time.sleep(15)
    print("timeout", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
