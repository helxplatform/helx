#!/usr/bin/env python3
"""Verify staged images, promote semantic tags, and write release metadata."""

from __future__ import annotations

import argparse
import copy
import json
import re
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LIB = runpy.run_path(str(ROOT / ".github" / "release" / "release_lib.py"))
ReleaseError = LIB["ReleaseError"]
load_config = LIB["load_config"]
manifest_json = LIB["manifest_json"]
manifest_message = LIB["manifest_message"]
release_notes = LIB["release_notes"]

DIGEST_RE = re.compile(r"^Digest:\s*(sha256:[0-9a-f]{64})\s*$", re.MULTILINE)
DIGEST_VALUE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--config", default=".github/release/components.json")
    parser.add_argument("--digests", help="Directory containing build-job digest JSON files")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--tag-message", required=True)
    return parser.parse_args()


# Registry inspection and mutation

def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "buildx", "imagetools", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def inspect_digest(reference: str, *, allow_missing: bool = False) -> str | None:
    """Resolve a registry reference to one immutable digest."""
    result = docker("inspect", reference, check=False)
    if result.returncode != 0:
        if allow_missing:
            return None
        raise ReleaseError(f"Could not inspect {reference}: {result.stderr.strip()}")
    match = DIGEST_RE.search(result.stdout)
    if not match:
        raise ReleaseError(f"docker buildx did not report a digest for {reference}")
    return match.group(1)


def create_semantic_tag(staging_ref: str, staging_digest: str, release_ref: str) -> None:
    """Create a semantic tag from the exact staged digest, never from a mutable tag alone."""
    source = f"{staging_ref}@{staging_digest}"
    result = docker("create", "--tag", release_ref, source, check=False)
    if result.returncode != 0:
        raise ReleaseError(f"Could not promote {source} to {release_ref}: {result.stderr.strip()}")


def promote(staging_ref: str, release_ref: str, expected_digest: str | None = None) -> str:
    """Create or reuse a semantic tag only when it matches the staged digest."""
    staging_digest = inspect_digest(staging_ref)
    assert staging_digest is not None
    if expected_digest is not None and staging_digest != expected_digest:
        raise ReleaseError(
            f"Refusing to promote moved staging tag {staging_ref}: "
            f"expected {expected_digest}, got {staging_digest}"
        )

    existing_digest = inspect_digest(release_ref, allow_missing=True)
    if existing_digest is not None and existing_digest != staging_digest:
        raise ReleaseError(
            f"Refusing to overwrite existing semantic image tag {release_ref}: "
            f"registry has {existing_digest}, staging has {staging_digest}"
        )
    if existing_digest is None:
        create_semantic_tag(staging_ref, staging_digest, release_ref)

    promoted_digest = inspect_digest(release_ref)
    if promoted_digest != staging_digest:
        raise ReleaseError(
            f"Promotion verification failed for {release_ref}: "
            f"expected {staging_digest}, got {promoted_digest}"
        )
    return promoted_digest


# Build-job digest handoff and promotion preflight

def validate_digest_record(path: Path, record: dict[str, Any]) -> dict[str, str]:
    """Validate one digest artifact written by a matrix build job."""
    name = record.get("name")
    digest = record.get("digest")
    staging_ref = record.get("staging_ref")
    if not name or not DIGEST_VALUE_RE.fullmatch(str(digest)) or not staging_ref:
        raise ReleaseError(f"Invalid image digest record: {path}")
    return {"digest": str(digest), "staging_ref": str(staging_ref)}


def load_expected_digests(directory: Path | None) -> dict[str, dict[str, str]]:
    """Index the immutable digests handed off by successful image-build jobs."""
    if directory is None:
        return {}
    if not directory.is_dir():
        raise ReleaseError(f"Digest artifact directory does not exist: {directory}")

    expected: dict[str, dict[str, str]] = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        name = record.get("name")
        if not name:
            raise ReleaseError(f"Invalid image digest record: {path}")
        if name in expected:
            raise ReleaseError(f"Duplicate image digest record for {name!r}")
        expected[name] = validate_digest_record(path, record)
    return expected


