from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

SCRIPT = Path(__file__).with_name("vault_secrets.py")
SPEC = importlib.util.spec_from_file_location("helx_vault_secrets", SCRIPT)
assert SPEC and SPEC.loader
vs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = vs
SPEC.loader.exec_module(vs)

REPO_MAP = SCRIPT.resolve().parents[2] / "deploy/helm/vault-secrets-map.yaml"

MAP = """
secrets:
  - name: "{release}-app-secrets"
    service: app
    values: app.secret.values
  - name: "{release}-db"
    service: app
    keys:
      postgres-password: app.db.auth.postgresPassword
    derived: [uri]
  - name: "{release}-tls"
    service: hook
    values: hook.secret.values
    set:
      hook.secret.mode: values
    encoded:
      hook.webhook.caBundle: ca.crt
"""


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def secret_doc(name: str, data: dict[str, str] | None = None, string_data: dict[str, str] | None = None) -> str:
    document: dict = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name}}
    if data is not None:
        document["data"] = {k: b64(v) for k, v in data.items()}
    if string_data is not None:
        document["stringData"] = string_data
    return yaml.safe_dump(document)


class TempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        (self.tmp / "map.yaml").write_text(MAP)
        self.specs = vs.load_map(self.tmp / "map.yaml")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class MapTests(TempDirTest):
    def test_repository_map_loads_and_covers_every_argocd_external_secret(self) -> None:
        specs = vs.load_map(REPO_MAP)
        names = {spec.name("helx") for spec in specs}
        self.assertEqual(
            names,
            {
                "helx-appstore-secrets", "pgadmin-env", "helx-postgresql",
                "helx-appstore-sockets", "openldap-credentials", "helx-ldap-sync-secrets",
                "helx-ldap-sync-postgres", "helx-user-mutator-tls",
                "helx-user-mutator-ldap-password",
            },
        )

    def test_values_path_keeps_dotted_key_names_as_one_segment(self) -> None:
        tls = self.specs[2]
        self.assertEqual(tls.values_path("tls.crt"), ("hook", "secret", "values", "tls.crt"))
        self.assertIsNone(self.specs[1].values_path("uri"))
        with self.assertRaisesRegex(vs.SecretsError, "has no place"):
            self.specs[1].values_path("unexpected")

    def test_map_rejects_both_or_neither_of_values_and_keys(self) -> None:
        for body in (
            "secrets:\n  - {name: a, service: s}\n",
            "secrets:\n  - {name: a, service: s, values: x.y, keys: {k: x.z}}\n",
        ):
            (self.tmp / "bad.yaml").write_text(body)
            with self.assertRaisesRegex(vs.SecretsError, "exactly one"):
                vs.load_map(self.tmp / "bad.yaml")

    def test_map_rejects_duplicates_unknown_fields_and_nested_services(self) -> None:
        cases = {
            "secrets:\n  - {name: a, service: s, values: x}\n  - {name: a, service: s, values: y}\n": "twice",
            "secrets:\n  - {name: a, service: s, values: x, extra: 1}\n": "unknown fields",
            "secrets:\n  - {name: a, service: s/t, values: x}\n": "single folder",
        }
        for body, message in cases.items():
            (self.tmp / "bad.yaml").write_text(body)
            with self.assertRaisesRegex(vs.SecretsError, message):
                vs.load_map(self.tmp / "bad.yaml")


