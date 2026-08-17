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

    def test_full_validation_checks_canonical_images_and_unique_charts(self) -> None:
        self.write_chart("services/app/chart", name="app", app_version="2.0.0")
        self.write_chart("deploy/helm/helx-common/chart", name="helx-common")
        self.write_chart("deploy/helm/helx-chart", name="helx")
        images = []
        for index, name in enumerate(sorted(ci.CANONICAL_IMAGES)):
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
            ".github/ci/images.json",
            json.dumps({"registry": ci.REGISTRY, "images": images}),
        )
        charts = ci.validate_config(self.root, config)
        self.assertEqual(set(charts), {"app", "helx-common", "helx"})

        self.write_chart("services/duplicate/chart", name="app")
        with self.assertRaisesRegex(ci.CIError, "duplicated"):
            ci.validate_config(self.root, config)


class ImageMatrixTests(TempTreeTest):
    def setUp(self) -> None:
        super().setUp()
        self.write_chart("services/api/chart", name="api", app_version="3.4.5")
        self.config = self.write(
            "images.json",
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
            "images.json",
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


if __name__ == "__main__":
    unittest.main()
