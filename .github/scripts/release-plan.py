#!/usr/bin/env python3
"""Create a develop image plan or a main monorepo release plan."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LIB = runpy.run_path(str(ROOT / ".github" / "release" / "release_lib.py"))
ReleaseError = LIB["ReleaseError"]
git_output = LIB["git_output"]
load_config = LIB["load_config"]
manifest_json = LIB["manifest_json"]
plan_develop = LIB["plan_develop"]
plan_release = LIB["plan_release"]
write_github_outputs = LIB["write_github_outputs"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("develop", "release"), required=True)
    parser.add_argument("--base", help="Base commit for develop mode; all-zero means build all images")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--config", default=".github/release/components.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--github-output")
    return parser.parse_args()


def resolve_commit(revision: str) -> str:
    """Resolve a user/workflow revision to one full commit SHA."""
    return git_output("rev-parse", revision)


def resolve_develop_base(base: str | None) -> str | None:
    """Normalize GitHub's all-zero initial-push SHA to 'no baseline'."""
    if not base or set(base) == {"0"}:
        return None
    return resolve_commit(base)


def create_plan(args: argparse.Namespace) -> dict[str, Any]:
    """Load configuration and delegate to the selected planning policy."""
    config = load_config(ROOT, ROOT / args.config)
    head = resolve_commit(args.head)
    if args.mode == "develop":
        return plan_develop(ROOT, config, head, resolve_develop_base(args.base))
    return plan_release(ROOT, config, head)


def write_plan(plan: dict[str, Any], output: str, github_output: str | None) -> None:
    """Persist the full plan and the small output set consumed by GitHub Actions."""
    output_path = ROOT / output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(manifest_json(plan), encoding="utf-8")
    if github_output:
        write_github_outputs(Path(github_output), plan)


def plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    """Return the human-readable decision summary printed in workflow logs."""
    release = plan.get("release", {})
    return {
        "mode": plan["mode"],
        "head": plan["head"],
        "release_tag": release.get("tag"),
        "previous_tag": release.get("previous_tag"),
        "already_released": plan["already_released"],
        "images": [image["name"] for image in plan["build_images"]],
        "plan_hash": plan["plan_hash"],
    }


def main() -> int:
    args = parse_args()
    try:
        plan = create_plan(args)
        write_plan(plan, args.output, args.github_output)
        print(json.dumps(plan_summary(plan), indent=2))
        return 0
    except (ReleaseError, OSError, json.JSONDecodeError) as exc:
        print(f"release planning failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