class ValuesFileChoiceTests(TempDirTest):
    def choose(self, list_file: Path, extra: list[str]):
        return vs.choose_values_files(list_file, extra, root=self.tmp, home=self.tmp / "home")

    def test_no_list_file_and_no_values_is_an_error_naming_both_options(self) -> None:
        with self.assertRaisesRegex(vs.SecretsError, r"does not exist or lists no files, and VALUES is empty"):
            self.choose(self.tmp / "missing.env", [])

    def test_no_list_file_uses_values_and_does_not_use_the_list(self) -> None:
        (self.tmp / "a.yaml").write_text("{}")
        chosen = self.choose(self.tmp / "missing.env", ["a.yaml"])
        self.assertEqual(chosen.files, [self.tmp / "a.yaml"])
        self.assertFalse(chosen.uses_list)

    def test_list_file_listing_nothing_is_ignored(self) -> None:
        (self.tmp / "a.yaml").write_text("{}")
        listing = self.tmp / "list.env"
        listing.write_text("# only a comment\n\n")
        chosen = self.choose(listing, ["a.yaml"])
        self.assertFalse(chosen.uses_list)
        self.assertEqual(chosen.files, [self.tmp / "a.yaml"])
        with self.assertRaisesRegex(vs.SecretsError, "lists no files"):
            self.choose(listing, [])

    def test_list_file_entries_come_first_and_missing_ones_are_reported(self) -> None:
        home = self.tmp / "home"
        home.mkdir()
        (home / "secrets.yaml").write_text("{}")
        (self.tmp / "env.yaml").write_text("{}")
        (self.tmp / "extra.yaml").write_text("{}")
        listing = self.tmp / "list.env"
        listing.write_text("# comment\n\nenv.yaml\n~/secrets.yaml\nmissing.yaml\n")
        chosen = self.choose(listing, ["extra.yaml"])
        self.assertTrue(chosen.uses_list)
        self.assertEqual(chosen.files, [self.tmp / "env.yaml", home / "secrets.yaml", self.tmp / "extra.yaml"])
        self.assertEqual(len(chosen.list_warnings), 1)
        self.assertIn("line 5 names missing.yaml", chosen.list_warnings[0])

    def test_list_naming_only_missing_files_and_no_values_is_an_error(self) -> None:
        listing = self.tmp / "list.env"
        listing.write_text("gone.yaml\n")
        with self.assertRaisesRegex(vs.SecretsError, "none of the files .* lists exist"):
            self.choose(listing, [])

    def test_missing_values_file_is_an_error(self) -> None:
        with self.assertRaisesRegex(vs.SecretsError, "do not exist"):
            self.choose(self.tmp / "missing.env", ["nope.yaml"])


class TerminalPromptTests(unittest.TestCase):
    """confirm_on_tty against a real pseudo-terminal, not a stand-in."""

    def ask_through_pty(self, answer: bytes) -> tuple[bool, bytes]:
        """Run confirm_on_tty in a child whose controlling terminal is a new pty,
        answer like a person would, and return its answer and what it showed.

        Every wait is bounded, so a broken prompt fails the test instead of
        hanging it.
        """
        import pty
        import select
        import time

        pid, master = pty.fork()
        if pid == 0:  # child: /dev/tty is the pty
            try:
                code = 10 if vs.confirm_on_tty("Proceed? [y/N] ") else 11
            except BaseException:
                code = 12
            os._exit(code)
        try:
            shown = b""
            deadline = time.monotonic() + 10
            while b"Proceed?" not in shown and time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master, 1024)
                    except OSError:
                        break
                    if not chunk:
                        break
                    shown += chunk
            self.assertIn(b"Proceed? [y/N]", shown, "the prompt never reached the terminal")
            time.sleep(0.3)  # a person reads the prompt before typing
            os.write(master, answer)
            status = None
            while status is None and time.monotonic() < deadline:
                done, waited = os.waitpid(pid, os.WNOHANG)
                if done:
                    status = waited
                    break
                ready, _, _ = select.select([master], [], [], 0.2)
                if ready:
                    try:
                        os.read(master, 1024)  # drain the echo of what was typed
                    except OSError:
                        pass
            self.assertIsNotNone(status, "confirm_on_tty never returned")
        finally:
            try:
                os.kill(pid, 9)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
            os.close(master)
        code = os.waitstatus_to_exitcode(status)
        self.assertIn(code, (10, 11), "confirm_on_tty raised instead of asking")
        return code == 10, shown

    def test_yes_and_no_through_a_real_terminal(self) -> None:
        agreed, shown = self.ask_through_pty(b"y\r")
        self.assertTrue(agreed)
        self.assertIn(b"Proceed? [y/N]", shown)
        agreed, _ = self.ask_through_pty(b"n\r")
        self.assertFalse(agreed)

    def test_no_terminal_is_reported_with_a_generic_hint(self) -> None:
        with self.assertRaisesRegex(vs.SecretsError, "Set ASSUME_YES=1 to continue without the prompt"):
            vs.confirm_on_tty("x", tty_path="/nonexistent/tty")


