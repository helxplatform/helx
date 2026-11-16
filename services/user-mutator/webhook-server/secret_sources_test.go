package main

import (
	"context"
	"errors"
	"testing"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/metadata"
)

// fakeSecretMeta serves List for secrets only; any other call panics on the
// nil embedded interface.
type fakeSecretMeta struct {
	metadata.ResourceInterface
	names []string
	err   error
	lists int
}

func (f *fakeSecretMeta) Resource(gvr schema.GroupVersionResource) metadata.Getter {
	if gvr.Resource != "secrets" {
		panic("unexpected resource " + gvr.Resource)
	}
	return f
}

func (f *fakeSecretMeta) Namespace(string) metadata.ResourceInterface { return f }

func (f *fakeSecretMeta) List(context.Context, metav1.ListOptions) (*metav1.PartialObjectMetadataList, error) {
	f.lists++
	if f.err != nil {
		return nil, f.err
	}
	list := &metav1.PartialObjectMetadataList{}
	for _, name := range f.names {
		list.Items = append(list.Items, metav1.PartialObjectMetadata{ObjectMeta: metav1.ObjectMeta{Name: name}})
	}
	return list, nil
}

func withMetaClient(t *testing.T, client metadata.Interface) {
	prev := appConfig
	appConfig = &AppConfig{K8sClient: &kubernetes.Clientset{}, MetaClient: client}
	t.Cleanup(func() { appConfig = prev })
}

func TestTemplatedSecretSourceMakesNoAPICall(t *testing.T) {
	client := &fakeSecretMeta{}
	withMetaClient(t, client)

	out, err := parseVolumeSources("helx", "pg", "secret://pguser-{{.username}}", map[string]string{"username": "alice"})
	if err != nil {
		t.Fatal(err)
	}
	if len(out) != 1 {
		t.Fatalf("got %d volumes, want 1", len(out))
	}
	s := out[0].Volume.Secret
	if s == nil || s.SecretName != "pguser-alice" || s.Optional == nil || !*s.Optional {
		t.Errorf("got secret volume %+v, want optional pguser-alice", s)
	}
	if client.lists != 0 {
		t.Errorf("listed secrets %d times, want 0", client.lists)
	}
}

func TestRegexSecretSourceForbiddenIsSkipped(t *testing.T) {
	withMetaClient(t, &fakeSecretMeta{
		err: apierrors.NewForbidden(corev1.Resource("secrets"), "", errors.New("no list")),
	})

	out, err := parseVolumeSources("helx", "data", "secret://{{.username}}-data-(.*)", map[string]string{"username": "alice"})
	if err != nil {
		t.Fatalf("want the source skipped without an error, got %v", err)
	}
	if len(out) != 0 {
		t.Errorf("got %d volumes, want 0", len(out))
	}
}

func TestRegexSecretSourceFansOut(t *testing.T) {
	withMetaClient(t, &fakeSecretMeta{names: []string{"alice-data-b", "alice-data-a", "bob-data-c"}})

	out, err := parseVolumeSources("helx", "data", "secret://{{.username}}-data-(.*)", map[string]string{"username": "alice"})
	if err != nil {
		t.Fatal(err)
	}
	if len(out) != 2 {
		t.Fatalf("got %d volumes, want 2", len(out))
	}
	for i, want := range []string{"a", "b"} {
		if got := out[i].Volume.Secret.SecretName; got != "alice-data-"+want {
			t.Errorf("volume %d: got secret %q, want %q", i, got, "alice-data-"+want)
		}
		if got := out[i].Vars["cap"].([]string); len(got) != 1 || got[0] != want {
			t.Errorf("volume %d: got captures %v, want [%s]", i, got, want)
		}
	}
}
