from __future__ import annotations

import argparse
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

PLANNER = runpy.run_path(str(Path(__file__).with_name("release-plan.py")))
BASELINE = runpy.run_path(str(Path(__file__).with_name("release-baseline.py")))
baseline_commit = BASELINE["baseline_commit"]
create_plan = PLANNER["create_plan"]
plan_summary = PLANNER["plan_summary"]
resolve_develop_base = PLANNER["resolve_develop_base"]


class ReleasePlanCommandTests(unittest.TestCase):
    def test_baseline_query_returns_latest_marked_ancestor_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "components.json"
            config.write_text('{"marker": "release-marker"}', encoding="utf-8")
            with patch.dict(
                baseline_commit.__globals__,
                {
                    "git_output": Mock(return_value="h" * 40),
                    "select_release_baseline": Mock(
                        return_value=(None, {"commit": "a" * 40})
                    ),
                },
            ):
                self.assertEqual(baseline_commit(config, "HEAD"), "a" * 40)

    def test_initial_push_zero_base_means_build_without_baseline(self) -> None:
        self.assertIsNone(resolve_develop_base("0" * 40))

    def test_develop_plan_resolves_head_and_base_before_delegating(self) -> None:
        args = argparse.Namespace(
            mode="develop",
            config=".github/release/components.json",
            head="HEAD",
            base="HEAD^",
        )
        plan = {"mode": "develop"}
        resolve = Mock(side_effect=["h" * 40, "b" * 40])
        develop = Mock(return_value=plan)
        with patch.dict(
            create_plan.__globals__,
            {
                "load_config": Mock(return_value={"components": []}),
                "resolve_commit": resolve,
                "plan_develop": develop,
            },
        ):
            self.assertIs(create_plan(args), plan)

        develop.assert_called_once_with(
            create_plan.__globals__["ROOT"],
            {"components": []},
            "h" * 40,
            "b" * 40,
        )

    def test_summary_exposes_release_decisions_without_full_plan(self) -> None:
        summary = plan_summary(
            {
                "mode": "release",
                "head": "a" * 40,
                "release": {"tag": "v4.5.7", "previous_tag": None},
                "already_released": False,
                "build_images": [{"name": "appstore"}],
                "plan_hash": "digest",
            }
        )
        self.assertEqual(summary["release_tag"], "v4.5.7")
        self.assertEqual(summary["images"], ["appstore"])


if __name__ == "__main__":
    unittest.main()
