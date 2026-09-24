package main

import (
	"encoding/json"
	"testing"

	jsonpatchapply "github.com/evanphx/json-patch"
	admissionv1 "k8s.io/api/admission/v1"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
)

func findMount(mounts []corev1.VolumeMount, path string) *corev1.VolumeMount {
	for i := range mounts {
		if mounts[i].MountPath == path {
			return &mounts[i]
		}
	}
	return nil
}

func findContainer(cs []corev1.Container, name string) *corev1.Container {
	for i := range cs {
		if cs[i].Name == name {
			return &cs[i]
		}
	}
	return nil
}

func findVolume(vs []corev1.Volume, name string) *corev1.Volume {
	for i := range vs {
		if vs[i].Name == name {
			return &vs[i]
		}
	}
	return nil
}

func TestGetNSLCDVolumesMountsAndSidecar(t *testing.T) {
	vols, appMounts, sidecar := getNSLCDVolumesMountsAndSidecar("um-nslcd-config", "reg/nslcd:1")

	// --- volumes: config ConfigMap + shared socket emptyDir ---
	cfg := findVolume(vols, nslcdConfigVol)
	if cfg == nil || cfg.ConfigMap == nil || cfg.ConfigMap.Name != "um-nslcd-config" {
		t.Fatalf("expected %s ConfigMap volume named um-nslcd-config, got %+v", nslcdConfigVol, cfg)
	}
	sock := findVolume(vols, nslcdSocketVol)
	if sock == nil || sock.EmptyDir == nil {
		t.Fatalf("expected %s emptyDir volume, got %+v", nslcdSocketVol, sock)
	}

	// --- app mounts: nsswitch + shared socket, and NOT the retired libnss-ldap files ---
	if m := findMount(appMounts, "/etc/nsswitch.conf"); m == nil || m.SubPath != "nsswitch.conf" {
		t.Errorf("app should mount nsswitch.conf, got %+v", m)
	}
	if m := findMount(appMounts, nslcdSocketDir); m == nil || m.Name != nslcdSocketVol {
		t.Errorf("app should mount the shared nslcd socket dir, got %+v", m)
	}
	for _, gone := range []string{"/etc/libnss-ldap.conf", "/etc/ldap.conf"} {
		if m := findMount(appMounts, gone); m != nil {
			t.Errorf("retired libnss-ldap mount %s must not be injected, got %+v", gone, m)
		}
	}

	// --- sidecar: image, nslcd.conf + socket, but NOT the app's nsswitch mount ---
	if sidecar.Name != "nslcd" || sidecar.Image != "reg/nslcd:1" {
		t.Errorf("unexpected sidecar name/image: %s / %s", sidecar.Name, sidecar.Image)
	}
	if m := findMount(sidecar.VolumeMounts, "/etc/nslcd.conf"); m == nil || m.SubPath != "nslcd.conf" {
		t.Errorf("sidecar should mount nslcd.conf, got %+v", m)
	}
	if m := findMount(sidecar.VolumeMounts, nslcdSocketDir); m == nil {
		t.Errorf("sidecar should mount the shared socket dir")
	}
	if m := findMount(sidecar.VolumeMounts, "/etc/nsswitch.conf"); m != nil {
		t.Errorf("sidecar must not receive the app nsswitch mount, got %+v", m)
	}
	// --- native sidecar: restartPolicy=Always + startupProbe on the socket ---
	if sidecar.RestartPolicy == nil || *sidecar.RestartPolicy != corev1.ContainerRestartPolicyAlways {
		t.Errorf("sidecar must be a native sidecar (restartPolicy=Always), got %v", sidecar.RestartPolicy)
	}
	if sidecar.StartupProbe == nil || sidecar.StartupProbe.Exec == nil {
		t.Errorf("sidecar should gate app start with a startupProbe on the socket")
	}
	// --- resources set (avoids ResourceQuota rejection) ---
	if sidecar.Resources.Requests.Cpu().IsZero() || sidecar.Resources.Requests.Memory().IsZero() {
		t.Errorf("sidecar should set cpu/memory requests, got %+v", sidecar.Resources.Requests)
	}
	// --- restricted PSS hardening ---
	sc := sidecar.SecurityContext
	if sc == nil || sc.AllowPrivilegeEscalation == nil || *sc.AllowPrivilegeEscalation {
		t.Errorf("sidecar should set allowPrivilegeEscalation=false")
	}
	if sc == nil || sc.RunAsNonRoot == nil || !*sc.RunAsNonRoot {
		t.Errorf("sidecar should set runAsNonRoot=true")
	}
	if sc == nil || sc.Capabilities == nil || len(sc.Capabilities.Drop) == 0 || sc.Capabilities.Drop[0] != "ALL" {
		t.Errorf("sidecar should drop ALL capabilities")
	}
	if sc == nil || sc.SeccompProfile == nil || sc.SeccompProfile.Type != corev1.SeccompProfileTypeRuntimeDefault {
		t.Errorf("sidecar should set seccompProfile=RuntimeDefault")
	}
}

