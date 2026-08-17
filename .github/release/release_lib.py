"""Release planning primitives for the HeLx monorepo.

This module intentionally uses only the Python standard library. Chart.yaml is
read with a small, strict parser limited to the top-level metadata and umbrella
`dependencies` fields used by the release manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path
from typing import Any

MANIFEST_BEGIN = "-----BEGIN HELX RELEASE MANIFEST-----"
MANIFEST_END = "-----END HELX RELEASE MANIFEST-----"
SEMVER_RE = re.compile(
    r"^(?:v)?(0|[1-9][0-9]*)"
    r"(?:\.(0|[1-9][0-9]*))?"
    r"(?:\.(0|[1-9][0-9]*))?"
    r"(?:-([0-9A-Za-z.-]+))?"
    r"(?:\+[0-9A-Za-z.-]+)?$"
)


class ReleaseError(RuntimeError):
    """A release invariant was violated."""


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[tuple[int, Any], ...] = ()

    @classmethod
    def parse(cls, value: str) -> SemVer:
        text = str(value).strip()
        match = SEMVER_RE.fullmatch(text)
        if not match:
            raise ReleaseError(
                f"Version {value!r} is not numeric semver (accepted examples: 1, 0.8, 1.2.3)"
            )
        major, minor, patch, prerelease = match.groups()
        parsed_prerelease: list[tuple[int, Any]] = []
        if prerelease:
            for identifier in prerelease.split("."):
                if identifier.isdigit():
                    parsed_prerelease.append((0, int(identifier)))
                else:
                    parsed_prerelease.append((1, identifier))
        return cls(int(major), int(minor or 0), int(patch or 0), tuple(parsed_prerelease))

    def core(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def _compare(self, other: SemVer) -> int:
        if self.core() != other.core():
            return (self.core() > other.core()) - (self.core() < other.core())
        if not self.prerelease and not other.prerelease:
            return 0
        if not self.prerelease:
            return 1
        if not other.prerelease:
            return -1
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if left[0] != right[0]:
                return -1 if left[0] == 0 else 1
            return (left[1] > right[1]) - (left[1] < right[1])
        return (len(self.prerelease) > len(other.prerelease)) - (
            len(self.prerelease) < len(other.prerelease)
        )

    def __lt__(self, other: SemVer) -> bool:
        return self._compare(other) < 0

    def __le__(self, other: SemVer) -> bool:
        return self._compare(other) <= 0

    def __gt__(self, other: SemVer) -> bool:
        return self._compare(other) > 0

    def __ge__(self, other: SemVer) -> bool:
        return self._compare(other) >= 0


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        text=True,
        capture_output=True,
    )


def git_output(*args: str) -> str:
    return git(*args).stdout.strip()


def unquote_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_chart(path: Path, dependency: str | None = None) -> dict[str, str | None]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ReleaseError(f"Configured chart does not exist: {path}") from exc

    if dependency:
        in_dependencies = False
        current_name: str | None = None
        for line in lines:
            if re.fullmatch(r"dependencies:\s*", line):
                in_dependencies = True
                continue
            if in_dependencies and line and not line[0].isspace():
                break
            name_match = re.match(r"^\s{2}-\s+name:\s*(.+?)\s*$", line)
            if name_match:
                current_name = unquote_yaml_scalar(name_match.group(1))
                continue
            version_match = re.match(r"^\s{4}version:\s*(.+?)\s*$", line)
            if current_name == dependency and version_match:
                version = unquote_yaml_scalar(version_match.group(1))
                return {
                    "name": dependency,
                    "type": "dependency",
                    "chart_version": version,
                    "app_version": None,
                }
        raise ReleaseError(f"Dependency {dependency!r} was not found in {path}")

    values: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^(name|type|version|appVersion):\s*(.+?)\s*$", line)
        if match:
            values[match.group(1)] = unquote_yaml_scalar(match.group(2))
    for required in ("name", "version"):
        if not values.get(required):
            raise ReleaseError(f"Top-level {required!r} is missing from {path}")
    return {
        "name": values["name"],
        "type": values.get("type", "application"),
        "chart_version": values["version"],
        "app_version": values.get("appVersion"),
    }


def load_config(root: Path, config_path: Path) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    required = ("marker", "registry", "initial_version", "components")
    for key in required:
        if key not in config:
            raise ReleaseError(f"Release configuration is missing {key!r}")
    SemVer.parse(config["initial_version"])
    names: set[str] = set()
    image_names: set[str] = set()
    for component in config["components"]:
        name = component.get("name")
        if not name or name in names:
            raise ReleaseError(f"Component names must be non-empty and unique: {name!r}")
        names.add(name)
        chart_path = root / component["chart"]
        chart = read_chart(chart_path, component.get("dependency"))
        if chart["name"] != name:
            raise ReleaseError(
                f"Configured component {name!r} resolves to chart name {chart['name']!r} in {chart_path}"
            )
        for image in component.get("images", []):
            image_name = image.get("name")
            if not image_name or image_name in image_names:
                raise ReleaseError(f"Image names must be non-empty and unique: {image_name!r}")
            image_names.add(image_name)
            for field in ("app_name", "repository", "context", "dockerfile"):
                if not image.get(field):
                    raise ReleaseError(f"Image {image_name!r} is missing {field!r}")
            if not (root / image["dockerfile"]).is_file():
                raise ReleaseError(f"Image {image_name!r} Dockerfile does not exist: {image['dockerfile']}")
    return config


def path_is_within(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/")
    if normalized.endswith("-"):
        return path.startswith(normalized)
    return path == normalized or path.startswith(normalized + "/")


def any_path_matches(paths: Iterable[str], includes: Iterable[str], excludes: Iterable[str] = ()) -> bool:
    excluded = tuple(excludes)
    for path in paths:
        if any(path_is_within(path, item) for item in includes) and not any(
            path_is_within(path, item) for item in excluded
        ):
            return True
    return False


def changed_paths(base: str | None, head: str) -> list[str]:
    if base is None:
        return git_output("ls-tree", "-r", "--name-only", head).splitlines()
    result = git("diff", "--name-only", base, head)
    return [line for line in result.stdout.splitlines() if line]


def manifest_json(manifest: dict[str, Any], *, compact: bool = False) -> str:
    if compact:
        return json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return json.dumps(manifest, sort_keys=True, indent=2) + "\n"


def manifest_message(marker: str, manifest: dict[str, Any]) -> str:
    payload = manifest_json(manifest)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    tag = manifest.get("release", {}).get("tag", "unknown")
    return (
        f"{marker}\n"
        f"HeLx monorepo release {tag}\n"
        f"compatibility-manifest-sha256: {digest}\n\n"
        f"{MANIFEST_BEGIN}\n{payload}{MANIFEST_END}\n"
    )


def extract_manifest(message: str, marker: str) -> dict[str, Any]:
    if marker not in message.splitlines():
        raise ReleaseError("Annotated tag does not contain the configured release marker")
    try:
        payload = message.split(MANIFEST_BEGIN, 1)[1].split(MANIFEST_END, 1)[0].strip() + "\n"
    except IndexError as exc:
        raise ReleaseError("Marked tag does not contain an embedded compatibility manifest") from exc
    manifest = json.loads(payload)
    checksum_match = re.search(r"^compatibility-manifest-sha256:\s*([0-9a-f]{64})$", message, re.MULTILINE)
    if checksum_match:
        actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if actual != checksum_match.group(1):
            raise ReleaseError("Embedded compatibility manifest checksum does not match")
    return manifest


def marked_releases(marker: str, head: str | None = None) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    refs = git_output("for-each-ref", "--format=%(refname:short)%09%(objecttype)", "refs/tags")
    for line in refs.splitlines():
        if not line:
            continue
        tag, object_type = line.split("\t", 1)
        if not tag.startswith("v"):
            continue
        try:
            version = SemVer.parse(tag)
        except ReleaseError as exc:
            raise ReleaseError(
                f"Git tag {tag!r} uses the reserved v* namespace but is not semantic"
            ) from exc
        if object_type != "tag":
            raise ReleaseError(
                f"Git tag {tag} uses the reserved monorepo release namespace but is not annotated"
            )
        message = git_output("for-each-ref", "--format=%(contents)", f"refs/tags/{tag}")
        if marker not in message.splitlines():
            raise ReleaseError(
                f"Git tag {tag} uses the reserved monorepo release namespace but lacks marker {marker!r}"
            )
        manifest = extract_manifest(message, marker)
        manifest_tag = manifest.get("release", {}).get("tag")
        if manifest_tag != tag:
            raise ReleaseError(f"Marked tag {tag} embeds a manifest for {manifest_tag!r}")
        commit = git_output("rev-list", "-n", "1", tag)
        if head is not None and git(
            "merge-base", "--is-ancestor", commit, head, check=False
        ).returncode != 0:
            continue
        releases.append(
            {
                "tag": tag,
                "version": version,
                "commit": commit,
                "manifest": manifest,
            }
        )
    releases.sort(
        key=cmp_to_key(lambda left, right: left["version"]._compare(right["version"]))
    )
    return releases


def compare_versions(current: str, previous: str, label: str) -> int:
    current_version = SemVer.parse(current)
    previous_version = SemVer.parse(previous)
    comparison = current_version._compare(previous_version)
    if comparison == 0 and current != previous:
        raise ReleaseError(
            f"{label} changed spelling from {previous!r} to {current!r} without a semantic increase"
        )
    if comparison < 0:
        raise ReleaseError(f"{label} regressed from {previous!r} to {current!r}")
    return comparison


def delta_level(current: str, previous: str) -> int:
    current_version = SemVer.parse(current)
    previous_version = SemVer.parse(previous)
    if current_version._compare(previous_version) == 0:
        return 0
    if current_version.major != previous_version.major:
        return 3
    if current_version.minor != previous_version.minor:
        return 2
    return 1


def bump_version(previous: SemVer, level: int) -> SemVer:
    if level >= 3:
        return SemVer(previous.major + 1, 0, 0)
    if level == 2:
        return SemVer(previous.major, previous.minor + 1, 0)
    return SemVer(previous.major, previous.minor, previous.patch + 1)


def ref_exists(tag: str) -> bool:
    return git("show-ref", "--verify", "--quiet", f"refs/tags/{tag}", check=False).returncode == 0


def current_components(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for definition in config["components"]:
        chart = read_chart(root / definition["chart"], definition.get("dependency"))
        chart_version = str(chart["chart_version"])
        app_version = str(chart["app_version"]) if chart["app_version"] is not None else None
        SemVer.parse(chart_version)
        if app_version is not None:
            SemVer.parse(app_version)
        if definition.get("images") and app_version is None:
            raise ReleaseError(f"Image component {definition['name']!r} must define appVersion")
        components.append(
            {
                "name": definition["name"],
                "type": chart["type"],
                "chart_source": (
                    f"{definition['chart']}#dependencies.{definition['dependency']}"
                    if definition.get("dependency")
                    else definition["chart"]
                ),
                "chart_version": chart_version,
                "app_version": app_version,
                "component_version": app_version or chart_version,
                "definition": definition,
            }
        )
    return components


def image_matrix_entry(
    registry: str,
    component: dict[str, Any],
    image: dict[str, Any],
    staging_tag: str,
) -> dict[str, Any]:
    repository = f"{registry}/{image['repository']}"
    release_tag = f"v{component['app_version']}"
    return {
        "name": image["name"],
        "component": component["name"],
        "app_name": image["app_name"],
        "image_name": image["repository"],
        "context": image["context"],
        "dockerfile": image["dockerfile"],
        "staging_tag": staging_tag,
        "staging_ref": f"{repository}:{staging_tag}",
        "release_tag": release_tag,
        "release_ref": f"{repository}:{release_tag}",
    }


def plan_hash(plan: dict[str, Any]) -> str:
    decision = {
        "mode": plan["mode"],
        "head": plan["head"],
        "release": plan.get("release"),
        "build_images": plan.get("build_images", []),
        "components": [
            {
                "name": component["name"],
                "chart_version": component["chart_version"],
                "app_version": component["app_version"],
                "changes": component.get("changes"),
            }
            for component in plan.get("components", [])
        ],
    }
    return hashlib.sha256(manifest_json(decision, compact=True).encode("utf-8")).hexdigest()


def plan_develop(root: Path, config: dict[str, Any], head: str, base: str | None) -> dict[str, Any]:
    paths = changed_paths(base, head)
    rebuild_all = base is None or any_path_matches(paths, config.get("rebuild_all_paths", []))
    staging_tag = f"develop_{head}"
    builds: list[dict[str, Any]] = []
    components = current_components(root, config)
    for component in components:
        definition = component.pop("definition")
        source_changed = rebuild_all or any_path_matches(
            paths,
            definition.get("image_sources", []),
            definition.get("image_excludes", []),
        )
        component["changes"] = {"chart": False, "image_source": source_changed, "version": False}
        component["images"] = []
        if source_changed:
            for image in definition.get("images", []):
                entry = image_matrix_entry(config["registry"], component, image, staging_tag)
                entry.pop("release_tag")
                entry.pop("release_ref")
                builds.append(entry)
    plan = {
        "schema_version": 1,
        "marker": config["marker"],
        "mode": "develop",
        "head": head,
        "base": base,
        "changed_paths": paths,
        "components": components,
        "build_images": builds,
        "already_released": False,
    }
    plan["plan_hash"] = plan_hash(plan)
    return plan


@dataclass(frozen=True)
class ComponentVersionDelta:
    chart_comparison: int
    app_comparison: int
    level: int


@dataclass(frozen=True)
class ImageReleaseDecision:
    build: bool
    promote: bool


def select_release_baseline(
    marker: str, head: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return a release at HEAD, or the latest marked ancestor as the baseline."""
    # Passing HEAD is essential: marked tags on divergent branches are not
    # compatibility baselines for this release line.
    releases = marked_releases(marker, head)
    releases_at_head = [release for release in releases if release["commit"] == head]
    return (releases_at_head[-1] if releases_at_head else None, releases[-1] if releases else None)