class RenderedSecretTests(TempDirTest):
    def test_reads_data_and_string_data_of_secrets_only(self) -> None:
        manifest = "---\n".join(
            [
                secret_doc("helx-app-secrets", data={"SECRET_KEY": "k"}),
                secret_doc("helx-tls", string_data={"tls.crt": "PEM\n"}),
                yaml.safe_dump({"kind": "ConfigMap", "metadata": {"name": "x"}, "data": {"a": "b"}}),
            ]
        )
        self.assertEqual(
            vs.rendered_secrets(manifest),
            {"helx-app-secrets": {"SECRET_KEY": "k"}, "helx-tls": {"tls.crt": "PEM\n"}},
        )

    def test_generated_keys_are_grouped_per_secret_and_derived_keys_ignored(self) -> None:
        first = {"helx-db": {"postgres-password": "a", "uri": "x"}, "helx-tls": {"tls.key": "1", "ca.crt": "c"}}
        second = {"helx-db": {"postgres-password": "b", "uri": "y"}, "helx-tls": {"tls.key": "2", "ca.crt": "c"}}
        problems = vs.generated_keys(first, second, self.specs, "helx")
        self.assertEqual(len(problems), 2)
        self.assertIn("app.db.auth.postgresPassword", problems[0])
        self.assertNotIn("uri", problems[0])
        self.assertIn("hook.secret.values.tls.key", problems[1])
        self.assertIn("hook.secret.mode: values", problems[1])
        self.assertIn("hook.webhook.caBundle", problems[1])

    def test_identical_renders_report_nothing(self) -> None:
        same = {"helx-app-secrets": {"SECRET_KEY": "k"}}
        self.assertEqual(vs.generated_keys(same, same, self.specs, "helx"), [])


class HelmValuesTests(TempDirTest):
    def test_builds_nested_values_with_set_and_encoded_entries(self) -> None:
        secrets = {
            "helx-app-secrets": {"SECRET_KEY": "k", "PG": "p"},
            "helx-db": {"postgres-password": "admin", "uri": "postgresql://..."},
            "helx-tls": {"tls.crt": "CRT\n", "tls.key": "KEY\n", "ca.crt": "CA\n"},
        }
        tree = vs.helm_values(secrets, self.specs, "helx")
        self.assertEqual(tree["app"]["secret"]["values"], {"PG": "p", "SECRET_KEY": "k"})
        self.assertEqual(tree["app"]["db"]["auth"], {"postgresPassword": "admin"})
        self.assertEqual(tree["hook"]["secret"]["mode"], "values")
        self.assertEqual(tree["hook"]["secret"]["values"]["tls.key"], "KEY\n")
        self.assertEqual(tree["hook"]["webhook"]["caBundle"], b64("CA\n"))

    def test_yaml_keeps_strings_and_newlines_through_a_reload(self) -> None:
        tree = {"a": {"port": "8080", "flag": "False", "pem": "-----BEGIN-----\nabc\n-----END-----\n"}}
        text = vs.helm_values_yaml(tree, "here")
        self.assertIn("pem: |", text)
        self.assertEqual(yaml.safe_load(text), tree)

    def test_unknown_key_in_a_keys_secret_is_an_error(self) -> None:
        with self.assertRaisesRegex(vs.SecretsError, "has no place"):
            vs.helm_values({"helx-db": {"surprise": "x"}}, self.specs, "helx")

    def test_encoded_value_requires_its_key(self) -> None:
        with self.assertRaisesRegex(vs.SecretsError, "no key 'ca.crt'"):
            vs.helm_values({"helx-tls": {"tls.crt": "c", "tls.key": "k"}}, self.specs, "helx")


