import json
import os
from types import SimpleNamespace
from unittest import TestCase, mock

from tycho.config import Config
from tycho.context import TychoContext
from tycho.kube import KubernetesCompute
from tycho.model import System, Volumes


def _pvc(name):
    return SimpleNamespace(metadata=SimpleNamespace(name=name))


def _compute_with_pvcs(*names):
    """ A KubernetesCompute with a stub API, so no cluster or kubeconfig is needed. """
    compute = KubernetesCompute.__new__(KubernetesCompute)
    compute.api = mock.Mock()
    compute.api.list_namespaced_persistent_volume_claim.return_value = SimpleNamespace(
        items=[_pvc(name) for name in names])
    return compute


class VolumeKindTests(TestCase):
    """ Volumes.process_volumes records which scheme declared each volume. """

    def test_kind_per_scheme_including_repeat_references(self):
        volumes = Volumes("x", [
            {"name": "app", "volumes": [
                "pvc://stdnfs/home/alice:/home/alice",
                "pvc://stdnfs/shared:/home/shared",
                "emptyDir://scratch:/scratch",
                "emptyDirSeeded://etc-passwd/passwd:/etc/passwd",
            ]},
            {"name": "sidecar", "volumes": [
                "emptyDir://scratch:/scratch",
            ]},
        ]).process_volumes()

        self.assertEqual(
            [(v["container_name"], v["volume_name"], v["kind"]) for v in volumes],
            [("app", "stdnfs", "pvc"),
             ("app", "stdnfs", "pvc"),
             ("app", "scratch", "emptyDir"),
             ("app", "etc-passwd", "emptyDir"),
             ("sidecar", "scratch", "emptyDir")])
        # The repeat references are why kind is needed: both have neither name set.
        self.assertIsNone(volumes[1]["pvc_name"])
        self.assertIsNone(volumes[4]["empty_dir_name"])


class CheckVolumesTests(TestCase):
    """ check_volumes drops only PVC volumes whose PVC is missing. """

    def test_emptydirs_are_never_dropped(self):
        volumes = Volumes("x", [{"name": "pgadmin", "volumes": [
            "emptyDir://pgadmin-distro-config:/pgadmin-distro-config",
            "emptyDir://pgadmin-var-lib:/var/lib/pgadmin",
            "emptyDirSeeded://etc-passwd/passwd:/etc/passwd",
        ]}]).process_volumes()

        self.assertEqual(_compute_with_pvcs().check_volumes(volumes, "ns"), [])

    def test_missing_pvcs_are_still_dropped(self):
        volumes = Volumes("x", [{"name": "app", "volumes": [
            "pvc://stdnfs/home/alice:/home/alice",
            "pvc://present/data:/data",
            "pvc://absent/data:/other",
            "emptyDir://scratch:/scratch",
        ]}]).process_volumes()

        dropped = _compute_with_pvcs("present").check_volumes(volumes, "ns")

        self.assertEqual([volumes[i]["volume_name"] for i in dropped], ["absent"])

    def test_volume_without_kind_is_checked_as_a_pvc(self):
        legacy = [{"container_name": "app", "pvc_name": "gone", "volume_name": "gone",
                   "path": "/gone", "subpath": "", "empty_dir_name": None, "needs_seed": False}]

        self.assertEqual(_compute_with_pvcs().check_volumes(legacy, "ns"), [0])


class PgadminSpecRenderTests(TestCase):
    """ The cdsr-staging pgadmin spec keeps its emptyDir volumes from parse through render. """

    SPEC = {
        "version": "3.6",
        "services": {"pgadmin": {
            "image": "example.invalid/pgadmin4:test",
            "ports": ["8080:8080"],
            "volumes": [
                "emptyDir://pgadmin-distro-config:/pgadmin-distro-config",
                "emptyDir://pgadmin-var-lib:/var/lib/pgadmin",
                "emptyDir://pgadmin-tmp:/tmp",
            ],
        }},
        "security_context": {"readOnlyRootFilesystem": True},
    }

    @mock.patch.dict(os.environ, {"DEV_PHASE": "test"})
    def test_emptydir_volumes_and_mounts_survive_check_and_render(self):
        system = System.parse(Config(), "pgadmin", json.dumps({"username": "alice"}),
                              json.loads(json.dumps(self.SPEC)), "default", env={}, services={})

        dropped = set(_compute_with_pvcs().check_volumes(system.volumes, "ns"))
        system.volumes = [v for i, v in enumerate(system.volumes) if i not in dropped]
        manifests = [m for m in system.render("pod.yaml") if m]

        # pod.yaml renders a Pod; KubernetesCompute.start wraps its spec in the Deployment.
        pod_spec = next(m for m in manifests if m.get("kind") == "Pod")["spec"]
        volumes = {v["name"]: v for v in pod_spec["volumes"]}
        mounts = {m["name"]: m["mountPath"] for m in pod_spec["containers"][0]["volumeMounts"]}
        for name, path in [("pgadmin-distro-config", "/pgadmin-distro-config"),
                           ("pgadmin-var-lib", "/var/lib/pgadmin"),
                           ("pgadmin-tmp", "/tmp")]:
            self.assertEqual(volumes[name].get("emptyDir"), {})
            self.assertEqual(mounts[name], path)