def already_released_plan(
    marker: str, head: str, existing: dict[str, Any]
) -> dict[str, Any]:
    plan = {
        "schema_version": 1,
        "marker": marker,
        "mode": "release",
        "head": head,
        "base": existing["commit"],
        "release": existing["manifest"]["release"],
        "components": existing["manifest"]["components"],
        "build_images": [],
        "already_released": True,
        "existing_manifest": existing["manifest"],
    }
    plan["plan_hash"] = plan_hash(plan)
    return plan


def previous_release_state(
    previous: dict[str, Any] | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    components = {
        component["name"]: component
        for component in (previous["manifest"].get("components", []) if previous else [])
    }
    images = {
        image["name"]: image
        for component in components.values()
        for image in component.get("images", [])
    }
    return components, images


def version_delta(current: str, previous: str | None, label: str) -> tuple[int, int]:
    baseline = previous or "0.0.0"
    comparison = (
        compare_versions(current, previous, label)
        if previous is not None
        else SemVer.parse(current)._compare(SemVer(0, 0, 0))
    )
    return comparison, delta_level(current, baseline)


def component_version_delta(
    current: dict[str, Any], prior: dict[str, Any] | None
) -> ComponentVersionDelta:
    prior_chart = prior.get("chart_version") if prior else None
    chart_comparison, chart_level = version_delta(
        current["chart_version"], prior_chart, f"{current['name']} chartVersion"
    )

    app_comparison = 0
    app_level = 0
    if current["app_version"] is not None:
        prior_app = prior.get("app_version") if prior else None
        app_comparison, app_level = version_delta(
            current["app_version"], prior_app, f"{current['name']} appVersion"
        )
    return ComponentVersionDelta(chart_comparison, app_comparison, max(chart_level, app_level))


def component_change_flags(
    paths: Iterable[str],
    definition: dict[str, Any],
    version: ComponentVersionDelta,
    *,
    bootstrap: bool,
    shared_rebuild: bool,
) -> dict[str, bool]:
    if bootstrap:
        chart_changed = True
        source_changed = bool(definition.get("images"))
    else:
        if definition.get("chart_change_mode") == "version":
            chart_changed = version.chart_comparison != 0
        else:
            chart_directory = str(Path(definition["chart"]).parent)
            chart_changed = any_path_matches(paths, [chart_directory])
        source_changed = any_path_matches(
            paths,
            definition.get("image_sources", []),
            definition.get("image_excludes", []),
        )
    return {
        "chart": chart_changed,
        "image_source": source_changed,
        "shared_rebuild": shared_rebuild,
        "version": version.chart_comparison != 0 or version.app_comparison != 0,
    }


def validate_component_change_versions(
    current: dict[str, Any],
    prior: dict[str, Any] | None,
    changes: dict[str, bool],
    version: ComponentVersionDelta,
    *,
    bootstrap: bool,
) -> None:
    if bootstrap:
        return
    if changes["chart"] and version.chart_comparison <= 0:
        prior_chart = prior.get("chart_version") if prior else None
        raise ReleaseError(
            f"{current['name']} chart changed but chart version did not increase above {prior_chart}"
        )
    if changes["image_source"] and version.app_comparison <= 0:
        prior_app = prior.get("app_version") if prior else None
        raise ReleaseError(
            f"{current['name']} image source changed but appVersion did not increase above {prior_app}"
        )


def removed_component_names(
    previous_components: dict[str, dict[str, Any]], current_components: Iterable[dict[str, Any]]
) -> list[str]:
    current_names = {component["name"] for component in current_components}
    return sorted(set(previous_components) - current_names)


def removed_image_names(
    component_name: str,
    prior: dict[str, Any] | None,
    configured_images: Iterable[dict[str, Any]],
) -> list[str]:
    if not prior:
        return []
    prior_names = {image["name"] for image in prior.get("images", [])}
    configured_names = {image["name"] for image in configured_images}
    return [f"{component_name}/{name}" for name in sorted(prior_names - configured_names)]


def removal_delta(removed_components: Iterable[str], removed_images: Iterable[str]) -> int:
    """Removing a component or image is a monorepo-breaking change."""
    return 3 if any(removed_components) or any(removed_images) else 0


def image_release_decision(
    *,
    bootstrap: bool,
    source_changed: bool,
    app_comparison: int,
    component_is_new: bool,
    shared_rebuild: bool,
) -> ImageReleaseDecision:
    promote = bootstrap or source_changed or app_comparison > 0 or component_is_new
    return ImageReleaseDecision(build=promote or shared_rebuild, promote=promote)


def promoted_image_record(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": entry["name"],
        "release_tag": entry["release_tag"],
        "release_ref": entry["release_ref"],
        "staging_ref": entry["staging_ref"],
        "digest": None,
        "immutable_ref": None,
    }


def carried_forward_image_record(
    entry: dict[str, Any], prior_image: dict[str, Any] | None, *, rebuilt: bool
) -> dict[str, Any]:
    if not prior_image or not prior_image.get("digest"):
        raise ReleaseError(f"Previous manifest has no digest for unchanged image {entry['name']!r}")
    expected_ref = entry["release_ref"]
    if prior_image.get("release_ref") != expected_ref:
        raise ReleaseError(
            f"Unchanged image {entry['name']!r} expected {expected_ref}, previous manifest has "
            f"{prior_image.get('release_ref')!r}"
        )
    return {
        "name": entry["name"],
        "release_tag": entry["release_tag"],
        "release_ref": expected_ref,
        "staging_ref": entry["staging_ref"] if rebuilt else None,
        "digest": prior_image["digest"],
        "immutable_ref": prior_image.get("immutable_ref")
        or f"{expected_ref.rsplit(':', 1)[0]}@{prior_image['digest']}",
    }


def plan_release_component(
    current: dict[str, Any],
    prior: dict[str, Any] | None,
    previous_images: dict[str, dict[str, Any]],
    paths: Iterable[str],
    registry: str,
    staging_tag: str,
    *,
    bootstrap: bool,
    shared_rebuild: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], int, list[str]]:
    component = dict(current)
    definition = component.pop("definition")
    version = component_version_delta(component, prior)
    changes = component_change_flags(
        paths,
        definition,
        version,
        bootstrap=bootstrap,
        shared_rebuild=shared_rebuild,
    )
    validate_component_change_versions(
        component, prior, changes, version, bootstrap=bootstrap
    )
    component["changes"] = changes
    component["images"] = []

    configured_images = definition.get("images", [])
    removed_images = removed_image_names(component["name"], prior, configured_images)
    decision = image_release_decision(
        bootstrap=bootstrap,
        source_changed=changes["image_source"],
        app_comparison=version.app_comparison,
        component_is_new=prior is None,
        shared_rebuild=shared_rebuild,
    )
    builds: list[dict[str, Any]] = []
    for image in configured_images:
        entry = image_matrix_entry(registry, component, image, staging_tag)
        entry["promote"] = decision.promote
        if decision.build:
            builds.append(entry)
        image_record = (
            promoted_image_record(entry)
            if decision.promote
            else carried_forward_image_record(
                entry, previous_images.get(image["name"]), rebuilt=decision.build
            )
        )
        component["images"].append(image_record)

    level = max(version.level, removal_delta([], removed_images))
    return component, builds, level, removed_images