class FileTests(TempDirTest):
    def test_written_files_and_folders_are_owner_only(self) -> None:
        out = self.tmp / "out"
        reported: list[str] = []
        written = vs.write_secret_files(
            {"helx-app-secrets": {"SECRET_KEY": "k"}}, self.specs,
            release="helx", out=out, mount="helx", vault_path="dev/azure/x", report=reported.append,
        )
        self.assertEqual(written, [out / "app" / "helx-app-secrets.json"])
        self.assertEqual(json.loads(written[0].read_text()), {"SECRET_KEY": "k"})
        for path, mode in ((out, 0o700), (out / "app", 0o700), (written[0], 0o600)):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode, path)
        self.assertIn(
            f"vault kv put -mount=helx dev/azure/x/app/helx-app-secrets @{written[0]}",
            "\n".join(reported),
        )
        self.assertTrue(any("Skipped helx-db" in line for line in reported))

    def test_missing_vault_path_prints_runnable_commands_and_explains_it(self) -> None:
        reported: list[str] = []
        vs.write_secret_files(
            {"helx-app-secrets": {"K": "v"}}, self.specs,
            release="helx", out=self.tmp / "o", mount="helx", vault_path="", report=reported.append,
        )
        text = "\n".join(reported)
        self.assertIn("vault kv put -mount=helx $VAULT_PATH/app/helx-app-secrets @", text)
        self.assertIn("path prefix, on the helx mount, under which all of this namespace's secrets", text)
        self.assertIn("export VAULT_PATH=dev/azure/ai-sb-test", text)
        self.assertIn("make vault-secrets-upload VAULT_PATH=<prefix>", text)
        # The explanation comes before the commands, so they can be copied top to bottom.
        self.assertLess(text.index("export VAULT_PATH"), text.index("vault kv put"))
        self.assertNotIn("readable by you only", text)

    def test_given_vault_path_is_written_into_the_commands(self) -> None:
        reported: list[str] = []
        vs.write_secret_files(
            {"helx-app-secrets": {"K": "v"}}, self.specs,
            release="helx", out=self.tmp / "o", mount="helx", vault_path="dev/azure/x/",
            report=reported.append,
        )
        text = "\n".join(reported)
        self.assertIn("vault kv put -mount=helx dev/azure/x/app/helx-app-secrets @", text)
        self.assertIn("make vault-secrets-upload VAULT_PATH=dev/azure/x", text)
        self.assertNotIn("$VAULT_PATH", text)

    def test_round_trip_through_files(self) -> None:
        secrets = {"helx-app-secrets": {"K": "v"}, "helx-db": {"postgres-password": "p"}}
        vs.write_secret_files(
            secrets, self.specs, release="helx", out=self.tmp / "o",
            mount="helx", vault_path="", report=lambda _: None,
        )
        self.assertEqual(vs.read_secret_files(self.tmp / "o", self.specs, "helx", lambda _: None), secrets)

    def test_read_rejects_non_string_values(self) -> None:
        file = self.tmp / "o" / "app" / "helx-app-secrets.json"
        file.parent.mkdir(parents=True)
        file.write_text(json.dumps({"K": 1}))
        with self.assertRaisesRegex(vs.SecretsError, "string values"):
            vs.read_secret_files(self.tmp / "o", self.specs, "helx", lambda _: None)


