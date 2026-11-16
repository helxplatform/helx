package main

import (
	"testing"

	corev1 "k8s.io/api/core/v1"
)

func TestGetK8sVolumeMountsSubPath(t *testing.T) {
	cfg := VolumeConfig{VolumeMounts: []VolumeMount{
		{Name: "codex", MountPath: "/etc/codex/config.toml", SubPath: "config.toml"},
		{Name: "home", MountPath: "/home/{{.username}}", SubPath: "users/{{.username}}"},
		{Name: "data", MountPath: "/data"},
	}}
	vmap := VolumeContextMap{
		"codex": {{BaseName: "codex", Volume: corev1.Volume{Name: "codex-0"}, Vars: map[string]interface{}{}}},
		"home":  {{BaseName: "home", Volume: corev1.Volume{Name: "home-0"}, Vars: map[string]interface{}{"username": "alice"}}},
		"data":  {{BaseName: "data", Volume: corev1.Volume{Name: "data-0"}, Vars: map[string]interface{}{}}},
	}

	mounts, err := GetK8sVolumeMounts(cfg, vmap)
	if err != nil {
		t.Fatalf("GetK8sVolumeMounts: %v", err)
	}

	want := map[string]corev1.VolumeMount{
		"codex-0": {Name: "codex-0", MountPath: "/etc/codex/config.toml", SubPath: "config.toml"},
		"home-0":  {Name: "home-0", MountPath: "/home/alice", SubPath: "users/alice"},
		"data-0":  {Name: "data-0", MountPath: "/data"},
	}
	if len(mounts) != len(want) {
		t.Fatalf("got %d mounts, want %d: %+v", len(mounts), len(want), mounts)
	}
	for _, m := range mounts {
		if m != want[m.Name] {
			t.Errorf("mount %s = %+v, want %+v", m.Name, m, want[m.Name])
		}
	}
}

func TestGetK8sVolumeMountsSubPathTemplateError(t *testing.T) {
	cfg := VolumeConfig{VolumeMounts: []VolumeMount{
		{Name: "home", MountPath: "/home", SubPath: "{{.missing}}"},
	}}
	vmap := VolumeContextMap{
		"home": {{BaseName: "home", Volume: corev1.Volume{Name: "home-0"}, Vars: map[string]interface{}{}}},
	}

	mounts, err := GetK8sVolumeMounts(cfg, vmap)
	if err == nil {
		t.Fatal("expected a subPath template error")
	}
	if len(mounts) != 0 {
		t.Errorf("expected the failing mount to be skipped, got %+v", mounts)
	}
}
