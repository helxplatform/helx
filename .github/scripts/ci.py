#!/usr/bin/env python3
"""Small, testable CI helpers for HeLx charts, images, and releases."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tarfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
IMAGES_FILE = Path(".github/ci/images.yaml")
UMBRELLA_DIR = Path("deploy/helm/helx-chart")
COMMON_DIR = Path("deploy/helm/helx-common/chart")
REGISTRY = "containers.renci.org/helxplatform"

SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
DIGEST_RE = re.compile(r"^Digest:\s*(sha256:[0-9a-f]{64})\s*$", re.MULTILINE)
REBUILD_ALL_IMAGE_PATHS = (
    ".github/actions/build-service",
    ".github/ci/images.yaml",
    ".github/scripts/ci.py",
    ".github/workflows/ci.yml",
)
REQUIRED_IMAGE_FIELDS = (
    "name",
    "component",
    "chart",
    "repository",
    "context",
    "dockerfile",
    "sources",
    "excludes",
)


class CIError(RuntimeError):
    """A user-actionable CI policy error."""


@total_ordering
@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...] = ()

    @classmethod
    def parse(cls, value: Any, label: str = "version") -> SemVer:
        """Parse a semantic version string into a comparable SemVer."""
        text = str(value).strip()
        match = SEMVER_RE.fullmatch(text)
        if not match:
            raise CIError(
                f"{label} {text!r} is not numeric semantic version x.y.z "
                "(a prerelease suffix is allowed)"
            )
        major, minor, patch, prerelease = match.groups()
        identifiers: list[int | str] = []
        for identifier in prerelease.split(".") if prerelease else ():
            if identifier.isdigit():
                if len(identifier) > 1 and identifier.startswith("0"):
                    raise CIError(f"{label} {text!r} has a zero-padded prerelease number")
                identifiers.append(int(identifier))
            else:
                identifiers.append(identifier)
        return cls(int(major), int(minor), int(patch), tuple(identifiers))

    def _key(self) -> tuple[int, int, int]:
        """Return the numeric release components used for comparison."""
        return self.major, self.minor, self.patch

    def _compare(self, other: SemVer) -> int:
        """Compare this version with another SemVer, including prerelease ordering."""
        if self._key() != other._key():
            return (self._key() > other._key()) - (self._key() < other._key())
        if not self.prerelease or not other.prerelease:
            return (not self.prerelease) - (not other.prerelease)
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if isinstance(left, int) and isinstance(right, str):
                return -1
            if isinstance(left, str) and isinstance(right, int):
                return 1
            if isinstance(left, int) and isinstance(right, int):
                return (left > right) - (left < right)
            assert isinstance(left, str) and isinstance(right, str)
            return (left > right) - (left < right)
        return (len(self.prerelease) > len(other.prerelease)) - (
            len(self.prerelease) < len(other.prerelease)
        )

    def __lt__(self, other: object) -> bool:
        """Return whether this version precedes another SemVer."""
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._compare(other) < 0

    def __eq__(self, other: object) -> bool:
        """Return whether another object represents the same semantic version."""
        return isinstance(other, SemVer) and self._compare(other) == 0


@dataclass(frozen=True)
class Dependency:
    name: str
    version: str
    repository: str

    def tsv(self) -> str:
        """Serialize the dependency as a tab-separated row."""
        return f"{self.name}\t{self.version}\t{self.repository}"


def _yaml_mapping(content: str, label: str) -> dict[str, Any]:
    """Parse YAML content and require a top-level mapping."""
    try:
        value = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise CIError(f"Could not parse YAML in {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise CIError(f"{label} must contain a top-level YAML mapping")
    return value


def read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file and return its top-level mapping."""
    try:
        return _yaml_mapping(path.read_text(encoding="utf-8"), str(path))
    except FileNotFoundError as exc:
        raise CIError(f"Required file does not exist: {path}") from exc