def monorepo_bump(highest_component_delta: int) -> tuple[int, str]:
    level = highest_component_delta or 1
    return level, {1: "patch", 2: "minor", 3: "major"}[level]


def select_release_version(
    initial_version: str,
    previous: dict[str, Any] | None,
    bump_level: int,
) -> tuple[SemVer, str]:
    if previous is None:
        version = SemVer.parse(initial_version)
        tag = f"v{version}"
        if ref_exists(tag):
            raise ReleaseError(
                f"Bootstrap tag {tag} already exists. The v* Git tag namespace is reserved for "
                "CI-created monorepo releases; investigate the existing tag before continuing."
            )
        return version, tag

    version = bump_version(previous["version"], bump_level)
    tag = f"v{version}"
    if ref_exists(tag):
        raise ReleaseError(
            f"Next monorepo release tag {tag} already exists. The v* Git tag namespace is "
            "reserved for CI-created monorepo releases; investigate rather than skipping it."
        )
    return version, tag


def plan_release(root: Path, config: dict[str, Any], head: str) -> dict[str, Any]:
    existing, previous = select_release_baseline(config["marker"], head)
    if existing:
        return already_released_plan(config["marker"], head, existing)

    bootstrap = previous is None
    base = previous["commit"] if previous else None
    paths = changed_paths(base, head)
    shared_rebuild = not bootstrap and any_path_matches(paths, config.get("rebuild_all_paths", []))
    previous_components, previous_images = previous_release_state(previous)
    current_component_list = current_components(root, config)
    removed_components = removed_component_names(previous_components, current_component_list)

    builds: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    removed_images: list[str] = []
    highest_delta = removal_delta(removed_components, [])
    for current in current_component_list:
        component, component_builds, component_delta, component_removed_images = (
            plan_release_component(
                current,
                previous_components.get(current["name"]),
                previous_images,
                paths,
                config["registry"],
                f"staging_{head}",
                bootstrap=bootstrap,
                shared_rebuild=shared_rebuild,
            )
        )
        components.append(component)
        builds.extend(component_builds)
        removed_images.extend(component_removed_images)
        highest_delta = max(highest_delta, component_delta)

    bump_level, bump_name = monorepo_bump(highest_delta)
    release_version, release_tag = select_release_version(
        config["initial_version"], previous, bump_level
    )
    release = {
        "tag": release_tag,
        "version": str(release_version),
        "commit": head,
        "commit_timestamp": git_output("show", "-s", "--format=%cI", head),
        "previous_tag": previous["tag"] if previous else None,
        "previous_commit": previous["commit"] if previous else None,
        "bump": "bootstrap" if bootstrap else bump_name,
        "bootstrap": bootstrap,
        "removed_components": removed_components,
        "removed_images": removed_images,
    }
    plan = {
        "schema_version": 1,
        "marker": config["marker"],
        "mode": "release",
        "head": head,
        "base": base,
        "release": release,
        "changed_paths": paths,
        "components": components,
        "build_images": builds,
        "already_released": False,
    }
    plan["plan_hash"] = plan_hash(plan)
    return plan


