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

func int64Ptr(v int64) *int64 { return &v }

// launcherContainerSC is the hardening Tycho renders for an app container
// under UNCDSR-182, which the mutator must keep.
func launcherContainerSC() *corev1.SecurityContext {
	return &corev1.SecurityContext{
		ReadOnlyRootFilesystem:   boolPtr(true),
		RunAsNonRoot:             boolPtr(true),
		AllowPrivilegeEscalation: boolPtr(false),
		Capabilities:             &corev1.Capabilities{Drop: []corev1.Capability{"ALL"}},
		SeccompProfile:           &corev1.SeccompProfile{Type: corev1.SeccompProfileTypeRuntimeDefault},
	}
}

// identitySCs is what constructSecurityContexts builds for a user.
func identitySCs(t *testing.T) (*corev1.PodSecurityContext, *corev1.SecurityContext) {
	t.Helper()
	pod, ctr, err := constructSecurityContexts(&User{UIDNumber: "319769", GIDNumber: "1025", FsGroup: "1025"})
	if err != nil {
		t.Fatal(err)
	}
	return pod, ctr
}

// mutate runs the real patch path on dep and returns the patched Deployment.
func mutate(t *testing.T, dep appsv1.Deployment, resources ProfileResources, exempt map[string]bool) appsv1.Deployment {
	t.Helper()
	raw, err := json.Marshal(&dep)
	if err != nil {
		t.Fatal(err)
	}
	ar := &admissionv1.AdmissionReview{Request: &admissionv1.AdmissionRequest{Object: runtime.RawExtension{Raw: raw}}}
	patchBytes, err := calculatePatch(ar, resources, exempt)
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
	return out
}

func TestCalculatePatchKeepsLauncherHardening(t *testing.T) {
	podSC, ctrSC := identitySCs(t)
	dep := appsv1.Deployment{Spec: appsv1.DeploymentSpec{Template: corev1.PodTemplateSpec{Spec: corev1.PodSpec{
		SecurityContext: &corev1.PodSecurityContext{
			FSGroupChangePolicy: func() *corev1.PodFSGroupChangePolicy { p := corev1.FSGroupChangeOnRootMismatch; return &p }(),
			SupplementalGroups:  []int64{0},
		},
		InitContainers: []corev1.Container{{Name: "seed-volumes", Image: "app:1", SecurityContext: launcherContainerSC()}},
		Containers:     []corev1.Container{{Name: "app", Image: "app:1", SecurityContext: launcherContainerSC()}},
	}}}}

	out := mutate(t, dep, ProfileResources{PodSecurityContext: podSC, SecurityContext: ctrSC}, map[string]bool{})
	spec := out.Spec.Template.Spec

	for _, c := range []*corev1.Container{findContainer(spec.Containers, "app"), findContainer(spec.InitContainers, "seed-volumes")} {
		if c == nil {
			t.Fatal("container missing after patch")
		}
		sc := c.SecurityContext
		if sc == nil {
			t.Fatalf("%s: securityContext missing", c.Name)
		}
		// identity applied
		if sc.RunAsUser == nil || *sc.RunAsUser != 319769 || sc.RunAsGroup == nil || *sc.RunAsGroup != 1025 {
			t.Errorf("%s: identity not applied: runAsUser=%v runAsGroup=%v", c.Name, sc.RunAsUser, sc.RunAsGroup)
		}
		// launcher hardening kept
		if sc.ReadOnlyRootFilesystem == nil || !*sc.ReadOnlyRootFilesystem {
			t.Errorf("%s: readOnlyRootFilesystem was dropped", c.Name)
		}
		if sc.RunAsNonRoot == nil || !*sc.RunAsNonRoot {
			t.Errorf("%s: runAsNonRoot was dropped", c.Name)
		}
		if sc.Capabilities == nil || len(sc.Capabilities.Drop) != 1 || sc.Capabilities.Drop[0] != "ALL" {
			t.Errorf("%s: capabilities.drop was dropped: %+v", c.Name, sc.Capabilities)
		}
		if sc.SeccompProfile == nil || sc.SeccompProfile.Type != corev1.SeccompProfileTypeRuntimeDefault {
			t.Errorf("%s: seccompProfile was dropped", c.Name)
		}
		if sc.AllowPrivilegeEscalation == nil || *sc.AllowPrivilegeEscalation {
			t.Errorf("%s: allowPrivilegeEscalation should stay false", c.Name)
		}
	}

	pod := spec.SecurityContext
	if pod == nil || pod.RunAsUser == nil || *pod.RunAsUser != 319769 || pod.FSGroup == nil || *pod.FSGroup != 1025 {
		t.Fatalf("pod identity not applied: %+v", pod)
	}
	if pod.FSGroupChangePolicy == nil || *pod.FSGroupChangePolicy != corev1.FSGroupChangeOnRootMismatch {
		t.Errorf("pod fsGroupChangePolicy was dropped: %+v", pod)
	}
	if len(pod.SupplementalGroups) == 0 || pod.SupplementalGroups[0] != 0 {
		t.Errorf("existing supplemental groups should be kept first, got %v", pod.SupplementalGroups)
	}
}

