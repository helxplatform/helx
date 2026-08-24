from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.write("services/app/chart/values.yaml", "controller:\n  image:\n    tag: latest\n")
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


if __name__ == "__main__":
    unittest.main()
