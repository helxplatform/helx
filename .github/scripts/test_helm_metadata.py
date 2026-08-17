from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helm_metadata import (
    Dependency,
    HelmMetadataError,
    dependencies,
    local_dependency_paths,
    locked_dependencies,
    resolve_file_repository,
)


class HelmMetadataTests(unittest.TestCase):
    def write(self, directory: str, name: str, content: str) -> Path:
        path = Path(directory) / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_parses_dependency_tuples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chart = self.write(
                directory,
                "Chart.yaml",
                "dependencies:\n"
                "  - name: local\n"
                "    version: \"1.2.3\" # pinned\n"
                "    repository: file://../local\n",
            )
            self.assertEqual(
                dependencies(chart),
                [Dependency("local", "1.2.3", "file://../local")],
            )

    def test_lock_must_match_chart_dependencies_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chart = self.write(
                directory,
                "Chart.yaml",
                "dependencies:\n  - name: sample\n    version: 1.0.0\n    repository: oci://example.test\n",
            )
            lock = self.write(
                directory,
                "Chart.lock",
                "dependencies:\n- name: sample\n  version: 1.0.1\n  repository: oci://example.test\n",
            )
            with self.assertRaisesRegex(HelmMetadataError, "do not match"):
                locked_dependencies(chart, lock)

    def test_resolves_file_dependencies_relative_to_chart(self) -> None:
        chart_dir = Path("deploy/helm/helx-chart")
        self.assertEqual(
            resolve_file_repository(chart_dir, "file://../../../services/helx-ldap/chart"),
            Path("services/helx-ldap/chart"),
        )

    def test_lists_only_local_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            chart_dir = Path(directory)
            self.write(
                directory,
                "Chart.yaml",
                "dependencies:\n"
                "  - name: local\n"
                "    version: 1.0.0\n"
                "    repository: file://../local\n"
                "  - name: remote\n"
                "    version: 2.0.0\n"
                "    repository: oci://example.test/charts\n",
            )
            self.assertEqual(
                local_dependency_paths(chart_dir),
                [Path(directory).parent / "local"],
            )


if __name__ == "__main__":
    unittest.main()