class CommandTests(TempDirTest):
    def test_from_cluster_writes_found_secrets_and_skips_missing(self) -> None:
        live = {
            "helx-app-secrets": {"data": {"SECRET_KEY": b64("k")}},
            "helx-tls": {"data": {"tls.crt": b64("CRT\n")}},
        }
        calls: list[tuple[str, str, str]] = []

        def fake_kubectl(name: str, namespace: str, context: str):
            calls.append((name, namespace, context))
            return live.get(name)

        reported: list[str] = []
        args = vs.parse_args(["--map", str(self.tmp / "map.yaml"), "from-cluster", "--namespace", "ns", "--out", str(self.tmp / "o")])
        with patch.object(vs, "kubectl_secret", fake_kubectl):
            vs.command_from_cluster(args, self.specs, reported.append)
        self.assertEqual([c[1] for c in calls], ["ns", "ns", "ns"])
        self.assertEqual(json.loads((self.tmp / "o/hook/helx-tls.json").read_text()), {"tls.crt": "CRT\n"})
        self.assertFalse((self.tmp / "o/app/helx-db.json").exists())

    def run_from_cluster(self, *extra: str, live=None, confirm=None) -> list[str]:
        live = {"helx-app-secrets": {"data": {"SECRET_KEY": b64("new")}}} if live is None else live
        reported: list[str] = []
        args = vs.parse_args(["--map", str(self.tmp / "map.yaml"), "from-cluster",
                              "--namespace", "ns", "--out", str(self.tmp / "o"), *extra])

        def refuse(_: str) -> bool:
            raise AssertionError("asked when it should not have")

        with patch.object(vs, "kubectl_secret", lambda name, *_: live.get(name)), \
                patch.object(vs, "confirm_on_tty", confirm or refuse):
            vs.command_from_cluster(args, self.specs, reported.append)
        return reported

    def test_from_cluster_does_not_ask_when_no_file_exists(self) -> None:
        self.run_from_cluster()
        file = self.tmp / "o/app/helx-app-secrets.json"
        self.assertEqual(json.loads(file.read_text()), {"SECRET_KEY": "new"})

    def test_from_cluster_asks_before_overwriting_and_no_changes_nothing(self) -> None:
        file = self.tmp / "o/app/helx-app-secrets.json"
        file.parent.mkdir(parents=True)
        file.write_text('{"SECRET_KEY": "old"}')
        other = self.tmp / "o/app/helx-db.json"  # not in the cluster, so never at risk
        other.write_text("{}")
        asked: list[str] = []
        with self.assertRaisesRegex(vs.SecretsError, "Cancelled; no files were changed"):
            reported = self.run_from_cluster(confirm=lambda prompt: asked.append(prompt) or False)
        self.assertEqual(len(asked), 1)
        self.assertEqual(file.read_text(), '{"SECRET_KEY": "old"}')

    def test_from_cluster_lists_only_the_files_it_would_overwrite(self) -> None:
        file = self.tmp / "o/app/helx-app-secrets.json"
        file.parent.mkdir(parents=True)
        file.write_text("{}")
        (self.tmp / "o/app/helx-db.json").write_text("{}")
        reported = self.run_from_cluster(confirm=lambda _: True)
        listed = [line.strip() for line in reported if line.startswith("  ")]
        self.assertIn(str(file), listed)
        self.assertNotIn(str(self.tmp / "o/app/helx-db.json"), listed)
        self.assertEqual(json.loads(file.read_text()), {"SECRET_KEY": "new"})

    def test_from_cluster_assume_yes_overwrites_without_asking(self) -> None:
        file = self.tmp / "o/app/helx-app-secrets.json"
        file.parent.mkdir(parents=True)
        file.write_text("{}")
        reported = self.run_from_cluster("--assume-yes")
        self.assertTrue(any("overwriting without asking" in line for line in reported))
        self.assertEqual(json.loads(file.read_text()), {"SECRET_KEY": "new"})

    def test_to_vault_refuses_to_write_when_a_value_is_generated(self) -> None:
        renders = iter([secret_doc("helx-db", data={"postgres-password": "a"}),
                        secret_doc("helx-db", data={"postgres-password": "b"})])
        (self.tmp / "v.yaml").write_text("{}")
        args = vs.parse_args([
            "--map", str(self.tmp / "map.yaml"), "to-vault", "--chart", "chart", "--namespace", "ns",
            "--values-list", str(self.tmp / "none.env"), "--values", str(self.tmp / "v.yaml"),
            "--out", str(self.tmp / "o"),
        ])
        def refuse(_: str) -> bool:
            raise AssertionError("asked before finding the generated value")

        with patch.object(vs, "helm_template", lambda *a: next(renders)), \
                patch.object(vs, "confirm_on_tty", refuse):
            with self.assertRaisesRegex(vs.SecretsError, "app.db.auth.postgresPassword"):
                vs.command_to_vault(args, self.specs, lambda _: None)
        self.assertFalse((self.tmp / "o").exists())

    def test_to_vault_requires_a_namespace_and_never_renders_without_one(self) -> None:
        (self.tmp / "v.yaml").write_text("{}")
        args = vs.parse_args([
            "--map", str(self.tmp / "map.yaml"), "to-vault", "--chart", "chart",
            "--values-list", str(self.tmp / "none.env"), "--values", str(self.tmp / "v.yaml"),
            "--out", str(self.tmp / "o"),
        ])

        def no_render(*_):
            raise AssertionError("rendered without a namespace")

        with patch.object(vs, "helm_template", no_render):
            with self.assertRaisesRegex(vs.SecretsError, "(?s)NAMESPACE is required.*not taken from your kubectl context"):
                vs.command_to_vault(args, self.specs, lambda _: None)
        self.assertFalse((self.tmp / "o").exists())

    def run_to_vault(self, *extra: str, list_body: str | None = None, answer: bool = True,
                     assume_yes: bool = False):
        """Run to-vault with a fixed render; return what it printed and the prompts it showed."""
        render = secret_doc("helx-app-secrets", data={"K": "new"}) + "---\n" + \
            secret_doc("helx-db", data={"postgres-password": "p"})
        (self.tmp / "v.yaml").write_text("{}")
        listing = self.tmp / "list.env"
        if list_body is not None:
            listing.write_text(list_body)
        argv = ["--map", str(self.tmp / "map.yaml"), "to-vault", "--chart", "chart.tgz",
                "--namespace", "ns", "--values-list", str(listing),
                "--values", str(self.tmp / "v.yaml"), "--out", str(self.tmp / "o"), *extra]
        if assume_yes:
            argv.append("--assume-yes")
        reported: list[str] = []
        asked: list[str] = []
        with patch.object(vs, "helm_template", lambda *a: render), \
                patch.object(vs, "confirm_on_tty", lambda prompt: asked.append(prompt) or answer):
            vs.command_to_vault(vs.parse_args(argv), self.specs, reported.append)
        return "\n".join(reported), asked

    def summary_of(self, text: str) -> str:
        """Everything printed before writing starts: the summary itself."""
        lines = []
        for line in text.splitlines():
            if line.startswith(("Skipped ", "Wrote ", "ASSUME_YES")):
                break
            lines.append(line)
        return "\n".join(lines)

    def test_to_vault_asks_once_with_a_helm_deploy_style_summary(self) -> None:
        text, asked = self.run_to_vault("--out-origin", "file")
        self.assertEqual(asked, ["Proceed? [y/N] "])
        self.assertEqual(
            self.summary_of(text).splitlines(),
            [
                "Rendering chart.tgz into one JSON file per Secret",
                "  release   helx",
                "  namespace ns",
                f"  values    {self.tmp / 'v.yaml'}",
                f"  output    {self.tmp / 'o'} (the default VAULT_SECRETS_DIR)",
                "  files     2 JSON files",
            ],
        )

    def test_to_vault_says_when_the_output_folder_was_set_by_the_user(self) -> None:
        text, _ = self.run_to_vault("--out-origin", "command line")
        self.assertIn("(VAULT_SECRETS_DIR, set on the command line)", text)

    def test_to_vault_mentions_the_list_file_only_when_it_lists_files(self) -> None:
        (self.tmp / "env.yaml").write_text("{}")
        text, _ = self.run_to_vault(list_body=f"{self.tmp / 'env.yaml'}\nmissing.yaml\n")
        summary = self.summary_of(text).splitlines()
        self.assertIn(f"  list      {self.tmp / 'list.env'}", summary)
        # The list's files come first, then VALUES, continuing the one "values" field.
        start = summary.index(f"  values    {self.tmp / 'env.yaml'}")
        self.assertEqual(summary[start + 1], f"            {self.tmp / 'v.yaml'}")
        # A missing entry is warned about before the summary, as helm-deploy does.
        self.assertTrue(summary[0].startswith(f"WARNING: {self.tmp / 'list.env'} line 2 names missing.yaml"))
        self.assertEqual(summary[1], "         That file's values will not be rendered.")
        text, _ = self.run_to_vault(list_body="# nothing listed\n")
        self.assertFalse(any(line.startswith("  list") for line in self.summary_of(text).splitlines()))

    def test_to_vault_lists_files_it_would_overwrite(self) -> None:
        existing = self.tmp / "o/app/helx-app-secrets.json"
        existing.parent.mkdir(parents=True)
        existing.write_text('{"K": "old"}')
        text, asked = self.run_to_vault()
        self.assertEqual(len(asked), 1)
        summary = self.summary_of(text).splitlines()
        self.assertEqual(summary[-1], f"  overwrite {existing}")
        self.assertNotIn(str(self.tmp / "o/app/helx-db.json"), self.summary_of(text))
        self.assertEqual(json.loads(existing.read_text()), {"K": "new"})

    def test_to_vault_answer_no_changes_nothing(self) -> None:
        existing = self.tmp / "o/app/helx-app-secrets.json"
        existing.parent.mkdir(parents=True)
        existing.write_text('{"K": "old"}')
        with self.assertRaisesRegex(vs.SecretsError, "Cancelled; no files were changed"):
            self.run_to_vault(answer=False)
        self.assertEqual(existing.read_text(), '{"K": "old"}')
        self.assertFalse((self.tmp / "o/app/helx-db.json").exists())

    def test_to_vault_assume_yes_shows_the_summary_without_asking(self) -> None:
        text, asked = self.run_to_vault(assume_yes=True)
        self.assertEqual(asked, [])
        self.assertIn("  files     2 JSON files", text)
        self.assertIn("ASSUME_YES is set; continuing without asking.", text)

    def run_to_helm(self, *extra: str, answer: bool = True) -> tuple[Path, list[str], list[str]]:
        vs.write_secret_files({"helx-app-secrets": {"K": "v"}}, self.specs, release="helx",
                              out=self.tmp / "o", mount="helx", vault_path="", report=lambda _: None)
        out_file = self.tmp / "o" / "secrets.yaml"
        args = vs.parse_args(["--map", str(self.tmp / "map.yaml"), "to-helm",
                              "--in", str(self.tmp / "o"), "--out-file", str(out_file), *extra])
        reported: list[str] = []
        asked: list[str] = []
        with patch.object(vs, "confirm_on_tty", lambda prompt: asked.append(prompt) or answer):
            vs.command_to_helm(args, self.specs, reported.append)
        return out_file, asked, reported

    def test_to_helm_does_not_ask_when_the_file_is_new(self) -> None:
        out_file, asked, reported = self.run_to_helm()
        self.assertEqual(asked, [])
        self.assertFalse(any("LOCAL_VALUES_FILE" in line for line in reported))
        self.assertTrue(out_file.exists())

    def test_to_helm_asks_before_overwriting_and_no_keeps_the_file(self) -> None:
        out_file = self.tmp / "o" / "secrets.yaml"
        out_file.parent.mkdir(parents=True)
        out_file.write_text("old: true\n")
        with self.assertRaisesRegex(vs.SecretsError, "Cancelled; no files were changed"):
            self.run_to_helm(answer=False)
        self.assertEqual(out_file.read_text(), "old: true\n")
        _, asked, reported = self.run_to_helm(answer=True)
        self.assertEqual(asked, ["Overwrite it? [y/N] "])
        self.assertIn("This file already exists and would be overwritten:", reported)
        self.assertEqual(yaml.safe_load(out_file.read_text()), {"app": {"secret": {"values": {"K": "v"}}}})

    def test_to_helm_assume_yes_overwrites_without_asking(self) -> None:
        out_file = self.tmp / "o" / "secrets.yaml"
        out_file.parent.mkdir(parents=True)
        out_file.write_text("old: true\n")
        _, asked, reported = self.run_to_helm("--assume-yes")
        self.assertEqual(asked, [])
        self.assertIn("ASSUME_YES is set; overwriting without asking.", reported)

    def test_to_helm_writes_an_owner_only_yaml(self) -> None:
        vs.write_secret_files({"helx-app-secrets": {"K": "v"}}, self.specs, release="helx",
                              out=self.tmp / "o", mount="helx", vault_path="", report=lambda _: None)
        out_file = self.tmp / "o" / "secrets.yaml"
        args = vs.parse_args(["--map", str(self.tmp / "map.yaml"), "to-helm",
                              "--in", str(self.tmp / "o"), "--out-file", str(out_file)])
        vs.command_to_helm(args, self.specs, lambda _: None)
        self.assertEqual(yaml.safe_load(out_file.read_text()), {"app": {"secret": {"values": {"K": "v"}}}})
        self.assertEqual(stat.S_IMODE(out_file.stat().st_mode), 0o600)


