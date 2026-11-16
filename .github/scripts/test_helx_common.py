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
        (self.chart / "templates/secret.yaml").write_text(
            '{{ include "helx-common.secret.resources.v1" (dict\n'
            '  "root" . "defaultName" "probe" "mode" "values" "values" .Values.values) }}\n'
        )
        shutil.copytree(HELX_COMMON, self.chart / "charts/helx-common")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def render_string_data(self, values: dict[str, str]) -> dict[str, str]:
        values_file = self.chart.parent / "values.json"
        values_file.write_text(json.dumps({"values": values}))
        result = subprocess.run(
            ["helm", "template", "probe", str(self.chart), "--values", str(values_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        (secret,) = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
        self.assertEqual(secret["kind"], "Secret")
        return secret["stringData"]

    def test_values_mode_keeps_every_value_byte_for_byte(self) -> None:
        for label, value in TRICKY_VALUES.items():
            with self.subTest(label):
                values = {"a-first": value, "z-last": value}
                self.assertEqual(self.render_string_data(values), values)


if __name__ == "__main__":
    unittest.main()