// TestAddNSLCDConfigToProfileEmptyImageGuard: with no sidecar image the webhook
// must NOT inject (an image:"" container would fail pod creation).
func TestAddNSLCDConfigToProfileEmptyImageGuard(t *testing.T) {
	out := addNSLCDConfigToProfile("um-nslcd-config", "", ProfileResources{})
	if len(out.InitContainers) != 0 || len(out.Volumes) != 0 || len(out.VolumeMounts) != 0 {
		t.Errorf("empty sidecar image must skip injection, got initContainers=%d volumes=%d mounts=%d",
			len(out.InitContainers), len(out.Volumes), len(out.VolumeMounts))
	}
}

// TestCalculatePatchInjectsNSLCDSidecar exercises the real patch path: build a
// Deployment, run calculatePatch, apply the resulting JSONPatch, and assert the
// final pod has the app container mounts + the nslcd sidecar + shared volumes.
func TestCalculatePatchInjectsNSLCDSidecar(t *testing.T) {
	dep := appsv1.Deployment{
		Spec: appsv1.DeploymentSpec{
			Template: corev1.PodTemplateSpec{
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{{Name: "app", Image: "app:1"}},
				},
			},
		},
	}
	raw, err := json.Marshal(&dep)
	if err != nil {
		t.Fatal(err)
	}
	ar := &admissionv1.AdmissionReview{
		Request: &admissionv1.AdmissionRequest{Object: runtime.RawExtension{Raw: raw}},
	}

	resources := addNSLCDConfigToProfile("um-nslcd-config", "reg/nslcd:1", ProfileResources{})
	patchBytes, err := calculatePatch(ar, resources, map[string]bool{})
	if err != nil {
		t.Fatalf("calculatePatch: %v", err)
	}

	patch, err := jsonpatchapply.DecodePatch(patchBytes)
	if err != nil {
		t.Fatalf("decode patch: %v", err)
	}
	modified, err := patch.Apply(raw)
	if err != nil {
		t.Fatalf("apply patch: %v", err)
	}

	var out appsv1.Deployment
	if err := json.Unmarshal(modified, &out); err != nil {
		t.Fatal(err)
	}
	spec := out.Spec.Template.Spec

	// app container present and got the nsswitch + socket mounts
	app := findContainer(spec.Containers, "app")
	if app == nil {
		t.Fatal("app container missing after patch")
	}
	if findMount(app.VolumeMounts, "/etc/nsswitch.conf") == nil || findMount(app.VolumeMounts, nslcdSocketDir) == nil {
		t.Errorf("app container should have nsswitch + socket mounts, got %+v", app.VolumeMounts)
	}

	// nslcd native sidecar injected into initContainers (NOT app containers),
	// and it did NOT inherit the app nsswitch mount
	if findContainer(spec.Containers, "nslcd") != nil {
		t.Error("nslcd must be a native sidecar in initContainers, not a regular container")
	}
	side := findContainer(spec.InitContainers, "nslcd")
	if side == nil {
		t.Fatal("nslcd native sidecar was not injected into initContainers")
	}
	if side.RestartPolicy == nil || *side.RestartPolicy != corev1.ContainerRestartPolicyAlways {
		t.Error("injected nslcd must have restartPolicy=Always (native sidecar)")
	}
	if findMount(side.VolumeMounts, "/etc/nsswitch.conf") != nil {
		t.Errorf("sidecar must not inherit app nsswitch mount")
	}
	if findMount(side.VolumeMounts, "/etc/nslcd.conf") == nil {
		t.Errorf("sidecar should mount nslcd.conf")
	}

	// shared volumes present
	if findVolume(spec.Volumes, nslcdConfigVol) == nil || findVolume(spec.Volumes, nslcdSocketVol) == nil {
		t.Errorf("pod should have nslcd config + socket volumes, got %+v", spec.Volumes)
	}

	// idempotency marker stamped so a re-admission (Deployment update) no-ops
	if out.Spec.Template.ObjectMeta.Annotations[mutatedAnnotation] != "true" {
		t.Errorf("expected idempotency marker %q on the mutated pod template, got %+v",
			mutatedAnnotation, out.Spec.Template.ObjectMeta.Annotations)
	}
}