class SeededSpecRenderTests(TestCase):
    """ An emptyDirSeeded volume (jupyter/rstudio /etc/passwd) survives the
        check and still gets its seed-volumes init container. """

    SPEC = {
        "version": "3.6",
        "services": {"jupyter": {
            "image": "example.invalid/jupyter:test",
            "ports": ["8888:8888"],
            "volumes": ["emptyDirSeeded://etc-passwd/passwd:/etc/passwd"],
        }},
    }

    @mock.patch.dict(os.environ, {"DEV_PHASE": "test"})
    def test_seed_volume_and_init_container_survive_check_and_render(self):
        system = System.parse(Config(), "jupyter", json.dumps({"username": "alice"}),
                              json.loads(json.dumps(self.SPEC)), "default", env={}, services={})

        dropped = set(_compute_with_pvcs().check_volumes(system.volumes, "ns"))
        system.volumes = [v for i, v in enumerate(system.volumes) if i not in dropped]
        pod_spec = next(m for m in system.render("pod.yaml") if m and m.get("kind") == "Pod")["spec"]

        self.assertEqual({v["name"]: v.get("emptyDir") for v in pod_spec["volumes"]}.get("etc-passwd"), {})
        mount = next(m for m in pod_spec["containers"][0]["volumeMounts"] if m["name"] == "etc-passwd")
        self.assertEqual((mount["mountPath"], mount["subPath"]), ("/etc/passwd", "passwd"))
        seed = next(c for c in pod_spec["initContainers"] if c["name"] == "seed-volumes")
        self.assertEqual(seed["image"], "example.invalid/jupyter:test")
        self.assertIn('cp -a "/etc/passwd.default"', seed["args"][0])


class MergeSecurityContextTests(TestCase):
    """ TychoContext.start keeps the spec's own security_context, with the
        registry entry's securityContext winning where both set a key. """

    merge = staticmethod(TychoContext.merge_security_context)

    def test_spec_setting_survives_when_registry_has_none(self):
        self.assertEqual(self.merge({"readOnlyRootFilesystem": True}, None),
                         {"readOnlyRootFilesystem": True})

    def test_registry_setting_applies_when_spec_has_none(self):
        self.assertEqual(self.merge(None, {"runAsUser": 1000}), {"runAsUser": 1000})

    def test_registry_wins_on_conflict_and_both_sides_kept(self):
        merged = self.merge({"readOnlyRootFilesystem": True, "fsGroup": 0},
                            {"fsGroup": 1000, "runAsUser": 1000})
        self.assertEqual(merged, {"readOnlyRootFilesystem": True, "fsGroup": 1000, "runAsUser": 1000})

    def test_nothing_set_is_empty(self):
        self.assertEqual(self.merge(None, None), {})

    def test_inputs_unchanged_and_repeat_launch_is_stable(self):
        spec_sc = {"readOnlyRootFilesystem": True}
        registry_sc = {"runAsUser": 1000}
        once = self.merge(spec_sc, registry_sc)
        # get_spec returns its cached spec, so a second launch merges the
        # already-merged result again.
        twice = self.merge(once, registry_sc)
        self.assertEqual(once, twice)
        self.assertEqual(spec_sc, {"readOnlyRootFilesystem": True})
        self.assertEqual(registry_sc, {"runAsUser": 1000})
        self.assertIsNot(once, spec_sc)


class SpecSecurityContextRenderTests(TestCase):
    """ A spec-level readOnlyRootFilesystem, merged as TychoContext.start does,
        reaches the rendered container; an empty TYCHO_APP_FS_GROUP renders no
        pod fsGroup, while the chart's default of 0 renders fsGroup: 0. """

    SPEC = {
        "version": "3.6",
        "services": {"filebrowser": {
            "image": "example.invalid/filebrowser:test",
            "ports": ["8080:8080"],
            "volumes": ["emptyDir://filebrowser-tmp:/tmp"],
        }},
        "security_context": {"readOnlyRootFilesystem": True},
    }

    def _render(self, fs_group_env):
        spec = json.loads(json.dumps(self.SPEC))
        spec["security_context"] = TychoContext.merge_security_context(spec.get("security_context"), None)
        with mock.patch.dict(os.environ, {"DEV_PHASE": "test", "TYCHO_APP_FS_GROUP": fs_group_env}):
            system = System.parse(Config(), "filebrowser", json.dumps({"username": "alice"}),
                                  spec, "default", env={}, services={})
            return next(m for m in system.render("pod.yaml") if m and m.get("kind") == "Pod")["spec"]

    def test_read_only_root_filesystem_rendered_from_spec(self):
        pod_spec = self._render("")
        self.assertIs(pod_spec["containers"][0]["securityContext"].get("readOnlyRootFilesystem"), True)

    def test_empty_fs_group_env_renders_no_fs_group(self):
        self.assertNotIn("fsGroup", (self._render("").get("securityContext") or {}))

    def test_default_fs_group_env_renders_root_fs_group(self):
        self.assertEqual(self._render("0")["securityContext"].get("fsGroup"), 0)
