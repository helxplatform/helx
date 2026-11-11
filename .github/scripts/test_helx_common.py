from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

HELX_COMMON = Path(__file__).resolve().parents[2] / "deploy/helm/helx-common/chart"

# The last key sorts last, where a YAML round trip or Helm's per-manifest
# whitespace trimming used to cut trailing line breaks.
TRICKY_VALUES = {
    "no final newline": "value",
    "final newline": "-----BEGIN KEY-----\nAAAA\n-----END KEY-----\n",
    "two final newlines": "line\n\n",
    "leading newline": "\nline\n",
    "leading and trailing spaces": "  padded  ",
    "tab": "a\tb\n",
}


@unittest.skipUnless(shutil.which("helm"), "helm is not installed")
class SecretValuesRenderTests(unittest.TestCase):
    """Render a synthetic chart against the in-tree helx-common with helm template."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.chart = Path(self.temporary.name) / "probe"
        (self.chart / "templates").mkdir(parents=True)
        (self.chart / "Chart.yaml").write_text("apiVersion: v2\nname: probe\nversion: 0.1.0\n")
        shutil.copytree(HELX_COMMON, self.chart / "charts/helx-common")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def render_string_data(self, cases: list[dict[str, str]]) -> list[dict[str, str]]:
        """Render each case as the values of its own Secret, in one helm run.

        Each Secret comes from its own template file, so Helm trims each one as
        a separate manifest, exactly as it would trim a chart's only Secret.
        """
        for index in range(len(cases)):
            (self.chart / f"templates/secret-{index}.yaml").write_text(
                '{{ include "helx-common.secret.resources.v1" (dict\n'
                f'  "root" . "defaultName" "probe-{index}" "mode" "values"\n'
                f'  "values" (index .Values.cases {index})) }}}}\n'
            )
        values_file = self.chart.parent / "values.json"
        values_file.write_text(json.dumps({"cases": cases}))
        result = subprocess.run(
            ["helm", "template", "probe", str(self.chart), "--values", str(values_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        secrets = {doc["metadata"]["name"]: doc for doc in yaml.safe_load_all(result.stdout) if doc}
        self.assertEqual(len(secrets), len(cases))
        rendered = []
        for index in range(len(cases)):
            secret = secrets[f"probe-{index}"]
            self.assertEqual(secret["kind"], "Secret")
            rendered.append(secret["stringData"])
        return rendered

    def test_values_mode_keeps_every_value_byte_for_byte(self) -> None:
        cases = [{"a-first": value, "z-last": value} for value in TRICKY_VALUES.values()]
        for label, values, rendered in zip(TRICKY_VALUES, cases, self.render_string_data(cases)):
            with self.subTest(label):
                self.assertEqual(rendered, values)


if __name__ == "__main__":
    unittest.main()