class UserPathTests(unittest.TestCase):
    """zsh passes `VAULT_SECRETS_YAML=~/x` through with the ~ unexpanded."""

    def test_leading_tilde_in_every_path_argument_is_expanded(self) -> None:
        with patch.dict(vs.os.environ, {"HOME": "/home/someone"}):
            cases = {
                ("to-helm", "--in", "~/in", "--out-file", "~/out/secrets.yaml"): {
                    "input": "/home/someone/in", "out_file": "/home/someone/out/secrets.yaml"},
                ("to-vault", "--chart", "c", "--values-list", "~/list.env", "--out", "~/o"): {
                    "values_list": "/home/someone/list.env", "out": "/home/someone/o"},
                ("from-cluster", "--out", "~/o"): {"out": "/home/someone/o"},
                ("upload", "--in", "~/o"): {"input": "/home/someone/o"},
            }
            for argv, expected in cases.items():
                with self.subTest(command=argv[0]):
                    args = vs.parse_args(list(argv))
                    self.assertEqual({k: getattr(args, k) for k in expected}, expected)

    def test_relative_and_absolute_paths_are_unchanged(self) -> None:
        args = vs.parse_args(["to-helm", "--in", "dist/vault-secrets", "--out-file", "/abs/secrets.yaml"])
        self.assertEqual((args.input, args.out_file), ("dist/vault-secrets", "/abs/secrets.yaml"))


