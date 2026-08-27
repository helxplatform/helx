from __future__ import annotations

import contextlib
from collections.abc import Iterator
import importlib.util
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest

import yaml
from pathlib import Path
from unittest.mock import patch

@contextlib.contextmanager
def captured_stderr() -> Iterator[io.StringIO]:
    """Capture stderr so advisory warnings never reach the suite's own output.

    A warning printed by a test is indistinguishable from one CI should act on,
    so anything that deliberately triggers one captures it here instead.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        yield buffer


SCRIPT = Path(__file__).with_name("ci.py")
SPEC = importlib.util.spec_from_file_location("helx_ci", SCRIPT)
assert SPEC and SPEC.loader
ci = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ci
SPEC.loader.exec_module(ci)


class TempTreeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, content: str = "") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_chart(
        self,
        directory: str,
        *,
        name: str,
        version: str = "1.0.0",
        app_version: str | None = None,
        dependencies: str = "",
    ) -> Path:
        app = f'appVersion: "{app_version}"\n' if app_version is not None else ""
        return self.write(
            f"{directory}/Chart.yaml",
            f"apiVersion: v2\nname: {name}\nversion: {version}\n{app}{dependencies}",
        )


class SemVerTests(unittest.TestCase):
    def test_numeric_semver_and_prerelease_ordering(self) -> None:
        self.assertLess(ci.SemVer.parse("1.2.3-rc.2"), ci.SemVer.parse("1.2.3"))
        self.assertLess(ci.SemVer.parse("1.2.3-rc.2"), ci.SemVer.parse("1.2.3-rc.10"))
        self.assertGreater(ci.SemVer.parse("2.0.0"), ci.SemVer.parse("1.99.99"))

    def test_requires_three_numeric_components(self) -> None:
        with self.assertRaisesRegex(ci.CIError, "x.y.z"):
            ci.SemVer.parse("1.2")


class ConfigValidationTests(TempTreeTest):
    def test_exact_lock_and_local_dependency_metadata(self) -> None:
        child = self.write_chart("services/common/chart", name="common", version="1.2.3")
        parent = self.write_chart(
            "services/api/chart",
            name="api",
            dependencies=(
                "dependencies:\n"
                "  - name: common\n"
                "    version: 1.2.3\n"
                "    repository: file://../../common/chart\n"
            ),
        )
        lock = self.write(
            "services/api/chart/Chart.lock",
            "dependencies:\n"
            "  - name: common\n"
            "    version: 1.2.3\n"
            "    repository: file://../../common/chart\n",
        )
        self.assertEqual(ci.validate_chart(self.root, parent.parent)[0], "api")

        lock.write_text(lock.read_text().replace("1.2.3", "1.2.4"), encoding="utf-8")
        with self.assertRaisesRegex(ci.CIError, "tuples differ"):
            ci.exact_locked_dependencies(parent.parent)
        self.assertTrue(child.is_file())

    def test_full_validation_checks_image_definitions_and_unique_charts(self) -> None:
        self.write_chart("services/app/chart", name="app", app_version="2.0.0")
        self.write_chart("deploy/helm/helx-common/chart", name="helx-common")
        self.write_chart("deploy/helm/helx-chart", name="helx")
        for directory in (
            "services/app/chart",
            "deploy/helm/helx-common/chart",
            "deploy/helm/helx-chart",
        ):
            self.write(f"{directory}/.helmignore", "\n".join(ci.REQUIRED_HELMIGNORE) + "\n")
        images = []
        for index, name in enumerate(("app", "worker")):
            source = f"sources/{index}"
            self.write(f"{source}/Dockerfile", "FROM scratch\n")
            self.write(f"{source}/chart-only/keep", "")
            images.append(
                {
                    "name": name,
                    "component": "app",
                    "chart": "services/app/chart",
                    "repository": f"repo/{index}",
                    "context": source,
                    "dockerfile": f"{source}/Dockerfile",
                    "sources": [source],
                    "excludes": [f"{source}/chart-only"],
                }
            )
        config = self.write(
            ".github/ci/images.yaml",
            json.dumps({"registry": ci.REGISTRY, "images": images}),
        )
        charts = ci.validate_config(self.root, config)
        self.assertEqual(set(charts), {"app", "helx-common", "helx"})

        self.write_chart("services/duplicate/chart", name="app")
        with self.assertRaisesRegex(ci.CIError, "duplicated"):
            ci.validate_config(self.root, config)

    def test_tag_path_must_be_declared_in_the_chart_values(self) -> None:
        self.write_chart("services/app/chart", name="app", app_version="2.0.0")
        self.write_chart("deploy/helm/helx-common/chart", name="helx-common")
        self.write_chart("deploy/helm/helx-chart", name="helx")
        self.write(
            "services/app/chart/values.yaml",
            "controller:\n  image:\n    repository: example/app\n    tag: latest\n",
        )
        self.write("sources/Dockerfile", "FROM scratch\n")
        image = {
            "name": "app",
            "component": "app",
            "chart": "services/app/chart",
            "repository": "app",
            "context": "sources",
            "dockerfile": "sources/Dockerfile",
            "sources": ["sources"],
            "excludes": [],
        }
        good = self.write(
            "good.yaml",
            json.dumps(
                {
                    "registry": ci.REGISTRY,
                    "images": [dict(image, tag_path="controller.image.tag")],
                }
            ),
        )
        self.assertEqual(len(ci.validate_images(self.root, good)["images"]), 1)

        bad = self.write(
            "bad.yaml",
            json.dumps({"registry": ci.REGISTRY, "images": [dict(image, tag_path="image.tag")]}),
        )
        with self.assertRaisesRegex(ci.CIError, r"tag_path 'image.tag' is not declared"):
            ci.validate_images(self.root, bad)

    def test_service_defaults_and_variants_expand_to_normalized_images(self) -> None:
        images = ci.expand_service_images(
            {
                "appstore": {},
                "appstore-prepuller": {
                    "context": "controller",
                    "dockerfile": "controller/Dockerfile",
                },
                "appstore-sockets": {
                    "images": {
                        "server": {},
                        "monitoring": {
                            "context": "monitoring",
                            "dockerfile": "monitoring/Dockerfile",
                        },
                    }
                },
                "ldap-sync": {},
                "ui": {"repository": "helx-ui"},
            }
        )
        by_name = {image["name"]: image for image in images}

        self.assertEqual(by_name["ldap-sync"]["component"], "ldap-sync")
        self.assertEqual(by_name["ldap-sync"]["chart"], "services/ldap-sync/chart")
        self.assertEqual(by_name["ldap-sync"]["context"], "services/ldap-sync")
        self.assertEqual(by_name["ldap-sync"]["dockerfile"], "services/ldap-sync/Dockerfile")
        self.assertEqual(by_name["ldap-sync"]["sources"], ["services/ldap-sync"])
        self.assertEqual(by_name["ldap-sync"]["excludes"], ["services/ldap-sync/chart"])
        self.assertEqual(
            by_name["appstore-prepuller"]["context"],
            "services/appstore-prepuller/controller",
        )
        self.assertEqual(
            by_name["appstore-sockets-monitoring"]["repository"],
            "appstore-sockets/monitoring",
        )
        self.assertEqual(
            by_name["appstore-sockets-server"]["dockerfile"],
            "services/appstore-sockets/Dockerfile",
        )
        self.assertEqual(by_name["ui"]["repository"], "helx-ui")


class ImageMatrixTests(TempTreeTest):
    def setUp(self) -> None:
        super().setUp()
        self.write_chart("services/api/chart", name="api", app_version="3.4.5")
        self.config = self.write(
            "images.yaml",
            json.dumps(
                {
                    "registry": ci.REGISTRY,
                    "images": [
                        {
                            "name": "api",
                            "component": "api",
                            "chart": "services/api/chart",
                            "repository": "api",
                            "context": "services/api",
                            "dockerfile": "services/api/Dockerfile",
                            "sources": ["services/api"],
                            "excludes": ["services/api/chart"],
                        },
                        {
                            "name": "worker",
                            "component": "api",
                            "chart": "services/api/chart",
                            "repository": "api/worker",
                            "context": "services/api/worker",
                            "dockerfile": "services/api/worker/Dockerfile",
                            "sources": ["services/api/worker"],
                            "excludes": [],
                        },
                    ],
                }
            ),
        )

    def test_base_selects_sources_but_excludes_chart_paths(self) -> None:
        with patch.object(ci, "changed_paths", return_value=["services/api/chart/values.yaml"]):
            self.assertEqual(ci.image_matrix(self.root, base="base", config_path=self.config), [])

        with patch.object(ci, "changed_paths", return_value=["services/api/worker/job.py"]):
            matrix = ci.image_matrix(self.root, base="base", config_path=self.config)
        self.assertEqual([item["name"] for item in matrix], ["api", "worker"])
        self.assertEqual(
            [item["job_name"] for item in matrix],
            ["Build api image", "Build worker image"],
        )
        self.assertEqual({item["tag"] for item in matrix}, {"v3.4.5"})

    def test_shared_build_changes_select_every_image(self) -> None:
        with patch.object(
            ci, "changed_paths", return_value=[".github/actions/build-service/action.yml"]
        ):
            matrix = ci.image_matrix(self.root, base="base", config_path=self.config)
        self.assertEqual([item["name"] for item in matrix], ["api", "worker"])

    def test_empty_matrix_sentinel_has_blank_required_fields(self) -> None:
        sentinel = ci.empty_image()
        self.assertEqual(sentinel["name"], "none changed")
        self.assertEqual(sentinel["job_name"], "No images to build")
        self.assertEqual(sentinel["repository"], "")
        self.assertEqual(sentinel["tag"], "")


class ReleaseGateTests(unittest.TestCase):
    def test_release_requires_increase_unless_forced(self) -> None:
        self.assertTrue(ci.release_decision("4.5.7", "4.5.6"))
        self.assertFalse(ci.release_decision("4.5.6", "4.5.6"))
        self.assertTrue(ci.release_decision("4.5.6", "4.5.6", force=True))
        self.assertFalse(ci.release_decision("4.5.6", None))
        self.assertTrue(ci.release_decision("4.5.6", None, force=True))
        with self.assertRaisesRegex(ci.CIError, "regressed"):
            ci.release_decision("4.5.5", "4.5.6")


class ManifestTests(TempTreeTest):
    def chart_archive(self, relative: str, chart_yaml: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = chart_yaml.encode()
        info = tarfile.TarInfo("appstore/Chart.yaml")
        info.size = len(payload)
        info.mtime = 0
        with tarfile.open(path, "w:gz") as archive:
            archive.addfile(info, io.BytesIO(payload))
        return path

    def test_manifest_uses_locked_archive_metadata_and_mocked_digest(self) -> None:
        dependency = (
            "dependencies:\n"
            "  - name: appstore\n"
            "    version: 5.1.4\n"
            "    repository: oci://example.test/charts\n"
        )
        self.write_chart(
            "deploy/helm/helx-chart", name="helx", version="4.5.7", dependencies=dependency
        )
        digest = "sha256:" + "a" * 64
        self.write(
            "deploy/helm/helx-chart/Chart.lock",
            dependency + f"digest: {digest}\n",
        )
        self.chart_archive(
            "deploy/helm/helx-chart/charts/appstore-5.1.4.tgz",
            "apiVersion: v2\nname: appstore\nversion: 5.1.4\nappVersion: 4.4.1\n",
        )
        config = self.write(
            "images.yaml",
            json.dumps(
                {
                    "registry": ci.REGISTRY,
                    "images": [
                        {
                            "name": "appstore",
                            "component": "appstore",
                            "chart": "unused",
                            "repository": "appstore",
                            "context": "unused",
                            "dockerfile": "unused",
                            "sources": [],
                            "excludes": [],
                        },
                        {
                            "name": "not-in-umbrella",
                            "component": "other",
                            "chart": "unused",
                            "repository": "other",
                            "context": "unused",
                            "dockerfile": "unused",
                            "sources": [],
                            "excludes": [],
                        },
                    ],
                }
            ),
        )
        image_digest = "sha256:" + "b" * 64
        with patch.object(ci, "inspect_digest", return_value=image_digest) as inspect:
            manifest = ci.build_release_manifest(self.root, "commit-sha", config)

        self.assertEqual(manifest["release"]["tag"], "v4.5.7")
        self.assertEqual(manifest["umbrella"]["lock_digest"], digest)
        self.assertEqual([item["name"] for item in manifest["dependencies"]], ["appstore"])
        image = manifest["dependencies"][0]["images"][0]
        self.assertEqual(image["digest"], image_digest)
        inspect.assert_called_once_with(f"{ci.REGISTRY}/appstore:v4.4.1")
        self.assertNotIn("not-in-umbrella", json.dumps(manifest))

        notes = ci.release_notes(manifest)
        self.assertIn("# HeLx release v4.5.7", notes)
        self.assertIn("appstore", notes)


class CandidateChannelTests(TempTreeTest):
    def setUp(self) -> None:
        super().setUp()
        self.write_chart(
            "deploy/helm/helx-chart",
            name="helx",
            version="4.5.6",
            app_version="3.6.4",
            dependencies=(
                "dependencies:\n"
                "  - name: appstore\n"
                "    version: 5.1.4\n"
                "    repository: oci://ghcr.io/helxplatform/helm-charts\n"
                "  - name: sockets\n"
                "    version: 2.1.0\n"
                "    repository: oci://ghcr.io/helxplatform/helm-charts\n"
            ),
        )
        self.write(
            "deploy/helm/helx-chart/Chart.lock",
            "dependencies:\n"
            "  - name: appstore\n"
            "    version: 5.1.4\n"
            "    repository: oci://ghcr.io/helxplatform/helm-charts\n"
            "  - name: sockets\n"
            "    version: 2.1.0\n"
            "    repository: oci://ghcr.io/helxplatform/helm-charts\n",
        )
        self.write_chart("services/appstore/chart", name="appstore", app_version="3.6.4")
        self.write_chart("services/sockets/chart", name="sockets", app_version="2.1.0")
        self.write_chart("services/loose/chart", name="loose", app_version="1.0.0")
        self.config = self.write(
            "images.yaml",
            json.dumps(
                {
                    "registry": ci.REGISTRY,
                    "images": [
                        {
                            "name": "appstore",
                            "component": "appstore",
                            "chart": "services/appstore/chart",
                            "repository": "appstore",
                            "context": "services/appstore",
                            "dockerfile": "services/appstore/Dockerfile",
                            "sources": ["services/appstore"],
                            "excludes": [],
                        },
                        {
                            "name": "sockets-monitoring",
                            "component": "sockets",
                            "chart": "services/sockets/chart",
                            "repository": "sockets/monitoring",
                            "context": "services/sockets/monitoring",
                            "dockerfile": "services/sockets/monitoring/Dockerfile",
                            "sources": ["services/sockets/monitoring"],
                            "excludes": [],
                            "tag_path": "monitoring.image.tag",
                        },
                        {
                            # Not an umbrella dependency, so it earns no override.
                            "name": "loose",
                            "component": "loose",
                            "chart": "services/loose/chart",
                            "repository": "loose",
                            "context": "services/loose",
                            "dockerfile": "services/loose/Dockerfile",
                            "sources": ["services/loose"],
                            "excludes": [],
                        },
                    ],
                }
            ),
        )

    def test_candidate_version_is_a_prerelease_below_the_release(self) -> None:
        candidate = ci.candidate_version("4.5.6", "develop")
        self.assertEqual(candidate, "4.5.6-develop")
        self.assertLess(ci.SemVer.parse(candidate), ci.SemVer.parse("4.5.6"))

    def test_candidate_version_rejects_prerelease_input_and_bad_channels(self) -> None:
        with self.assertRaisesRegex(ci.CIError, "prerelease"):
            ci.candidate_version("4.5.6-develop", "develop")
        for channel in ("Develop", "de_velop", "", "-develop"):
            with self.assertRaisesRegex(ci.CIError, "Channel"):
                ci.candidate_version("4.5.6", channel)

    def test_candidate_image_tag_shortens_the_commit(self) -> None:
        self.assertEqual(
            ci.candidate_image_tag("develop", "e3452604aaaabbbbccccddddeeeeffff00001111"),
            "develop-e345260",
        )
        with self.assertRaisesRegex(ci.CIError, "hexadecimal"):
            ci.candidate_image_tag("develop", "not-a-sha")

    def test_deep_merge_keeps_unrelated_existing_values(self) -> None:
        merged = ci.deep_merge(
            {"global": {"keep": True}, "appstore": {"replicas": 2}},
            {"appstore": {"image": {"tag": "develop-abc1234"}}},
        )
        self.assertEqual(merged["global"], {"keep": True})
        self.assertEqual(merged["appstore"], {"replicas": 2, "image": {"tag": "develop-abc1234"}})

    def test_candidate_values_cover_locked_dependencies_only(self) -> None:
        overlay = ci.candidate_values(
            self.root, "develop", "e3452604aaaabbbb", config_path=self.config
        )
        self.assertEqual(
            overlay,
            {
                "appstore": {"image": {"tag": "develop-e345260"}},
                "sockets": {"monitoring": {"image": {"tag": "develop-e345260"}}},
            },
        )
        self.assertNotIn("loose", overlay)

    def test_candidate_matrix_pins_every_image_to_one_tag(self) -> None:
        matrix = ci.image_matrix(
            self.root,
            all_images=True,
            config_path=self.config,
            channel="develop",
            commit="e3452604aaaabbbb",
        )
        self.assertEqual({entry["tag"] for entry in matrix}, {"develop-e345260"})

    def test_candidate_matrix_requires_a_commit(self) -> None:
        with self.assertRaisesRegex(ci.CIError, "commit"):
            ci.image_matrix(self.root, all_images=True, config_path=self.config, channel="develop")


class LockDigestTests(unittest.TestCase):
    # Oracle: this dependency set and digest were produced by helm itself and
    # committed as deploy/helm/helx-chart/Chart.lock, so the assertion pins the
    # exact field order and omitempty behaviour of Helm's resolver.HashReq.
    REGISTRY = "oci://ghcr.io/helxplatform/helm-charts"
    PINS = (
        ("appstore", "5.1.4", REGISTRY),
        ("appstore-sockets", "2.1.0", REGISTRY),
        ("backup-pvc-cronjob", "0.2.1", REGISTRY),
        ("helx-ldap", "0.1.2", "file://../../../services/helx-ldap/chart"),
        ("image-utils", "1.0.0", REGISTRY),
        ("nfs-server", "0.2.5", REGISTRY),
        ("nfsrods", "2.0.4", REGISTRY),
        ("pod-reaper", "0.2.5", REGISTRY),
        ("resty", "1.0.5", REGISTRY),
        ("search", "7.0.0", REGISTRY),
        ("ui", "1.6.0", REGISTRY),
    )
    DIGEST = "sha256:f04ca543ec1ae416e77b6940cfd48b08331173f23fb2e02fcfe8f3c268b54fba"

    def test_reproduces_a_helm_generated_digest(self) -> None:
        chart = {
            "dependencies": [
                {
                    "name": name,
                    "condition": f"{name}.enabled",
                    "version": version,
                    "repository": repository,
                }
                for name, version, repository in self.PINS
            ]
        }
        locked = [ci.Dependency(n, v, r) for n, v, r in self.PINS]
        self.assertEqual(ci.lock_digest(chart, locked), self.DIGEST)

    def test_digest_changes_when_a_pin_changes(self) -> None:
        chart = {"dependencies": [{"name": "api", "version": "1.0.0", "repository": "oci://x/y"}]}
        locked = [ci.Dependency("api", "1.0.0", "oci://x/y")]
        bumped = [ci.Dependency("api", "1.0.1", "oci://x/y")]
        self.assertNotEqual(ci.lock_digest(chart, locked), ci.lock_digest(chart, bumped))


class DependencyVersionInvariantTests(TempTreeTest):
    REGISTRY = "oci://ghcr.io/helxplatform/helm-charts"

    def build(self, pin: str, tree: str, repository: str | None = None) -> None:
        self.write_chart("services/api/chart", name="api", version=tree, app_version="1.0.0")
        self.write_chart("deploy/helm/helx-common/chart", name="helx-common")
        self.write_chart(
            "deploy/helm/helx-chart",
            name="helx",
            version="4.6.0",
            dependencies=(
                "dependencies:\n"
                "  - name: api\n"
                f"    version: {pin}\n"
                f"    repository: {repository or self.REGISTRY}\n"
            ),
        )

    def test_equal_versions_are_accepted(self) -> None:
        self.build("1.2.3", "1.2.3")
        ci.validate_dependency_versions(self.root)

    def test_tree_ahead_of_the_pin_is_rejected(self) -> None:
        self.build("1.2.3", "1.2.4")
        with self.assertRaisesRegex(ci.CIError, r"pins 'api' '1.2.3'.*is '1.2.4'"):
            ci.validate_dependency_versions(self.root)

    def test_tree_behind_the_pin_is_rejected(self) -> None:
        self.build("1.2.4", "1.2.3")
        with self.assertRaisesRegex(ci.CIError, r"pins 'api' '1.2.4'.*is '1.2.3'"):
            ci.validate_dependency_versions(self.root)

    def test_file_dependencies_are_left_to_validate_chart(self) -> None:
        self.build("1.2.3", "1.2.4", repository="file://../../../services/api/chart")
        ci.validate_dependency_versions(self.root)

    def test_dependency_absent_from_the_tree_is_ignored(self) -> None:
        self.write_chart("deploy/helm/helx-common/chart", name="helx-common")
        self.write_chart(
            "deploy/helm/helx-chart",
            name="helx",
            version="4.6.0",
            dependencies=(
                "dependencies:\n"
                "  - name: external\n"
                "    version: 9.9.9\n"
                f"    repository: {self.REGISTRY}\n"
            ),
        )
        ci.validate_dependency_versions(self.root)


class LockSyncTests(TempTreeTest):
    def setUp(self) -> None:
        super().setUp()
        self.chart_dir = self.root / "deploy/helm/helx-chart"
        self.write_chart(
            "deploy/helm/helx-chart",
            name="helx",
            version="4.6.0",
            dependencies=(
                "dependencies:\n"
                "  - name: api\n"
                "    version: 1.2.3\n"
                "    repository: oci://example.invalid/charts\n"
            ),
        )

    def write_lock(self) -> None:
        (self.chart_dir / "Chart.lock").write_text(
            ci.render_lock(self.chart_dir), encoding="utf-8"
        )

    def test_rendered_lock_satisfies_the_exactness_check(self) -> None:
        self.write_lock()
        self.assertTrue(ci.lock_matches_chart(self.chart_dir))
        locked = ci.exact_locked_dependencies(self.chart_dir)
        self.assertEqual([(item.name, item.version) for item in locked], [("api", "1.2.3")])

    def test_missing_lock_does_not_match(self) -> None:
        self.assertFalse(ci.lock_matches_chart(self.chart_dir))

    def test_lock_goes_stale_when_a_pin_moves(self) -> None:
        self.write_lock()
        chart = self.chart_dir / "Chart.yaml"
        chart.write_text(chart.read_text().replace("1.2.3", "1.2.4"), encoding="utf-8")
        self.assertFalse(ci.lock_matches_chart(self.chart_dir))


BASELINE_HELMIGNORE = "\n".join(ci.REQUIRED_HELMIGNORE) + "\n"


class HelmIgnoreTests(TempTreeTest):
    def rules(self, body: str) -> Path:
        self.write_chart("services/api/chart", name="api")
        return self.write("services/api/chart/.helmignore", body)

    def test_bare_pattern_matches_a_base_name_at_any_depth(self) -> None:
        chart = self.rules(".gitignore\n").parent
        self.assertTrue(ci.helm_ignores(chart, ".gitignore"))
        self.assertTrue(ci.helm_ignores(chart, "templates/.gitignore"))
        self.assertFalse(ci.helm_ignores(chart, "Chart.yaml"))

    def test_glob_matches_by_base_name(self) -> None:
        chart = self.rules("*.swp\n").parent
        self.assertTrue(ci.helm_ignores(chart, "templates/deployment.yaml.swp"))
        self.assertFalse(ci.helm_ignores(chart, "templates/deployment.yaml"))

    def test_pattern_with_a_slash_is_anchored(self) -> None:
        chart = self.rules("charts/*/README.md\n").parent
        self.assertTrue(ci.helm_ignores(chart, "charts/sub/README.md"))
        self.assertFalse(ci.helm_ignores(chart, "README.md"))

    def test_directory_rule_excludes_the_whole_subtree(self) -> None:
        chart = self.rules(".git/\n").parent
        self.assertTrue(ci.helm_ignores(chart, ".git/config"))
        # A directory-only rule must not match a file of the same name.
        self.assertFalse(ci.helm_ignores(chart, ".git"))

    def test_negation_wins_when_it_is_matched_first(self) -> None:
        chart = self.rules("!README.md\nREADME.md\n").parent
        self.assertFalse(ci.helm_ignores(chart, "README.md"))

    def test_comments_and_blank_lines_are_skipped(self) -> None:
        chart = self.rules("# a comment\n\n.gitignore\n").parent
        self.assertEqual(len(ci.helmignore_rules(chart)), 1)

    def test_absent_helmignore_ignores_nothing(self) -> None:
        self.write_chart("services/api/chart", name="api")
        self.assertFalse(ci.helm_ignores(self.root / "services/api/chart", ".gitignore"))


class PackagedChangeTests(TempTreeTest):
    def setUp(self) -> None:
        super().setUp()
        self.write_chart("services/api/chart", name="api")
        self.write("services/api/chart/.helmignore", BASELINE_HELMIGNORE)
        self.chart_dir = self.root / "services/api/chart"

    def test_ignored_file_does_not_gate(self) -> None:
        self.assertFalse(
            ci.packaged_change(self.root, self.chart_dir, ["services/api/chart/.gitignore"])
        )

    def test_packaged_file_gates(self) -> None:
        for path in ("Chart.yaml", "Chart.lock", "values.yaml", "templates/deployment.yaml"):
            with self.subTest(path=path):
                self.assertTrue(
                    ci.packaged_change(self.root, self.chart_dir, [f"services/api/chart/{path}"])
                )

    def test_paths_outside_the_chart_do_not_gate(self) -> None:
        self.assertFalse(ci.packaged_change(self.root, self.chart_dir, [".github/workflows/ci.yml"]))


class HelmIgnoreValidationTests(TempTreeTest):
    def build(self, body: str | None) -> None:
        self.write_chart("services/api/chart", name="api")
        self.write_chart("deploy/helm/helx-common/chart", name="helx-common")
        self.write_chart("deploy/helm/helx-chart", name="helx")
        for directory in ("services/api/chart", "deploy/helm/helx-common/chart", "deploy/helm/helx-chart"):
            if body is not None:
                self.write(f"{directory}/.helmignore", body)

    def test_compliant_charts_pass(self) -> None:
        self.build(BASELINE_HELMIGNORE)
        ci.validate_helmignore(self.root)

    def test_missing_file_is_reported(self) -> None:
        self.build(None)
        with self.assertRaisesRegex(ci.CIError, "has no .helmignore"):
            ci.validate_helmignore(self.root)

    def test_missing_baseline_pattern_is_reported(self) -> None:
        self.build(BASELINE_HELMIGNORE.replace(".gitignore\n", ""))
        with self.assertRaisesRegex(ci.CIError, r"missing: \.gitignore"):
            ci.validate_helmignore(self.root)

    def test_excluding_an_essential_path_is_reported(self) -> None:
        self.build(BASELINE_HELMIGNORE + "templates/\n")
        with self.assertRaisesRegex(ci.CIError, "which every chart must package"):
            ci.validate_helmignore(self.root)


class DockerIgnoreTests(TempTreeTest):
    def context(self, body: str) -> Path:
        self.write("services/api/.dockerignore", body)
        return self.root / "services/api"

    def test_patterns_are_anchored_to_the_context_root(self) -> None:
        context = self.context("*.log\n")
        self.assertTrue(ci.docker_ignores(context, "build.log"))
        # Docker's match does not cross a path separator.
        self.assertFalse(ci.docker_ignores(context, "sub/build.log"))

    def test_directory_excludes_its_subtree(self) -> None:
        context = self.context("chart/\n")
        self.assertTrue(ci.docker_ignores(context, "chart/Chart.yaml"))
        self.assertFalse(ci.docker_ignores(context, "charts/Chart.yaml"))

    def test_absent_file_excludes_nothing(self) -> None:
        self.assertFalse(ci.docker_ignores(self.root / "services/api", "anything"))

    def test_image_gate_skips_paths_docker_never_receives(self) -> None:
        self.write_chart("services/api/chart", name="api", app_version="1.0.0")
        self.write("services/api/Dockerfile", "FROM scratch\n")
        self.context("README.md\n")
        image = {
            "name": "api",
            "component": "api",
            "chart": "services/api/chart",
            "repository": "api",
            "context": "services/api",
            "dockerfile": "services/api/Dockerfile",
            "sources": ["services/api"],
            "excludes": [],
        }
        self.assertFalse(ci.image_source_changed(image, ["services/api/README.md"], self.root))
        self.assertTrue(ci.image_source_changed(image, ["services/api/main.go"], self.root))
        # Without a root there is no context to consult, so nothing is filtered.
        self.assertTrue(ci.image_source_changed(image, ["services/api/README.md"]))

    def test_unsupported_syntax_is_rejected(self) -> None:
        self.write_chart("services/api/chart", name="api", app_version="1.0.0")
        self.write("services/api/Dockerfile", "FROM scratch\n")
        self.context("!keep.me\n")
        config = self.write(
            "images.yaml",
            json.dumps(
                {
                    "registry": ci.REGISTRY,
                    "images": [
                        {
                            "name": "api",
                            "component": "api",
                            "chart": "services/api/chart",
                            "repository": "api",
                            "context": "services/api",
                            "dockerfile": "services/api/Dockerfile",
                            "sources": ["services/api"],
                            "excludes": [],
                        }
                    ],
                }
            ),
        )
        with self.assertRaisesRegex(ci.CIError, "negation and"):
            ci.validate_dockerignore(self.root, config)


class UntrackedChangeTests(TempTreeTest):
    """A local run must be able to see what CI will see once files are committed."""

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-c", "user.email=ci@example.invalid", "-c", "user.name=ci", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )

    def setUp(self) -> None:
        super().setUp()
        self.git("init", "-q")
        self.write_chart("services/api/chart", name="api", version="1.0.0")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def test_untracked_file_is_invisible_by_default(self) -> None:
        # The exact shape of the bug: a newly created .helmignore is packaged, so
        # it changes the chart, but base..HEAD cannot see it until it is committed.
        self.write("services/api/chart/.helmignore", ".gitignore\n")
        self.assertEqual(ci.changed_paths(self.root, self.base), [])
        self.assertEqual(
            ci.changed_paths(self.root, self.base, include_untracked=True),
            ["services/api/chart/.helmignore"],
        )

    def test_uncommitted_modification_is_invisible_by_default(self) -> None:
        chart = self.root / "services/api/chart/Chart.yaml"
        chart.write_text(chart.read_text() + "description: edited\n", encoding="utf-8")
        self.assertEqual(ci.changed_paths(self.root, self.base), [])
        self.assertEqual(
            ci.changed_paths(self.root, self.base, include_untracked=True),
            ["services/api/chart/Chart.yaml"],
        )

    def test_gitignored_files_stay_out_of_both_modes(self) -> None:
        self.write(".gitignore", "ignored/\n")
        self.write("ignored/junk.txt", "junk")
        self.assertNotIn(
            "ignored/junk.txt", ci.changed_paths(self.root, self.base, include_untracked=True)
        )

    def test_version_gate_catches_an_untracked_chart_file(self) -> None:
        self.write("services/api/chart/.helmignore", ".gitignore\n")
        empty = {"registry": ci.REGISTRY, "images": []}
        with patch.object(ci, "load_images_config", return_value=empty):
            # Committed history alone shows nothing to gate on.
            ci.check_versions(self.root, self.base)
            with self.assertRaisesRegex(ci.CIError, "chart version must increase"):
                ci.check_versions(self.root, self.base, include_untracked=True)


class LocalServiceBuildTests(TempTreeTest):
    """A developer rebuilding one service should pin only that service."""

    def setUp(self) -> None:
        super().setUp()
        self.write_chart(
            "deploy/helm/helx-chart",
            name="helx",
            version="4.6.1",
            dependencies=(
                "dependencies:\n"
                "  - name: api\n"
                "    version: 1.0.0\n"
                "    repository: oci://example.invalid/charts\n"
                "  - name: worker\n"
                "    version: 2.0.0\n"
                "    repository: oci://example.invalid/charts\n"
            ),
        )
        self.write(
            "deploy/helm/helx-chart/Chart.lock",
            "dependencies:\n"
            "  - name: api\n"
            "    version: 1.0.0\n"
            "    repository: oci://example.invalid/charts\n"
            "  - name: worker\n"
            "    version: 2.0.0\n"
            "    repository: oci://example.invalid/charts\n",
        )
        self.config = self.write(
            "images.yaml",
            json.dumps(
                {
                    "registry": ci.REGISTRY,
                    "images": [
                        {
                            "name": name,
                            "component": component,
                            "chart": f"services/{component}/chart",
                            "repository": repository,
                            "context": f"services/{component}",
                            "dockerfile": f"services/{component}/Dockerfile",
                            "sources": [f"services/{component}"],
                            "excludes": [],
                            **({"tag_path": tag_path} if tag_path else {}),
                        }
                        for name, component, repository, tag_path in (
                            ("api", "api", "api", None),
                            ("worker", "worker", "worker", None),
                            ("worker-sidecar", "worker", "worker/sidecar", "sidecar.image.tag"),
                        )
                    ],
                }
            ),
        )

    def test_plan_lists_every_variant_of_a_service(self) -> None:
        plan = ci.image_plan(self.root, ["worker"], config_path=self.config)
        self.assertEqual(
            [(item["name"], item["reference"]) for item in plan],
            [
                ("worker", f"{ci.REGISTRY}/worker"),
                ("worker-sidecar", f"{ci.REGISTRY}/worker/sidecar"),
            ],
        )

    def test_plan_without_a_filter_returns_everything(self) -> None:
        self.assertEqual(len(ci.image_plan(self.root, None, config_path=self.config)), 3)

    def test_plan_rejects_an_unknown_service(self) -> None:
        with self.assertRaisesRegex(ci.CIError, "No image is configured for: nope"):
            ci.image_plan(self.root, ["nope"], config_path=self.config)

    def test_only_the_named_service_is_pinned(self) -> None:
        overlay = ci.candidate_values(
            self.root, "local", "abc1234", config_path=self.config,
            services=["worker"], tag="dev-1",
        )
        # api keeps its released tag by being absent from the overlay entirely.
        self.assertEqual(
            overlay,
            {"worker": {"image": {"tag": "dev-1"}, "sidecar": {"image": {"tag": "dev-1"}}}},
        )

    def test_no_filter_still_pins_everything(self) -> None:
        overlay = ci.candidate_values(
            self.root, "develop", "abc1234def", config_path=self.config
        )
        self.assertEqual(set(overlay), {"api", "worker"})
        self.assertEqual(overlay["api"]["image"]["tag"], "develop-abc1234")

    def test_an_empty_tag_falls_back_to_the_channel_tag(self) -> None:
        # helm-build-chart.sh passes an empty CHART_IMAGE_TAG to mean "unset".
        overlay = ci.candidate_values(
            self.root, "local", "abc1234", config_path=self.config,
            services=["worker"], tag="",
        )
        self.assertEqual(overlay["worker"]["image"]["tag"], "local-abc1234")

    def test_a_custom_registry_replaces_the_configured_one(self) -> None:
        with captured_stderr():
            plan = ci.image_plan(
                self.root, ["worker"], config_path=self.config,
                registry="myregistry.example.org/helx",
            )
        self.assertEqual(
            [item["reference"] for item in plan],
            [
                "myregistry.example.org/helx/worker",
                "myregistry.example.org/helx/worker/sidecar",
            ],
        )

    def test_a_custom_registry_also_repoints_the_chart(self) -> None:
        # Pushing elsewhere is useless if the chart still names Harbor, so the
        # repository beside each tag key is rewritten too.
        overlay = ci.candidate_values(
            self.root, "local", "abc1234", config_path=self.config,
            services=["worker"], tag="dev-1", registry="localhost:5000",
        )
        self.assertEqual(
            overlay,
            {
                "worker": {
                    "image": {
                        "repository": "localhost:5000/worker",
                        "tag": "dev-1",
                    },
                    "sidecar": {
                        "image": {
                            "repository": "localhost:5000/worker/sidecar",
                            "tag": "dev-1",
                        }
                    },
                }
            },
        )

    def test_without_a_registry_the_repository_is_left_alone(self) -> None:
        # Overriding it unasked would rewrite values the chart already ships.
        overlay = ci.candidate_values(
            self.root, "local", "abc1234", config_path=self.config,
            services=["worker"], tag="dev-1",
        )
        self.assertEqual(
            overlay,
            {"worker": {"image": {"tag": "dev-1"}, "sidecar": {"image": {"tag": "dev-1"}}}},
        )

    def test_a_registry_without_the_project_path_warns_but_still_builds(self) -> None:
        # Forgetting /helxplatform yields references nothing was pushed to, but
        # hosting at the registry root is legal, so this warns rather than fails.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            plan = ci.image_plan(
                self.root, ["worker"], config_path=self.config,
                registry="myregistry.example.org",
            )
        self.assertEqual(plan[0]["reference"], "myregistry.example.org/worker")
        message = stderr.getvalue()
        self.assertIn("::warning::", message)
        self.assertIn(ci.REGISTRY_PROJECT, message)
        self.assertIn("myregistry.example.org/<image>", message)

    def test_a_localhost_registry_is_exempt_from_the_warning(self) -> None:
        # A scratch registry beside a kind cluster serves from its root, so the
        # missing project path is intended and nagging about it trains it away.
        for registry in ("localhost:5000", "localhost", "localhost:5000/scratch"):
            with self.subTest(registry=registry):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    ci.image_plan(
                        self.root, ["worker"], config_path=self.config,
                        registry=registry,
                    )
                self.assertEqual(stderr.getvalue(), "")

    def test_a_hostname_merely_containing_localhost_still_warns(self) -> None:
        # Only the literal localhost host is exempt; a remote registry that
        # happens to spell it is still a real missing project path.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            ci.image_plan(
                self.root, ["worker"], config_path=self.config,
                registry="localhost.example.org",
            )
        self.assertIn("::warning::", stderr.getvalue())

    def test_a_registry_with_the_project_path_is_silent(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            ci.image_plan(
                self.root, ["worker"], config_path=self.config,
                registry=f"myregistry.example.org/{ci.REGISTRY_PROJECT}",
            )
        self.assertEqual(stderr.getvalue(), "")

    def test_the_default_registry_never_warns(self) -> None:
        # It ends in the project path by construction; a warning here would fire
        # on every ordinary build.
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            ci.image_plan(self.root, ["worker"], config_path=self.config)
        self.assertEqual(stderr.getvalue(), "")

    def test_an_invalid_registry_is_rejected_before_anything_is_built(self) -> None:
        with self.assertRaisesRegex(ci.CIError, "registry path segment"):
            ci.image_plan(
                self.root, ["worker"], config_path=self.config,
                registry="registry.example.org/Helx",
            )

    def test_literal_tag_is_validated(self) -> None:
        for bad in ("not a tag", "-leading", "x" * 200):
            with self.subTest(tag=bad), self.assertRaisesRegex(ci.CIError, "valid OCI image tag"):
                ci.candidate_values(
                    self.root, "local", "abc1234", config_path=self.config,
                    services=["worker"], tag=bad,
                )


class ImagePlanContractTests(TempTreeTest):
    """The Makefile reads image-plan positionally, so the column order is a contract.

    Reordering the printed fields would keep every other test green while making
    the Makefile push to the wrong image reference, so both halves are pinned here.
    """

    COLUMNS = ("component", "name", "reference", "context", "dockerfile")

    def setUp(self) -> None:
        super().setUp()
        self.write_chart("services/api/chart", name="api", app_version="1.0.0")
        self.write("services/api/Dockerfile", "FROM scratch\n")
        self.write(
            ".github/ci/images.yaml",
            json.dumps(
                {
                    "registry": ci.REGISTRY,
                    "images": [
                        {
                            "name": "api",
                            "component": "api",
                            "chart": "services/api/chart",
                            "repository": "renamed-api",
                            "context": "services/api",
                            "dockerfile": "services/api/Dockerfile",
                            "sources": ["services/api"],
                            "excludes": [],
                        }
                    ],
                }
            ),
        )

    def run_cli(self, *argv: str) -> list[list[str]]:
        buffer = io.StringIO()
        with patch.object(ci, "ROOT", self.root), contextlib.redirect_stdout(buffer):
            with captured_stderr() as errors:
                self.assertEqual(ci.main(list(argv)), 0)
        self.stderr = errors.getvalue()
        return [line.split("\t") for line in buffer.getvalue().splitlines() if line]

    def test_cli_emits_the_documented_columns_in_order(self) -> None:
        rows = self.run_cli("image-plan")
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(len(row), len(self.COLUMNS))
        plan = ci.image_plan(self.root, None)
        self.assertEqual(
            rows, [[str(item[column]) for column in self.COLUMNS] for item in plan]
        )

    def test_reference_is_registry_plus_repository_not_the_service_name(self) -> None:
        # The 'ui' service publishes 'helx-ui', so the reference cannot be derived
        # from the service name in shell; it has to come from this column.
        (row,) = self.run_cli("image-plan")
        self.assertEqual(row[self.COLUMNS.index("reference")], f"{ci.REGISTRY}/renamed-api")

    def test_cli_registry_flag_replaces_the_reference_prefix(self) -> None:
        (row,) = self.run_cli("image-plan", "--registry", "https://reg.example.org/team/")
        self.assertEqual(
            row[self.COLUMNS.index("reference")], "reg.example.org/team/renamed-api"
        )
        # The missing-project warning must stay on stderr: the Makefile reads
        # this plan from stdout, and a stray line would be parsed as an image.
        self.assertIn("::warning::", self.stderr)

    def test_makefile_read_order_matches_the_cli(self) -> None:
        makefile = SCRIPT.resolve().parents[2] / "Makefile"
        if not makefile.is_file():  # pragma: no cover - only when run outside the repo
            self.skipTest("Makefile not present")
        found = re.findall(r"read -r ([a-z_ ]+?)\s*;", makefile.read_text(encoding="utf-8"))
        self.assertTrue(found, "no 'read -r' consumer found in the Makefile")
        for names in found:
            self.assertEqual(tuple(names.split()), self.COLUMNS)

    def test_every_makefile_image_plan_with_services_honours_the_registry(self) -> None:
        # build, load, and push must agree on the reference, or one of them
        # silently operates on images the others never touched.
        makefile = SCRIPT.resolve().parents[2] / "Makefile"
        if not makefile.is_file():  # pragma: no cover - only when run outside the repo
            self.skipTest("Makefile not present")
        text = makefile.read_text(encoding="utf-8")
        self.assertIn('--registry "$(IMAGE_REGISTRY)"', text)
        calls = re.findall(r"\$\(CI_SCRIPT\) image-plan([^;\\\n]*)", text)
        self.assertTrue(calls, "no image-plan call found in the Makefile")
        # A bare listing needs no flags; anything that selects images must take
        # them from the shared variable, or build, load, and push would drift.
        selective = [
            flags.strip()
            for flags in calls
            if flags.strip() and not flags.strip().startswith("|")
        ]
        self.assertTrue(selective, "no image-plan call passes flags")
        for flags in selective:
            self.assertIn("$(IMAGE_PLAN_FLAGS)", flags)


class RegistryUrlTests(unittest.TestCase):
    """A registry base URL is normalized into an image reference prefix."""

    def test_accepted_forms(self) -> None:
        for value, expected in (
            ("containers.renci.org/helxplatform", "containers.renci.org/helxplatform"),
            ("https://myregistry.azurecr.io/helx", "myregistry.azurecr.io/helx"),
            ("http://registry.example.org/a/b/", "registry.example.org/a/b"),
            ("localhost:5000", "localhost:5000"),
            ("  registry.example.org/team_1  ", "registry.example.org/team_1"),
        ):
            with self.subTest(value=value):
                self.assertEqual(ci.validate_registry(value), expected)

    def test_rejected_forms(self) -> None:
        for value in (
            "",
            "   ",
            "reg example.org",
            "reg.example.org/Team",
            "reg.example.org/a//b",
            "-reg.example.org",
        ):
            with self.subTest(value=value), self.assertRaises(ci.CIError):
                ci.validate_registry(value)


class UmbrellaAboveReleaseTests(TempTreeTest):
    """The umbrella is judged against the last release, not every base revision."""

    def setUp(self) -> None:
        super().setUp()
        self.git("init", "-q")
        self.write_chart("services/api/chart", name="api", version="1.0.0", app_version="1.0.0")
        self.write_chart("deploy/helm/helx-common/chart", name="helx-common")
        self.write_chart("deploy/helm/helx-chart", name="helx", version="4.6.2")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        self.empty_images = {"registry": ci.REGISTRY, "images": []}

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-c", "user.email=ci@example.invalid", "-c", "user.name=ci", *args],
            cwd=self.root, text=True, capture_output=True, check=True,
        )

    def release(self, version: str) -> None:
        self.git("tag", f"v{version}")

    def set_umbrella(self, version: str) -> None:
        chart = self.root / "deploy/helm/helx-chart/Chart.yaml"
        chart.write_text(
            chart.read_text().replace("version: 4.6.2", f"version: {version}"), encoding="utf-8"
        )

    def touch_umbrella(self) -> None:
        chart = self.root / "deploy/helm/helx-chart/Chart.yaml"
        chart.write_text(chart.read_text() + "description: pins moved\n", encoding="utf-8")

    def check(self, **kwargs: bool) -> None:
        with patch.object(ci, "load_images_config", return_value=self.empty_images):
            ci.check_versions(self.root, self.base, include_untracked=True, **kwargs)

    def test_last_released_version_picks_the_highest_tag(self) -> None:
        self.assertIsNone(ci.last_released_version(self.root))
        for tag in ("v4.6.2", "v4.7.0", "v4.6.9", "not-a-release", "v-bogus"):
            self.git("tag", tag)
        self.assertEqual(ci.last_released_version(self.root), "4.7.0")

    def test_with_no_release_the_umbrella_is_unconstrained(self) -> None:
        # Nothing is published, so there is nothing to sit above.
        self.touch_umbrella()
        self.check(umbrella_above_release=True)

    def test_matching_the_last_release_is_rejected(self) -> None:
        self.release("4.6.2")
        self.touch_umbrella()
        with self.assertRaisesRegex(ci.CIError, "must sit above the last published release"):
            self.check(umbrella_above_release=True)

    def test_sitting_above_the_release_needs_no_further_bump(self) -> None:
        self.release("4.6.2")
        self.set_umbrella("4.7.0")
        self.git("add", "-A")
        self.git("commit", "-qm", "open 4.7.0")
        # A later change leaves the version alone and still passes.
        self.touch_umbrella()
        self.check(umbrella_above_release=True)

    def test_regression_against_the_base_is_rejected(self) -> None:
        self.release("4.0.0")
        self.set_umbrella("4.5.0")
        with self.assertRaisesRegex(ci.CIError, "must not decrease below"):
            self.check(umbrella_above_release=True)

    def test_default_mode_still_requires_a_bump_every_change(self) -> None:
        self.release("4.6.2")
        self.touch_umbrella()
        with self.assertRaisesRegex(ci.CIError, "helx-chart chart version must increase"):
            self.check()

    def test_the_rule_does_not_exempt_service_charts(self) -> None:
        chart = self.root / "services/api/chart/Chart.yaml"
        chart.write_text(chart.read_text() + "description: edited\n", encoding="utf-8")
        with self.assertRaisesRegex(ci.CIError, "services/api/chart chart version must increase"):
            self.check(umbrella_above_release=True)

    def test_the_rule_does_not_exempt_image_app_versions(self) -> None:
        self.write("services/api/main.go", "package main\n")
        self.write("services/api/Dockerfile", "FROM scratch\n")
        images = {
            "registry": ci.REGISTRY,
            "images": [{
                "name": "api", "component": "api", "chart": "services/api/chart",
                "repository": "api", "context": "services/api",
                "dockerfile": "services/api/Dockerfile",
                "sources": ["services/api"], "excludes": ["services/api/chart"],
            }],
        }
        with patch.object(ci, "load_images_config", return_value=images):
            with self.assertRaisesRegex(ci.CIError, "api appVersion must increase"):
                ci.check_versions(
                    self.root, self.base, include_untracked=True, umbrella_above_release=True
                )


class WorkflowShellSyntaxTests(unittest.TestCase):
    """Every `run:` block must be valid bash.

    A stray quote in a workflow parses fine as YAML and only fails when the step
    executes in CI, which is an expensive place to learn about it. actionlint
    catches this too, but only in CI; this runs locally via `make ci-tests` and
    `make pre-push`.
    """

    def workflow_files(self) -> list[Path]:
        root = SCRIPT.resolve().parents[2] / ".github"
        return sorted(root.glob("workflows/*.yml")) + sorted(root.glob("actions/*/action.yml"))

    def run_blocks(self, path: Path) -> list[tuple[str, str]]:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        steps: list[dict] = []
        for spec in (document.get("jobs") or {}).values():
            steps.extend(spec.get("steps") or [])
        steps.extend((document.get("runs") or {}).get("steps") or [])
        return [
            (step.get("name") or "<unnamed>", step["run"])
            for step in steps
            if isinstance(step, dict) and step.get("run")
        ]

    def test_every_run_block_is_valid_bash(self) -> None:
        files = self.workflow_files()
        self.assertTrue(files, "no workflow or action files found")
        checked = 0
        for path in files:
            for name, script in self.run_blocks(path):
                with self.subTest(workflow=path.name, step=name):
                    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as handle:
                        handle.write(script)
                        temporary = handle.name
                    try:
                        result = subprocess.run(
                            ["bash", "-n", temporary], capture_output=True, text=True
                        )
                    finally:
                        Path(temporary).unlink()
                    self.assertEqual(
                        result.returncode, 0, f"{path.name} step {name!r}: {result.stderr.strip()}"
                    )
                    checked += 1
        self.assertGreater(checked, 10, "suspiciously few run blocks discovered")


if __name__ == "__main__":
    unittest.main()