def index_planned_builds(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {build["name"]: build for build in plan.get("build_images", [])}


def validate_digest_record_set(
    builds: dict[str, dict[str, Any]], expected: dict[str, dict[str, str]]
) -> None:
    """Require exactly one digest artifact for every planned build."""
    if builds and not expected:
        raise ReleaseError("Release has staged image builds but no build-job digest records")
    extra_names = set(expected) - set(builds)
    if extra_names:
        raise ReleaseError(f"Unexpected build digest record(s): {', '.join(sorted(extra_names))}")


def preflight_staged_build(
    build: dict[str, Any],
    record: dict[str, str] | None,
    *,
    bootstrap: bool,
) -> list[str]:
    """Bind a planned staging tag to the digest produced by its build job."""
    if record is None:
        return [f"missing digest record for {build['name']}"]
    if record["staging_ref"] != build["staging_ref"]:
        return [
            (
                f"{build['name']} digest record is for {record['staging_ref']}, "
                f"expected {build['staging_ref']}"
            )
        ]

    actual = inspect_digest(build["staging_ref"])
    if actual != record["digest"]:
        return [
            (
                f"{build['staging_ref']} moved after its build: job produced "
                f"{record['digest']}, registry now has {actual}"
            )
        ]
    build["expected_digest"] = record["digest"]

    if build.get("promote", True) and not bootstrap:
        existing = inspect_digest(build["release_ref"], allow_missing=True)
        if existing is not None and existing != record["digest"]:
            return [
                (
                    f"semantic tag {build['release_ref']} already has {existing}, "
                    f"not staged digest {record['digest']}"
                )
            ]
    return []


def preflight_carried_forward_images(
    plan: dict[str, Any], builds: dict[str, dict[str, Any]]
) -> list[str]:
    """Ensure unchanged semantic tags still match the previous release manifest."""
    errors: list[str] = []
    for component in plan.get("components", []):
        for image in component.get("images", []):
            build = builds.get(image["name"])
            if build and build.get("promote", True):
                continue
            existing = inspect_digest(image["release_ref"], allow_missing=True)
            if existing != image.get("digest"):
                errors.append(
                    f"unchanged image {image['release_ref']} no longer matches its prior manifest: "
                    f"expected {image.get('digest')}, registry has {existing or 'no tag'}"
                )
    return errors


def verify_build_digests(
    plan: dict[str, Any], expected: dict[str, dict[str, str]]
) -> None:
    """Preflight all registry state before creating any semantic image tag."""
    if plan.get("already_released"):
        return

    builds = index_planned_builds(plan)
    validate_digest_record_set(builds, expected)
    bootstrap = bool(plan.get("release", {}).get("bootstrap"))
    errors: list[str] = []
    for name, build in builds.items():
        errors.extend(preflight_staged_build(build, expected.get(name), bootstrap=bootstrap))
    errors.extend(preflight_carried_forward_images(plan, builds))

    if errors:
        raise ReleaseError("Image promotion preflight failed:\n- " + "\n- ".join(errors))


# Compatibility manifest materialization

def bootstrap_or_promoted_digest(build: dict[str, Any], *, bootstrap: bool) -> str:
    """Adopt an existing bootstrap tag, otherwise promote the staged digest."""
    if bootstrap:
        existing = inspect_digest(build["release_ref"], allow_missing=True)
        if existing is not None:
            print(f"Bootstrap preserving {build['release_ref']} at existing digest {existing}")
            return existing
    return promote(
        build["staging_ref"],
        build["release_ref"],
        build.get("expected_digest"),
    )


def verify_carried_forward_image(image: dict[str, Any]) -> None:
    """Recheck unchanged image state while materializing the final manifest."""
    existing = inspect_digest(image["release_ref"], allow_missing=True)
    if existing != image.get("digest"):
        raise ReleaseError(
            f"Unchanged image {image['release_ref']} no longer matches its prior manifest: "
            f"expected {image.get('digest')}, registry has {existing or 'no tag'}"
        )


def materialize_image(
    image: dict[str, Any],
    build: dict[str, Any] | None,
    *,
    bootstrap: bool,
) -> None:
    """Populate one manifest image with a verified immutable digest."""
    if build and build.get("promote", True):
        digest = bootstrap_or_promoted_digest(build, bootstrap=bootstrap)
        image["digest"] = digest
        image["immutable_ref"] = f"{build['release_ref'].rsplit(':', 1)[0]}@{digest}"
    else:
        verify_carried_forward_image(image)

    if not image.get("digest") or not image.get("immutable_ref"):
        raise ReleaseError(f"Image {image['name']!r} has no immutable digest in the manifest")


def materialize(plan: dict[str, Any], marker: str) -> dict[str, Any]:
    """Promote planned images and return the complete compatibility manifest."""
    if plan.get("already_released"):
        return copy.deepcopy(plan["existing_manifest"])

    builds = index_planned_builds(plan)
    bootstrap = bool(plan.get("release", {}).get("bootstrap"))
    components = copy.deepcopy(plan["components"])
    for component in components:
        for image in component.get("images", []):
            materialize_image(image, builds.get(image["name"]), bootstrap=bootstrap)

    return {
        "schema_version": 1,
        "marker": marker,
        "release": copy.deepcopy(plan["release"]),
        "components": components,
    }


# Command orchestration

def load_release_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("mode") != "release":
        raise ReleaseError("Only a release plan can be promoted")
    return plan


def write_release_files(
    manifest: dict[str, Any],
    marker: str,
    *,
    manifest_path: Path,
    notes_path: Path,
    tag_message_path: Path,
) -> None:
    manifest_path.write_text(manifest_json(manifest), encoding="utf-8")
    notes_path.write_text(release_notes(manifest), encoding="utf-8")
    tag_message_path.write_text(manifest_message(marker, manifest), encoding="utf-8")


def promote_release(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(ROOT, ROOT / args.config)
    plan = load_release_plan(ROOT / args.plan)
    expected = load_expected_digests(ROOT / args.digests if args.digests else None)

    verify_build_digests(plan, expected)
    manifest = materialize(plan, config["marker"])
    write_release_files(
        manifest,
        config["marker"],
        manifest_path=ROOT / args.manifest,
        notes_path=ROOT / args.notes,
        tag_message_path=ROOT / args.tag_message,
    )
    return manifest


def main() -> int:
    args = parse_args()
    try:
        manifest = promote_release(args)
        print(f"Materialized {manifest['release']['tag']} with {len(manifest['components'])} components")
        return 0
    except (ReleaseError, OSError, json.JSONDecodeError) as exc:
        print(f"release promotion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