def write_github_outputs(path: Path, plan: dict[str, Any]) -> None:
    release = plan.get("release", {})
    outputs = {
        "matrix": json.dumps(plan.get("build_images", []), separators=(",", ":")),
        "has-images": str(bool(plan.get("build_images"))).lower(),
        "release-tag": release.get("tag", ""),
        "previous-tag": release.get("previous_tag") or "",
        "bootstrap": str(bool(release.get("bootstrap"))).lower(),
        "already-released": str(bool(plan.get("already_released"))).lower(),
        "plan-hash": plan["plan_hash"],
        "marker": plan.get("marker", ""),
    }
    with path.open("a", encoding="utf-8") as output:
        for key, value in outputs.items():
            output.write(f"{key}={value}\n")


def release_notes(manifest: dict[str, Any]) -> str:
    release = manifest["release"]
    lines = [
        f"# HeLx monorepo release {release['tag']}",
        "",
        f"Commit: `{release['commit']}`  ",
        f"Previous marked release: `{release.get('previous_tag') or '(bootstrap)'}`  ",
        f"Monorepo bump: `{release['bump']}`",
        "",
        "## Compatibility manifest",
        "",
        "| Component | Component version | appVersion | chartVersion | Images |",
        "| --- | --- | --- | --- | --- |",
    ]
    for component in manifest["components"]:
        images = "; ".join(
            f"`{image['release_ref']}` (`{image['digest']}`)" for image in component.get("images", [])
        ) or "—"
        lines.append(
            "| {name} | `{component_version}` | {app} | `{chart}` | {images} |".format(
                name=component["name"],
                component_version=component["component_version"],
                app=f"`{component['app_version']}`" if component.get("app_version") else "—",
                chart=component["chart_version"],
                images=images,
            )
        )
    lines.extend(
        [
            "",
            "The attached JSON is the machine-readable compatibility manifest embedded in the annotated Git tag.",
            "The repository `v*` Git tag namespace is reserved for annotated monorepo releases containing `helx-monorepo-release`.",
            "",
        ]
    )
    return "\n".join(lines)
