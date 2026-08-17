#!/usr/bin/env python3
"""Read the small subset of Helm chart metadata needed by CI scripts.

The project deliberately avoids a runtime PyYAML dependency. These functions are
strict parsers for dependency names, versions, and repositories only; they are
not general-purpose YAML parsers.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


class HelmMetadataError(RuntimeError):
    """Chart dependency metadata is missing or inconsistent."""


@dataclass(frozen=True)
class Dependency:
    name: str
    version: str
    repository: str

    def as_tsv(self) -> str:
        return f"{self.name}\t{self.version}\t{self.repository}"


def unquote_scalar(value: str) -> str:
    """Read one quoted or unquoted scalar token, excluding an inline comment."""
    match = re.match(r'''^\s*(?:"([^"]*)"|'([^']*)'|([^\s#]+))''', value)
    if not match:
        return ""
    return next(group for group in match.groups() if group is not None)


def dependency_items(path: Path) -> list[dict[str, str]]:
    """Return dependency fields from the top-level dependencies YAML sequence."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise HelmMetadataError(f"Dependency metadata does not exist: {path}") from exc

    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_dependencies = False
    for line in lines:
        if re.fullmatch(r"dependencies:\s*", line):
            in_dependencies = True
            continue
        if in_dependencies and line and not line[0].isspace() and not re.match(r"^-\s", line):
            break

        name_match = re.match(r"^\s*-\s+name:\s*(.+?)\s*$", line)
        if name_match:
            if current:
                items.append(current)
            current = {"name": unquote_scalar(name_match.group(1))}
            continue

        field_match = re.match(r"^\s+(version|repository):\s*(.+?)\s*$", line)
        if current is not None and field_match:
            current[field_match.group(1)] = unquote_scalar(field_match.group(2))

    if current:
        items.append(current)
    return items


def dependencies(path: Path) -> list[Dependency]:
    """Parse complete dependency tuples and reject incomplete entries."""
    parsed: list[Dependency] = []
    for item in dependency_items(path):
        missing = [field for field in ("name", "version", "repository") if not item.get(field)]
        if missing:
            raise HelmMetadataError(
                f"Incomplete dependency in {path}: missing {', '.join(missing)} in {item!r}"
            )
        parsed.append(Dependency(item["name"], item["version"], item["repository"]))
    return parsed


def locked_dependencies(chart_path: Path, lock_path: Path) -> list[Dependency]:
    """Return the lock only when it exactly matches Chart.yaml dependency tuples."""
    chart_dependencies = dependencies(chart_path)
    lock_dependencies = dependencies(lock_path)
    if chart_dependencies != lock_dependencies:
        raise HelmMetadataError(
            "Chart.yaml dependencies do not match Chart.lock\n"
            f"Chart.yaml: {chart_dependencies}\n"
            f"Chart.lock: {lock_dependencies}"
        )
    return lock_dependencies


def resolve_file_repository(chart_dir: Path, repository: str) -> Path:
    """Resolve a file:// repository relative to its declaring chart directory."""
    if not repository.startswith("file://"):
        raise HelmMetadataError(f"Not a file repository: {repository}")
    return Path(os.path.normpath(os.path.join(str(chart_dir), repository.removeprefix("file://"))))


def local_dependency_paths(chart_dir: Path) -> list[Path]:
    """Resolve all file:// dependencies declared by a chart."""
    paths: list[Path] = []
    for item in dependency_items(chart_dir / "Chart.yaml"):
        repository = item.get("repository", "")
        if repository.startswith("file://"):
            paths.append(resolve_file_repository(chart_dir, repository))
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    locked = commands.add_parser("locked-dependencies")
    locked.add_argument("chart")
    locked.add_argument("lock")

    local = commands.add_parser("local-dependencies")
    local.add_argument("chart_dir")

    resolve = commands.add_parser("resolve-file")
    resolve.add_argument("chart_dir")
    resolve.add_argument("repository")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "locked-dependencies":
            for dependency in locked_dependencies(Path(args.chart), Path(args.lock)):
                print(dependency.as_tsv())
        elif args.command == "local-dependencies":
            for path in local_dependency_paths(Path(args.chart_dir)):
                print(path)
        else:
            print(resolve_file_repository(Path(args.chart_dir), args.repository))
        return 0
    except HelmMetadataError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
