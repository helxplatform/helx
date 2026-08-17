#!/usr/bin/env python3
"""Print the latest marked monorepo release commit that is an ancestor of HEAD."""

from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = runpy.run_path(str(ROOT / ".github" / "release" / "release_lib.py"))
ReleaseError = LIB["ReleaseError"]
git_output = LIB["git_output"]
select_release_baseline = LIB["select_release_baseline"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--config", default=".github/release/components.json")
    return parser.parse_args()


def baseline_commit(config_path: Path, head_revision: str) -> str | None:
    """Return the prior/current marked release commit for one release line."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    head = git_output("rev-parse", head_revision)
    _, previous = select_release_baseline(config["marker"], head)
    return previous["commit"] if previous else None


def main() -> int:
    args = parse_args()
    try:
        commit = baseline_commit(ROOT / args.config, args.head)
        if commit:
            print(commit)
        return 0
    except (ReleaseError, OSError, json.JSONDecodeError) as exc:
        print(f"release baseline lookup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