def metadata_value(data: dict[str, Any], field: str, label: str) -> str:
    """Return a required non-empty scalar metadata field."""
    value = data.get(field)
    if value is None or isinstance(value, (dict, list)) or str(value).strip() == "":
        raise CIError(f"{label} is missing top-level {field!r}")
    return str(value).strip()


def chart_file(chart: str | Path) -> Path:
    """Return the Chart.yaml path for a chart directory or file path."""
    path = Path(chart)
    return path if path.name == "Chart.yaml" else path / "Chart.yaml"


def dependency_list(data: dict[str, Any], label: str) -> list[Dependency]:
    """Parse and validate a chart dependency list."""
    raw = data.get("dependencies", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CIError(f"{label} top-level 'dependencies' must be a list")
    dependencies: list[Dependency] = []
    names: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise CIError(f"{label} dependency #{index} must be a mapping")
        values: list[str] = []
        for field in ("name", "version", "repository"):
            value = item.get(field)
            if value is None or isinstance(value, (dict, list)) or not str(value).strip():
                raise CIError(f"{label} dependency #{index} is missing {field!r}")
            values.append(str(value).strip())
        dependency = Dependency(*values)
        if dependency.name in names:
            raise CIError(f"{label} declares dependency {dependency.name!r} more than once")
        names.add(dependency.name)
        dependencies.append(dependency)
    return dependencies


def exact_locked_dependencies(chart_dir: Path) -> list[Dependency]:
    """Require Chart.yaml dependencies to match Chart.lock exactly."""
    chart_path = chart_dir / "Chart.yaml"
    lock_path = chart_dir / "Chart.lock"
    declared = dependency_list(read_yaml(chart_path), str(chart_path))
    if not declared:
        if lock_path.exists():
            locked = dependency_list(read_yaml(lock_path), str(lock_path))
            if locked:
                raise CIError(f"{lock_path} is stale: {chart_path} declares no dependencies")
        return []
    if not lock_path.is_file():
        raise CIError(f"{chart_path} declares dependencies but {lock_path} is missing")
    locked = dependency_list(read_yaml(lock_path), str(lock_path))
    if declared != locked:
        declared_rows = [item.tsv() for item in declared]
        locked_rows = [item.tsv() for item in locked]
        raise CIError(
            f"{chart_path} and {lock_path} dependency name/version/repository tuples differ\n"
            f"Chart.yaml: {declared_rows}\nChart.lock: {locked_rows}"
        )
    return locked


def discover_chart_dirs(root: Path) -> list[Path]:
    """Find all service, common, and umbrella chart directories."""
    service_dirs = sorted(path.parent for path in (root / "services").glob("*/chart/Chart.yaml"))
    return service_dirs + [root / COMMON_DIR, root / UMBRELLA_DIR]


def relative_path(root: Path, path: Path) -> str:
    """Return a POSIX path relative to root when possible."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _configured_path(root: Path, value: Any, label: str) -> Path:
    """Resolve a repository-relative configured path safely."""
    if not isinstance(value, str) or not value.strip():
        raise CIError(f"{label} must be a non-empty relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise CIError(f"{label} must stay within the repository: {value!r}")
    return root.joinpath(*pure.parts)


IMAGE_OVERRIDE_FIELDS = frozenset(REQUIRED_IMAGE_FIELDS)


def _simple_name(value: Any, label: str) -> str:
    """Validate and return a single-component name."""
    if not isinstance(value, str) or not value.strip():
        raise CIError(f"{label} must be a non-empty name")
    pure = PurePosixPath(value)
    if pure.is_absolute() or len(pure.parts) != 1 or pure.parts[0] in {".", ".."}:
        raise CIError(f"{label} must be a single path component: {value!r}")
    return pure.parts[0]


def _service_path(service: str, value: Any, label: str) -> str:
    """Validate a service-relative path and prefix it with services/<service>."""
    if not isinstance(value, str) or not value.strip():
        raise CIError(f"{label} must be a non-empty path relative to services/{service}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise CIError(f"{label} must stay within services/{service}: {value!r}")
    return (PurePosixPath("services") / service / pure).as_posix()


def _image_overrides(values: dict[str, Any], label: str) -> dict[str, Any]:
    """Reject unsupported fields in an image override mapping."""
    unknown = set(values) - IMAGE_OVERRIDE_FIELDS
    if unknown:
        fields = ", ".join(sorted(unknown))
        raise CIError(f"{label} contains unsupported image fields: {fields}")
    return values


def _expand_service_image(
    service: str,
    variant: str | None,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Expand one service or variant configuration into normalized image data."""
    _image_overrides(values, f"service {service!r}")
    name = service if variant is None else f"{service}-{variant}"
    repository = service if variant is None else f"{service}/{variant}"
    image: dict[str, Any] = {
        "name": values.get("name", name),
        "component": values.get("component", service),
        "chart": _service_path(service, values.get("chart", "chart"), f"{service}.chart"),
        "repository": values.get("repository", repository),
        "context": _service_path(service, values.get("context", "."), f"{service}.context"),
        "dockerfile": _service_path(
            service, values.get("dockerfile", "Dockerfile"), f"{service}.dockerfile"
        ),
    }
    for field, default in (("sources", ["."]), ("excludes", ["chart"])):
        raw = values.get(field, default)
        if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
            raise CIError(f"service {service!r} field {field!r} must be a list of relative paths")
        image[field] = [_service_path(service, item, f"{service}.{field}") for item in raw]
    return image


def expand_service_images(services: Any) -> list[dict[str, Any]]:
    """Expand service-based image configuration into normalized image entries."""
    if not isinstance(services, dict) or not services:
        raise CIError("Image configuration must define a non-empty 'services' mapping")
    images: list[dict[str, Any]] = []
    for raw_service, raw_values in services.items():
        service = _simple_name(raw_service, "image service")
        if raw_values is None:
            raw_values = {}
        if not isinstance(raw_values, dict):
            raise CIError(f"service {service!r} must be a mapping")
        values = dict(raw_values)
        variants = values.pop("images", None)
        if variants is None:
            images.append(_expand_service_image(service, None, values))
            continue
        if not isinstance(variants, dict) or not variants:
            raise CIError(f"service {service!r} 'images' must be a non-empty mapping")
        _image_overrides(values, f"service {service!r}")
        for raw_variant, raw_variant_values in variants.items():
            variant = _simple_name(raw_variant, f"service {service!r} image variant")
            if raw_variant_values is None:
                raw_variant_values = {}
            if not isinstance(raw_variant_values, dict):
                raise CIError(f"service {service!r} image {variant!r} must be a mapping")
            merged = dict(values)
            merged.update(raw_variant_values)
            images.append(_expand_service_image(service, variant, merged))
    return images


def load_images_config(path: Path) -> dict[str, Any]:
    """Load, normalize, and validate the image configuration."""
    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CIError(f"Image configuration does not exist: {path}") from exc
    except yaml.YAMLError as exc:
        raise CIError(f"Could not parse YAML in {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise CIError(f"{path} must contain a top-level YAML mapping")
    if not isinstance(config.get("registry"), str) or not config["registry"].strip():
        raise CIError(f"{path} must define a non-empty top-level 'registry'")
    if "services" in config:
        images = expand_service_images(config["services"])
    elif isinstance(config.get("images"), list):
        # Keep accepting normalized image data for focused helper tests and
        # gradual migration of external callers.
        images = config["images"]
    else:
        raise CIError(f"{path} must define a 'services' mapping or normalized 'images' array")
    names: set[str] = set()
    for index, image in enumerate(images, start=1):
        if not isinstance(image, dict):
            raise CIError(f"{path} image #{index} must be an object")
        missing = [field for field in REQUIRED_IMAGE_FIELDS if field not in image]
        if missing:
            raise CIError(f"{path} image #{index} is missing: {', '.join(missing)}")
        name = image.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise CIError(f"Image names must be non-empty and unique: {name!r}")
        names.add(name)
        for field in ("sources", "excludes"):
            if not isinstance(image[field], list) or not all(
                isinstance(item, str) and item for item in image[field]
            ):
                raise CIError(f"Image {name!r} field {field!r} must be a list of paths")
    return {"registry": config["registry"], "images": images}


def validate_images(root: Path, config_path: Path) -> dict[str, Any]:
    """Validate image paths, repositories, and chart metadata."""
    config = load_images_config(config_path)
    errors: list[str] = []
    if config["registry"] != REGISTRY:
        errors.append(f"registry must be {REGISTRY!r}, not {config['registry']!r}")

    for image in config["images"]:
        name = image["name"]
        try:
            chart_path = chart_file(_configured_path(root, image["chart"], f"{name}.chart"))
            context = _configured_path(root, image["context"], f"{name}.context")
            dockerfile = _configured_path(root, image["dockerfile"], f"{name}.dockerfile")
            sources = [
                _configured_path(root, value, f"{name}.sources") for value in image["sources"]
            ]
            excludes = [
                _configured_path(root, value, f"{name}.excludes") for value in image["excludes"]
            ]
            for path, kind in [(chart_path, "chart"), (dockerfile, "Dockerfile")]:
                if not path.is_file():
                    raise CIError(f"Image {name!r} configured {kind} does not exist: {path}")
            for path, kind in [(context, "context"), *[(p, "source") for p in sources], *[(p, "exclude") for p in excludes]]:
                if not path.exists():
                    raise CIError(f"Image {name!r} configured {kind} does not exist: {path}")
            repository = image.get("repository")
            if not isinstance(repository, str) or not repository:
                raise CIError(
                    f"Image {name!r} repository must be relative to {config['registry']}: {repository!r}"
                )
            if repository.startswith(("/", config["registry"] + "/")) or "://" in repository:
                raise CIError(
                    f"Image {name!r} repository must be relative to {config['registry']}: {repository!r}"
                )
            chart_data = read_yaml(chart_path)
            chart_name = metadata_value(chart_data, "name", str(chart_path))
            if chart_name != image.get("component"):
                raise CIError(
                    f"Image {name!r} component {image.get('component')!r} does not match "
                    f"chart name {chart_name!r}"
                )
            app_version = metadata_value(chart_data, "appVersion", str(chart_path))
            SemVer.parse(app_version, f"{chart_path} appVersion")
        except CIError as exc:
            errors.append(str(exc))
    if errors:
        raise CIError("Image configuration is invalid:\n- " + "\n- ".join(errors))
    return config


def validate_chart(root: Path, chart_dir: Path) -> tuple[str, dict[str, Any]]:
    """Validate a chart and its locked local dependencies."""
    chart_path = chart_dir / "Chart.yaml"
    data = read_yaml(chart_path)
    name = metadata_value(data, "name", str(chart_path))
    version = metadata_value(data, "version", str(chart_path))
    SemVer.parse(version, f"{chart_path} version")
    dependencies = exact_locked_dependencies(chart_dir)
    for dependency in dependencies:
        if not dependency.repository.startswith("file://"):
            continue
        target = (chart_dir / dependency.repository.removeprefix("file://")).resolve()
        target_chart = target / "Chart.yaml"
        if not target_chart.is_file():
            raise CIError(
                f"{chart_path} local dependency {dependency.name!r} does not resolve: {target_chart}"
            )
        target_data = read_yaml(target_chart)
        target_name = metadata_value(target_data, "name", str(target_chart))
        target_version = metadata_value(target_data, "version", str(target_chart))
        if (target_name, target_version) != (dependency.name, dependency.version):
            raise CIError(
                f"{chart_path} local dependency {dependency.name!r} resolves to "
                f"{target_name!r} {target_version!r}, expected {dependency.version!r}"
            )
    return name, data


def validate_config(root: Path = ROOT, config_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Validate all charts and image configuration and return chart metadata."""
    charts: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for chart_dir in discover_chart_dirs(root):
        try:
            name, data = validate_chart(root, chart_dir)
            if name in seen:
                raise CIError(
                    f"Chart name {name!r} is duplicated in {seen[name] / 'Chart.yaml'} "
                    f"and {chart_dir / 'Chart.yaml'}"
                )
            seen[name] = chart_dir
            charts[name] = data
        except CIError as exc:
            errors.append(str(exc))
    try:
        validate_images(root, config_path or root / IMAGES_FILE)
    except CIError as exc:
        errors.append(str(exc))
    if errors:
        raise CIError("Configuration validation failed:\n- " + "\n- ".join(errors))
    return charts


def path_is_within(path: str, prefix: str) -> bool:
    """Return whether path is prefix itself or a descendant of prefix."""
    normalized = prefix.strip("/")
    return path == normalized or path.startswith(normalized + "/")


def image_source_changed(image: dict[str, Any], paths: Iterable[str]) -> bool:
    """Return whether changed paths affect an image's included, non-excluded sources."""
    return any(
        any(path_is_within(path, source) for source in image["sources"])
        and not any(path_is_within(path, excluded) for excluded in image["excludes"])
        for path in paths
    )


def git_run(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a Git command in root and raise a CIError on failure."""
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=False
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CIError(f"git {' '.join(args)} failed: {detail}")
    return result


def changed_paths(root: Path, base: str) -> list[str]:
    """Return files changed from base to HEAD."""
    result = git_run(root, "diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base}..HEAD", "--")
    return [line for line in result.stdout.splitlines() if line]


def git_file(root: Path, revision: str, path: str) -> str | None:
    """Return a file's contents at a Git revision, or None if unavailable."""
    result = git_run(root, "show", f"{revision}:{path}", check=False)
    return result.stdout if result.returncode == 0 else None


def _base_chart(root: Path, base: str, chart_dir: Path) -> dict[str, Any] | None:
    """Load a chart's Chart.yaml from the base revision if it exists."""
    path = relative_path(root, chart_dir / "Chart.yaml")
    content = git_file(root, base, path)
    return _yaml_mapping(content, f"{base}:{path}") if content is not None else None


def _require_increase(current: str, previous: str, label: str) -> None:
    """Require current to be a greater semantic version than previous."""
    if SemVer.parse(current, label) <= SemVer.parse(previous, f"base {label}"):
        raise CIError(f"{label} must increase above {previous!r}; current value is {current!r}")


def check_versions(root: Path, base: str, config_path: Path | None = None) -> None:
    """Ensure changed chart and image versions increase over the base revision."""
    git_run(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    paths = changed_paths(root, base)
    errors: list[str] = []
    chart_dirs = discover_chart_dirs(root)
    for chart_dir in chart_dirs:
        relative_dir = relative_path(root, chart_dir)
        if not any(path_is_within(path, relative_dir) for path in paths):
            continue
        previous = _base_chart(root, base, chart_dir)
        if previous is None:  # New or moved chart.
            continue
        current = read_yaml(chart_dir / "Chart.yaml")
        try:
            _require_increase(
                metadata_value(current, "version", str(chart_dir / "Chart.yaml")),
                metadata_value(previous, "version", f"{base}:{relative_dir}/Chart.yaml"),
                f"{relative_dir} chart version",
            )
        except CIError as exc:
            errors.append(str(exc))

    config = load_images_config(config_path or root / IMAGES_FILE)
    checked_components: set[tuple[str, str]] = set()
    for image in config["images"]:
        if not image_source_changed(image, paths):
            continue
        key = (image["component"], image["chart"])
        if key in checked_components:
            continue
        checked_components.add(key)
        chart_dir = _configured_path(root, image["chart"], f"{image['name']}.chart")
        previous = _base_chart(root, base, chart_dir)
        if previous is None:
            continue
        current = read_yaml(chart_file(chart_dir))
        try:
            _require_increase(
                metadata_value(current, "appVersion", str(chart_file(chart_dir))),
                metadata_value(previous, "appVersion", f"{base}:{image['chart']}/Chart.yaml"),
                f"{image['component']} appVersion",
            )
        except CIError as exc:
            errors.append(str(exc))
    if errors:
        raise CIError("Version checks failed:\n- " + "\n- ".join(errors))


def image_matrix(
    root: Path,
    *,
    all_images: bool = False,
    target: str | None = None,
    base: str | None = None,
    config_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Select images for CI and build their versioned job matrix entries."""
    config = load_images_config(config_path or root / IMAGES_FILE)
    images = config["images"]
    if sum((all_images, target is not None, base is not None)) != 1:
        raise CIError("Choose exactly one of --all, --target, or --base")
    if all_images or target == "all":
        selected = images
    elif target is not None:
        selected = [image for image in images if image["name"] == target]
        if not selected:
            raise CIError(
                f"Unknown image target {target!r}; choose 'all' or one of: "
                + ", ".join(image["name"] for image in images)
            )
    else:
        assert base is not None
        paths = changed_paths(root, base)
        rebuild_all = any(
            path_is_within(path, shared_path)
            for path in paths
            for shared_path in REBUILD_ALL_IMAGE_PATHS
        )
        selected = images if rebuild_all else [
            image for image in images if image_source_changed(image, paths)
        ]

    matrix: list[dict[str, Any]] = []
    for image in selected:
        entry = dict(image)
        entry["job_name"] = f"Build {image['name']} image"
        data = read_yaml(chart_file(_configured_path(root, image["chart"], f"{image['name']}.chart")))
        app_version = metadata_value(data, "appVersion", str(chart_file(image["chart"])))
        SemVer.parse(app_version, f"{image['component']} appVersion")
        entry["tag"] = f"v{app_version}"
        matrix.append(entry)
    return matrix


def empty_image() -> dict[str, Any]:
    """Return a placeholder matrix entry when no images need building."""
    return {
        "name": "none changed",
        "job_name": "No images to build",
        "component": "",
        "chart": "",
        "repository": "",
        "context": "",
        "dockerfile": "",
        "sources": [],
        "excludes": [],
        "tag": "",
    }


def write_github_outputs(path: Path, values: dict[str, str]) -> None:
    """Append key-value pairs to a GitHub Actions output file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def compact_json(value: Any) -> str:
    """Serialize a value as deterministic compact JSON."""
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def service_chart_matrix(root: Path) -> list[str]:
    """Return service chart paths for a GitHub Actions matrix."""
    charts = [relative_path(root, path.parent) for path in (root / "services").glob("*/chart/Chart.yaml")]
    return sorted(charts) or ["__none__"]


def release_decision(current: str, previous: str | None, force: bool = False) -> bool:
    """Determine whether the umbrella chart should be released."""
    current_version = SemVer.parse(current, "umbrella version")
    if previous is None:
        return force
    previous_version = SemVer.parse(previous, "base umbrella version")
    if current_version < previous_version:
        raise CIError(f"Umbrella version regressed from {previous!r} to {current!r}")
    return force or current_version > previous_version


def release_info(root: Path, base: str, force: bool = False) -> dict[str, str]:
    """Collect the current and base umbrella versions and release decision."""
    current_data = read_yaml(root / UMBRELLA_DIR / "Chart.yaml")
    current = metadata_value(current_data, "version", str(root / UMBRELLA_DIR / "Chart.yaml"))
    git_run(root, "rev-parse", "--verify", f"{base}^{{commit}}")
    base_path = (UMBRELLA_DIR / "Chart.yaml").as_posix()
    old_content = git_file(root, base, base_path)
    previous = None
    if old_content is not None:
        previous = metadata_value(
            _yaml_mapping(old_content, f"{base}:{base_path}"), "version", f"{base}:{base_path}"
        )
    return {
        "release": str(release_decision(current, previous, force)).lower(),
        "version": current,
        "tag": f"v{current}",
    }


def archive_metadata(path: Path) -> dict[str, Any]:
    """Read Chart.yaml metadata from a chart archive."""
    try:
        with tarfile.open(path, "r:*") as archive:
            candidates = [
                member
                for member in archive.getmembers()
                if member.isfile()
                and len(PurePosixPath(member.name).parts) == 2
                and PurePosixPath(member.name).name == "Chart.yaml"
            ]
            if len(candidates) != 1:
                raise CIError(f"{path} must contain exactly one <chart>/Chart.yaml")
            stream = archive.extractfile(candidates[0])
            if stream is None:
                raise CIError(f"Could not read Chart.yaml from {path}")
            return _yaml_mapping(stream.read().decode("utf-8"), f"{path}:Chart.yaml")
    except (tarfile.TarError, UnicodeDecodeError) as exc:
        raise CIError(f"Could not read chart archive {path}: {exc}") from exc


def inspect_digest(reference: str) -> str:
    """Inspect a container image and return its immutable digest."""
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", reference],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise CIError(f"Could not inspect {reference}: {result.stderr.strip()}")
    match = DIGEST_RE.search(result.stdout)
    if not match:
        raise CIError(f"docker buildx imagetools inspect reported no digest for {reference}")
    return match.group(1)


def build_release_manifest(
    root: Path,
    commit: str,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Build a release manifest with locked charts and image digests."""
    umbrella_dir = root / UMBRELLA_DIR
    umbrella = read_yaml(umbrella_dir / "Chart.yaml")
    name = metadata_value(umbrella, "name", str(umbrella_dir / "Chart.yaml"))
    version = metadata_value(umbrella, "version", str(umbrella_dir / "Chart.yaml"))
    SemVer.parse(version, "umbrella version")
    locked = exact_locked_dependencies(umbrella_dir)
    lock_data = read_yaml(umbrella_dir / "Chart.lock")
    lock_digest = metadata_value(lock_data, "digest", str(umbrella_dir / "Chart.lock"))
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", lock_digest):
        raise CIError(f"Invalid Helm lock digest in {umbrella_dir / 'Chart.lock'}: {lock_digest!r}")

    config = load_images_config(config_path or root / IMAGES_FILE)
    images_by_component: dict[str, list[dict[str, Any]]] = {}
    for image in config["images"]:
        images_by_component.setdefault(image["component"], []).append(image)

    dependencies: list[dict[str, Any]] = []
    for dependency in locked:
        archive = umbrella_dir / "charts" / f"{dependency.name}-{dependency.version}.tgz"
        if not archive.is_file():
            raise CIError(f"Locked dependency archive is missing: {archive}")
        metadata = archive_metadata(archive)
        archive_name = metadata_value(metadata, "name", f"{archive}:Chart.yaml")
        archive_version = metadata_value(metadata, "version", f"{archive}:Chart.yaml")
        if (archive_name, archive_version) != (dependency.name, dependency.version):
            raise CIError(
                f"{archive} contains {archive_name!r} {archive_version!r}; lock requires "
                f"{dependency.name!r} {dependency.version!r}"
            )
        app_version = str(metadata["appVersion"]).strip() if metadata.get("appVersion") is not None else None
        record: dict[str, Any] = {
            "name": archive_name,
            "version": archive_version,
            "repository": dependency.repository,
            "type": str(metadata.get("type", "application")),
            "app_version": app_version,
            "images": [],
        }
        configured_images = images_by_component.get(dependency.name, [])
        if configured_images:
            if app_version is None:
                raise CIError(f"Image-owning dependency {dependency.name!r} has no appVersion")
            SemVer.parse(app_version, f"{dependency.name} appVersion")
            for image in configured_images:
                tag = f"v{app_version}"
                reference = f"{config['registry']}/{image['repository']}:{tag}"
                digest = inspect_digest(reference)
                record["images"].append(
                    {
                        "name": image["name"],
                        "tag": tag,
                        "reference": reference,
                        "digest": digest,
                        "immutable_reference": f"{reference.rsplit(':', 1)[0]}@{digest}",
                    }
                )
        dependencies.append(record)

    return {
        "schema_version": 1,
        "release": {"tag": f"v{version}", "version": version, "commit": commit},
        "umbrella": {"name": name, "version": version, "lock_digest": lock_digest},
        "dependencies": dependencies,
    }


def release_notes(manifest: dict[str, Any]) -> str:
    """Render release manifest data as Markdown release notes."""
    release = manifest["release"]
    umbrella = manifest["umbrella"]
    lines = [
        f"# HeLx release {release['tag']}",
        "",
        f"- Commit: `{release['commit']}`",
        f"- Umbrella chart: `{umbrella['name']} {umbrella['version']}`",
        f"- Helm lock digest: `{umbrella['lock_digest']}`",
        "",
        "## Locked dependencies",
        "",
        "| Chart | Version | appVersion | Images |",
        "| --- | --- | --- | --- |",
    ]
    for dependency in manifest["dependencies"]:
        images = "; ".join(
            f"`{image['reference']}` (`{image['digest']}`)" for image in dependency["images"]
        ) or "—"
        app_version = f"`{dependency['app_version']}`" if dependency["app_version"] else "—"
        lines.append(
            f"| {dependency['name']} | `{dependency['version']}` | {app_version} | {images} |"
        )
    return "\n".join(lines) + "\n"


def output_path(root: Path, value: str) -> Path:
    """Resolve a CLI output path relative to root unless already absolute."""
    path = Path(value)
    return path if path.is_absolute() else root / path


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CI command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("validate-config")

    versions = commands.add_parser("check-versions")
    versions.add_argument("--base", required=True)

    images = commands.add_parser("image-matrix")
    image_selection = images.add_mutually_exclusive_group(required=True)
    image_selection.add_argument("--base")
    image_selection.add_argument("--all", action="store_true", dest="all_images")
    image_selection.add_argument("--target")
    images.add_argument("--github-output", required=True)

    charts = commands.add_parser("chart-matrix")
    charts.add_argument("--github-output", required=True)

    field = commands.add_parser("chart-field")
    field.add_argument("chart_dir")
    field.add_argument("field")

    locked = commands.add_parser("locked-dependencies")
    locked.add_argument("chart_dir")

    info = commands.add_parser("release-info")
    info.add_argument("--base", required=True)
    info.add_argument("--github-output", required=True)
    info.add_argument("--force", action="store_true")

    manifest = commands.add_parser("release-manifest")
    manifest.add_argument("--commit", required=True)
    manifest.add_argument("--output", required=True)
    manifest.add_argument("--notes", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested CI command and return its process exit code."""
    args = parse_args(argv)
    try:
        if args.command == "validate-config":
            charts = validate_config(ROOT)
            image_count = len(load_images_config(ROOT / IMAGES_FILE)["images"])
            print(f"Validated {len(charts)} charts and {image_count} images")
        elif args.command == "check-versions":
            check_versions(ROOT, args.base)
            print("Version checks passed")
        elif args.command == "image-matrix":
            selected = image_matrix(
                ROOT,
                all_images=args.all_images,
                target=args.target,
                base=args.base,
            )
            write_github_outputs(
                output_path(ROOT, args.github_output),
                {"matrix": compact_json(selected or [empty_image()])},
            )
        elif args.command == "chart-matrix":
            write_github_outputs(
                output_path(ROOT, args.github_output),
                {"matrix": compact_json(service_chart_matrix(ROOT))},
            )
        elif args.command == "chart-field":
            data = read_yaml(chart_file(output_path(ROOT, args.chart_dir)))
            value = metadata_value(data, args.field, str(chart_file(args.chart_dir)))
            print(value)
        elif args.command == "locked-dependencies":
            for dependency in exact_locked_dependencies(output_path(ROOT, args.chart_dir)):
                print(dependency.tsv())
        elif args.command == "release-info":
            write_github_outputs(
                output_path(ROOT, args.github_output), release_info(ROOT, args.base, args.force)
            )
        elif args.command == "release-manifest":
            manifest = build_release_manifest(ROOT, args.commit)
            output_path(ROOT, args.output).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            output_path(ROOT, args.notes).write_text(release_notes(manifest), encoding="utf-8")
        return 0
    except (CIError, OSError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