class UploadTests(TempDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.out = self.tmp / "o"
        vs.write_secret_files(
            {"helx-app-secrets": {"K": "v"}, "helx-db": {"postgres-password": "p"}}, self.specs,
            release="helx", out=self.out, mount="helx", vault_path="", report=lambda _: None,
        )

    def args(self, *extra: str):
        return vs.parse_args(["--map", str(self.tmp / "map.yaml"), "upload", "--in", str(self.out), *extra])

    def run_upload(self, *extra: str, environ=None, confirm=None, put=None) -> list[str]:
        reported: list[str] = []
        environ = {"VAULT_ADDR": "https://vault.example.org"} if environ is None else environ
        with patch.dict(vs.os.environ, environ, clear=True), \
                patch.object(vs.shutil, "which", lambda _: "/usr/bin/vault"), \
                patch.object(vs, "confirm_on_tty", confirm or (lambda _: True)), \
                patch.object(vs, "vault_put", put or (lambda *a: None)):
            vs.command_upload(self.args(*extra), self.specs, reported.append)
        return reported

    def test_requires_vault_path_and_explains_it(self) -> None:
        with self.assertRaisesRegex(vs.SecretsError, "path prefix.*under which all of this namespace"):
            self.run_upload()

    def test_requires_vault_addr(self) -> None:
        with self.assertRaisesRegex(vs.SecretsError, "VAULT_ADDR is not set"):
            self.run_upload("--vault-path", "dev/azure/x", environ={})

    def test_lists_entries_asks_and_writes_each_file(self) -> None:
        puts: list[tuple] = []
        asked: list[str] = []
        reported = self.run_upload(
            "--vault-path", "dev/azure/x",
            confirm=lambda prompt: asked.append(prompt) or True,
            put=lambda *a: puts.append(a),
        )
        self.assertEqual(len(asked), 1)
        self.assertEqual(
            puts,
            [
                ("helx", "dev/azure/x/app/helx-app-secrets", self.out / "app" / "helx-app-secrets.json"),
                ("helx", "dev/azure/x/app/helx-db", self.out / "app" / "helx-db.json"),
            ],
        )
        text = "\n".join(reported)
        self.assertIn("Vault: https://vault.example.org", text)
        self.assertIn("Skipped helx-tls", text)

    def test_answer_no_writes_nothing_and_assume_yes_does_not_ask(self) -> None:
        puts: list[tuple] = []
        with self.assertRaisesRegex(vs.SecretsError, "Cancelled"):
            self.run_upload("--vault-path", "p", confirm=lambda _: False, put=lambda *a: puts.append(a))
        self.assertEqual(puts, [])

        def refuse(_: str) -> bool:
            raise AssertionError("asked despite --assume-yes")

        self.run_upload("--vault-path", "p", "--assume-yes", confirm=refuse, put=lambda *a: puts.append(a))
        self.assertEqual(len(puts), 2)

    def test_stops_at_the_first_failure_and_says_what_was_written(self) -> None:
        def put(mount: str, path: str, file: Path) -> None:
            if path.endswith("helx-db"):
                raise vs.SecretsError("vault failed:\npermission denied")

        with self.assertRaises(vs.SecretsError) as caught:
            self.run_upload("--vault-path", "p", "--assume-yes", put=put)
        message = str(caught.exception)
        self.assertIn("Written: p/app/helx-app-secrets", message)
        self.assertIn("Not written: p/app/helx-db", message)
        self.assertIn("permission denied", message)

    def test_runs_the_real_vault_command_line(self) -> None:
        """Through main(), with a fake `vault` on PATH that records its arguments."""
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        log = self.tmp / "vault.log"
        fake = bin_dir / "vault"
        fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
        fake.chmod(0o755)
        environ = {"PATH": f"{bin_dir}:/usr/bin:/bin", "VAULT_ADDR": "https://vault.example.org"}
        with patch.dict(vs.os.environ, environ, clear=True), \
                contextlib.redirect_stderr(io.StringIO()):
            code = vs.main([
                "--map", str(self.tmp / "map.yaml"), "upload", "--in", str(self.out),
                "--vault-path", "dev/azure/x", "--assume-yes",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(
            log.read_text().splitlines(),
            [
                f"kv put -mount=helx dev/azure/x/app/helx-app-secrets @{self.out}/app/helx-app-secrets.json",
                f"kv put -mount=helx dev/azure/x/app/helx-db @{self.out}/app/helx-db.json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