func TestCalculatePatchContainerWithoutContextGetsIdentityAndDefault(t *testing.T) {
	podSC, ctrSC := identitySCs(t)
	dep := appsv1.Deployment{Spec: appsv1.DeploymentSpec{Template: corev1.PodTemplateSpec{Spec: corev1.PodSpec{
		Containers: []corev1.Container{{Name: "app", Image: "app:1"}},
	}}}}

	out := mutate(t, dep, ProfileResources{PodSecurityContext: podSC, SecurityContext: ctrSC}, map[string]bool{})
	sc := findContainer(out.Spec.Template.Spec.Containers, "app").SecurityContext

	if sc == nil || sc.RunAsUser == nil || *sc.RunAsUser != 319769 {
		t.Fatalf("identity not applied: %+v", sc)
	}
	if sc.AllowPrivilegeEscalation == nil || *sc.AllowPrivilegeEscalation {
		t.Errorf("allowPrivilegeEscalation should default to false, got %v", sc.AllowPrivilegeEscalation)
	}
	if sc.ReadOnlyRootFilesystem != nil {
		t.Errorf("merge must not invent readOnlyRootFilesystem, got %v", *sc.ReadOnlyRootFilesystem)
	}
}

func TestCalculatePatchIdentityExemptContainerKeepsOwnContext(t *testing.T) {
	podSC, ctrSC := identitySCs(t)
	dep := appsv1.Deployment{Spec: appsv1.DeploymentSpec{Template: corev1.PodTemplateSpec{Spec: corev1.PodSpec{
		InitContainers: []corev1.Container{{Name: "userless-volume-tasks", Image: "busybox:1", SecurityContext: &corev1.SecurityContext{
			RunAsUser: int64Ptr(524288), RunAsGroup: int64Ptr(524288), AllowPrivilegeEscalation: boolPtr(false),
		}}},
		Containers: []corev1.Container{{Name: "app", Image: "app:1"}},
	}}}}

	out := mutate(t, dep, ProfileResources{PodSecurityContext: podSC, SecurityContext: ctrSC},
		map[string]bool{"userless-volume-tasks": true})
	sc := findContainer(out.Spec.Template.Spec.InitContainers, "userless-volume-tasks").SecurityContext

	if sc == nil || sc.RunAsUser == nil || *sc.RunAsUser != 524288 {
		t.Errorf("identity-exempt container should keep its own runAsUser, got %+v", sc)
	}
}

func TestMergeContainerSecurityContextDoesNotAlias(t *testing.T) {
	_, identity := identitySCs(t)
	a := mergeContainerSecurityContext(nil, identity)
	b := mergeContainerSecurityContext(nil, identity)
	*a.RunAsUser = 1

	if *b.RunAsUser != 319769 || *identity.RunAsUser != 319769 {
		t.Errorf("merged contexts must not share pointers with each other or the identity")
	}
}

func TestMergeCapabilitiesUnionsAddAndDrop(t *testing.T) {
	existing := &corev1.SecurityContext{Capabilities: &corev1.Capabilities{Drop: []corev1.Capability{"ALL"}}}
	identity := &corev1.SecurityContext{Capabilities: &corev1.Capabilities{
		Add: []corev1.Capability{"CHOWN"}, Drop: []corev1.Capability{"ALL", "NET_RAW"}}}

	got := mergeContainerSecurityContext(existing, identity).Capabilities

	if len(got.Add) != 1 || got.Add[0] != "CHOWN" {
		t.Errorf("add = %v, want [CHOWN]", got.Add)
	}
	if len(got.Drop) != 2 || got.Drop[0] != "ALL" || got.Drop[1] != "NET_RAW" {
		t.Errorf("drop = %v, want [ALL NET_RAW]", got.Drop)
	}
	if len(existing.Capabilities.Drop) != 1 {
		t.Errorf("merge must not modify the existing context")
	}
}

// TestNSLCDSidecarReadOnlyRootFilesystem: the injected nslcd sidecar runs with
// a read-only root (UNCDSR-182) and still sets nothing else the namespace's
// custom SCC would reject (runAsNonRoot, capabilities, seccomp).
func TestNSLCDSidecarReadOnlyRootFilesystem(t *testing.T) {
	_, _, sidecar := getNSLCDVolumesMountsAndSidecar("nslcd-config", "nslcd-sidecar:test")
	sc := sidecar.SecurityContext
	if sc == nil || sc.ReadOnlyRootFilesystem == nil || !*sc.ReadOnlyRootFilesystem {
		t.Fatalf("nslcd sidecar should set readOnlyRootFilesystem: %+v", sc)
	}
	if sc.AllowPrivilegeEscalation == nil || *sc.AllowPrivilegeEscalation {
		t.Errorf("allowPrivilegeEscalation should be false: %+v", sc)
	}
	if sc.RunAsNonRoot != nil || sc.Capabilities != nil || sc.SeccompProfile != nil {
		t.Errorf("sidecar must leave runAsNonRoot/capabilities/seccomp to the SCC: %+v", sc)
	}
	var socketMounted bool
	for _, m := range sidecar.VolumeMounts {
		if m.MountPath == nslcdSocketDir && m.Name == nslcdSocketVol {
			socketMounted = true
		}
	}
	if !socketMounted {
		t.Errorf("nslcd needs its writable socket emptyDir at %s", nslcdSocketDir)
	}
}
