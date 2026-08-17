from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from release_lib import (
    ComponentVersionDelta,
    ReleaseError,
    SemVer,
    component_version_delta,
    delta_level,
    extract_manifest,
    image_release_decision,
    manifest_message,
    marked_releases,
    monorepo_bump,
    path_is_within,
    plan_develop,
    plan_release,
    read_chart,
    removal_delta,
    select_release_baseline,
    select_release_version,
    validate_component_change_versions,
)


class SemVerTests(unittest.TestCase):
    def test_short_numeric_versions_are_normalized(self) -> None:
        self.assertEqual(str(SemVer.parse("0.8")), "0.8.0")
        self.assertEqual(str(SemVer.parse("v4")), "4.0.0")

    def test_highest_delta_classification(self) -> None:
        self.assertEqual(delta_level("2.0.0", "1.9.9"), 3)
        self.assertEqual(delta_level("1.3.0", "1.2.9"), 2)
        self.assertEqual(delta_level("1.2.4", "1.2.3"), 1)
        self.assertEqual(delta_level("0.8", "0.8.0"), 0)

    def test_prerelease_precedence(self) -> None:
        self.assertLess(SemVer.parse("1.0.0-rc.1"), SemVer.parse("1.0.0"))
        self.assertLess(SemVer.parse("1.0.0-rc.1"), SemVer.parse("1.0.0-rc.2"))

    def test_rejects_non_numeric_application_versions(self) -> None:
        with self.assertRaises(ReleaseError):
            SemVer.parse("latest")


class ManifestTests(unittest.TestCase):
    def test_tag_message_round_trip(self) -> None:
        manifest = {
            "schema_version": 1,
            "marker": "helx-monorepo-release",
            "release": {"tag": "v4.5.7"},
            "components": [],
        }
        message = manifest_message("helx-monorepo-release", manifest)
        self.assertEqual(extract_manifest(message, "helx-monorepo-release"), manifest)

    def test_chart_parser_reads_short_and_missing_app_versions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chart = Path(directory) / "Chart.yaml"
            chart.write_text(
                "apiVersion: v2\nname: sample\ntype: library\nversion: 0.8\n",
                encoding="utf-8",
            )
            parsed = read_chart(chart)
            self.assertEqual(parsed["chart_version"], "0.8")
            self.assertIsNone(parsed["app_version"])

    def test_dependency_chart_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chart = Path(directory) / "Chart.yaml"
            chart.write_text(
                "apiVersion: v2\nname: umbrella\nversion: 1.0.0\n"
                "dependencies:\n  - name: search\n    version: \"7.0.0\"\n",
                encoding="utf-8",
            )
            parsed = read_chart(chart, "search")
            self.assertEqual(parsed["chart_version"], "7.0.0")
            self.assertIsNone(parsed["app_version"])


class ExtractedReleaseRequirementTests(unittest.TestCase):
    def test_baseline_search_is_limited_to_marked_ancestors_of_head(self) -> None:
        head = "b" * 40
        releases = [
            {"tag": "v1.0.0", "commit": "a" * 40},
            {"tag": "v1.1.0", "commit": head},
        ]
        with patch("release_lib.marked_releases", return_value=releases) as marked:
            existing, previous = select_release_baseline("release-marker", head)

        marked.assert_called_once_with("release-marker", head)
        self.assertEqual(existing, releases[-1])
        self.assertEqual(previous, releases[-1])

    def test_component_delta_reports_highest_chart_or_app_change(self) -> None:
        current = {
            "name": "sample",
            "chart_version": "2.0.0",
            "app_version": "1.3.0",
        }
        prior = {"chart_version": "1.9.0", "app_version": "1.2.9"}

        version = component_version_delta(current, prior)

        self.assertGreater(version.chart_comparison, 0)
        self.assertGreater(version.app_comparison, 0)
        self.assertEqual(version.level, 3)

    def test_chart_change_requires_chart_version_increase(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "chart version did not increase"):
            validate_component_change_versions(
                {"name": "sample"},
                {"chart_version": "1.0.0", "app_version": "1.0.0"},
                {"chart": True, "image_source": False},
                ComponentVersionDelta(0, 0, 0),
                bootstrap=False,
            )

    def test_image_source_change_requires_app_version_increase(self) -> None:
        with self.assertRaisesRegex(ReleaseError, "appVersion did not increase"):
            validate_component_change_versions(
                {"name": "sample"},
                {"chart_version": "1.0.0", "app_version": "1.0.0"},
                {"chart": False, "image_source": True},
                ComponentVersionDelta(0, 0, 0),
                bootstrap=False,
            )

    def test_component_or_image_removal_is_a_major_delta(self) -> None:
        self.assertEqual(removal_delta(["removed-component"], []), 3)
        self.assertEqual(removal_delta([], ["component/removed-image"]), 3)
        self.assertEqual(removal_delta([], []), 0)

    def test_shared_rebuild_builds_but_does_not_promote_unchanged_image(self) -> None:
        decision = image_release_decision(
            bootstrap=False,
            source_changed=False,
            app_comparison=0,
            component_is_new=False,
            shared_rebuild=True,
        )
        self.assertTrue(decision.build)
        self.assertFalse(decision.promote)

    def test_app_version_increase_builds_and_promotes_image(self) -> None:
        decision = image_release_decision(
            bootstrap=False,
            source_changed=False,
            app_comparison=1,
            component_is_new=False,
            shared_rebuild=False,
        )
        self.assertTrue(decision.build)
        self.assertTrue(decision.promote)

    def test_monorepo_defaults_to_patch_and_preserves_major_delta(self) -> None:
        self.assertEqual(monorepo_bump(0), (1, "patch"))
        self.assertEqual(monorepo_bump(3), (3, "major"))

    def test_reserved_tag_collision_is_not_silently_skipped(self) -> None:
        previous = {"version": SemVer.parse("4.5.7")}
        with patch("release_lib.ref_exists", return_value=True), self.assertRaisesRegex(
            ReleaseError, "namespace is reserved"
        ):
            select_release_version("0.0.0", previous, 2)

    def test_lightweight_v_tag_violates_reserved_namespace(self) -> None:
        with patch(
            "release_lib.git_output",
            return_value="v4.5.7\tcommit",
        ), self.assertRaisesRegex(ReleaseError, "not annotated"):
            marked_releases("helx-monorepo-release")

    def test_unmarked_v_tag_violates_reserved_namespace(self) -> None:
        with patch(
            "release_lib.git_output",
            side_effect=["v4.5.7\ttag", "ordinary tag message"],
        ), self.assertRaisesRegex(ReleaseError, "lacks marker"):
            marked_releases("helx-monorepo-release")


class PlannerInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = {
            "name": "appstore",
            "chart": "services/appstore/chart/Chart.yaml",
            "image_sources": ["services/appstore"],
            "image_excludes": ["services/appstore/chart"],
            "images": [
                {
                    "name": "appstore",
                    "app_name": "appstore",
                    "repository": "appstore",
                    "context": "./services/appstore",
                    "dockerfile": "./services/appstore/Dockerfile",
                }
            ],
        }
        self.config = {
            "marker": "helx-monorepo-release",
            "registry": "containers.renci.org/helxplatform",
            "initial_version": "4.5.7",
            "rebuild_all_paths": [
                ".github/actions/build-service",
                ".github/release",
                ".github/scripts/release-",
                ".github/workflows/build-release.yml",
            ],
            "components": [self.definition],
        }
        self.previous: dict[str, Any] = {
            "tag": "v4.5.7",
            "version": SemVer.parse("4.5.7"),
            "commit": "a" * 40,
            "manifest": {
                "release": {"tag": "v4.5.7"},
                "components": [
                    {
                        "name": "appstore",
                        "chart_version": "1.0.0",
                        "app_version": "1.0.0",
                        "images": [
                            {
                                "name": "appstore",
                                "release_ref": "containers.renci.org/helxplatform/appstore:v1.0.0",
                                "digest": "sha256:" + "1" * 64,
                            }
                        ],
                    }
                ],
            },
        }

    def current(self, chart_version: str, app_version: str) -> list[dict]:
        return [
            {
                "name": "appstore",
                "type": "application",
                "chart_source": self.definition["chart"],
                "chart_version": chart_version,
                "app_version": app_version,
                "component_version": app_version,
                "definition": self.definition,
            }
        ]

    def patches(self, paths: list[str], current: list[dict]):
        return (
            patch("release_lib.marked_releases", return_value=[self.previous]),
            patch("release_lib.changed_paths", return_value=paths),
            patch("release_lib.current_components", return_value=current),
        )

    def test_image_source_requires_app_version_increase(self) -> None:
        first, second, third = self.patches(
            ["services/appstore/app.py"], self.current("1.0.0", "1.0.0")
        )
        with first, second, third, self.assertRaisesRegex(ReleaseError, "appVersion did not increase"):
            plan_release(Path("."), self.config, "b" * 40)

    def test_chart_change_requires_chart_version_increase(self) -> None:
        first, second, third = self.patches(
            ["services/appstore/chart/values.yaml"], self.current("1.0.0", "1.0.0")
        )
        with first, second, third, self.assertRaisesRegex(ReleaseError, "chart version did not increase"):
            plan_release(Path("."), self.config, "b" * 40)

    def test_component_major_delta_drives_monorepo_major_bump(self) -> None:
        first, second, third = self.patches(
            ["services/appstore/chart/Chart.yaml"], self.current("2.0.0", "1.1.0")
        )
        with first, second, third, patch("release_lib.ref_exists", return_value=False), patch(
            "release_lib.git_output", return_value="2026-08-16T00:00:00Z"
        ):
            plan = plan_release(Path("."), self.config, "b" * 40)
        self.assertEqual(plan["release"]["tag"], "v5.0.0")
        self.assertEqual(plan["release"]["bump"], "major")
        self.assertEqual(
            plan["build_images"][0]["release_ref"],
            "containers.renci.org/helxplatform/appstore:v1.1.0",
        )
        self.assertTrue(plan["build_images"][0]["promote"])

    def test_bootstrap_uses_configured_umbrella_lineage_version(self) -> None:
        with patch("release_lib.marked_releases", return_value=[]), patch(
            "release_lib.changed_paths", return_value=[]
        ), patch(
            "release_lib.current_components", return_value=self.current("1.0.0", "1.0.0")
        ), patch("release_lib.ref_exists", return_value=False), patch(
            "release_lib.git_output", return_value="2026-08-16T00:00:00Z"
        ):
            plan = plan_release(Path("."), self.config, "b" * 40)
        self.assertEqual(plan["release"]["tag"], "v4.5.7")
        self.assertTrue(plan["release"]["bootstrap"])
        self.assertTrue(plan["build_images"][0]["promote"])

    def test_shared_logic_change_rebuilds_without_retagging_unchanged_image(self) -> None:
        shared_paths = (
            ".github/actions/build-service/action.yml",
            ".github/release/release_lib.py",
            ".github/scripts/release-promote.py",
            ".github/workflows/build-release.yml",
        )
        for shared_path in shared_paths:
            with self.subTest(shared_path=shared_path):
                first, second, third = self.patches(
                    [shared_path], self.current("1.0.0", "1.0.0")
                )
                with first, second, third, patch(
                    "release_lib.ref_exists", return_value=False
                ), patch("release_lib.git_output", return_value="2026-08-16T00:00:00Z"):
                    plan = plan_release(Path("."), self.config, "b" * 40)
                self.assertEqual(plan["release"]["tag"], "v4.5.8")
                self.assertEqual(len(plan["build_images"]), 1)
                self.assertFalse(plan["build_images"][0]["promote"])
                self.assertTrue(plan["components"][0]["changes"]["shared_rebuild"])
                self.assertFalse(plan["components"][0]["changes"]["image_source"])
                self.assertEqual(
                    plan["components"][0]["images"][0]["digest"], "sha256:" + "1" * 64
                )

    def test_docs_only_change_creates_patch_release_without_image_build(self) -> None:
        first, second, third = self.patches(
            ["docs/operator-guide.md"], self.current("1.0.0", "1.0.0")
        )
        with first, second, third, patch("release_lib.ref_exists", return_value=False), patch(
            "release_lib.git_output", return_value="2026-08-16T00:00:00Z"
        ):
            plan = plan_release(Path("."), self.config, "b" * 40)
        self.assertEqual(plan["release"]["tag"], "v4.5.8")
        self.assertEqual(plan["release"]["bump"], "patch")
        self.assertEqual(plan["build_images"], [])

    def test_component_removal_forces_monorepo_major_bump(self) -> None:
        first, second, third = self.patches(
            [".github/release/components.json"], []
        )
        with first, second, third, patch("release_lib.ref_exists", return_value=False), patch(
            "release_lib.git_output", return_value="2026-08-16T00:00:00Z"
        ):
            plan = plan_release(Path("."), self.config, "b" * 40)
        self.assertEqual(plan["release"]["tag"], "v5.0.0")
        self.assertEqual(plan["release"]["bump"], "major")
        self.assertEqual(plan["release"]["removed_components"], ["appstore"])

    def test_image_removal_forces_monorepo_major_bump(self) -> None:
        previous = copy.deepcopy(self.previous)
        previous["manifest"]["components"][0]["images"].append(
            {
                "name": "sidecar",
                "release_ref": "containers.renci.org/helxplatform/sidecar:v1.0.0",
                "digest": "sha256:" + "2" * 64,
            }
        )
        with patch("release_lib.marked_releases", return_value=[previous]), patch(
            "release_lib.changed_paths", return_value=[".github/release/components.json"]
        ), patch(
            "release_lib.current_components", return_value=self.current("1.0.0", "1.0.0")
        ), patch("release_lib.ref_exists", return_value=False), patch(
            "release_lib.git_output", return_value="2026-08-16T00:00:00Z"
        ):
            plan = plan_release(Path("."), self.config, "b" * 40)

        self.assertEqual(plan["release"]["tag"], "v5.0.0")
        self.assertEqual(plan["release"]["bump"], "major")
        self.assertEqual(plan["release"]["removed_images"], ["appstore/sidecar"])

    def test_develop_without_base_rebuilds_every_image(self) -> None:
        with patch("release_lib.changed_paths", return_value=[]), patch(
            "release_lib.current_components", return_value=self.current("1.0.0", "1.0.0")
        ):
            plan = plan_develop(Path("."), self.config, "b" * 40, None)
        self.assertEqual(len(plan["build_images"]), 1)
        self.assertEqual(plan["build_images"][0]["staging_tag"], "develop_" + "b" * 40)

    def test_release_script_prefix_matches_all_shared_helpers(self) -> None:
        self.assertTrue(path_is_within(".github/scripts/release-plan.py", ".github/scripts/release-"))
        self.assertTrue(path_is_within(".github/scripts/release-baseline.py", ".github/scripts/release-"))
        self.assertTrue(
            path_is_within(".github/scripts/release-promote.py", ".github/scripts/release-")
        )


if __name__ == "__main__":
    unittest.main()
