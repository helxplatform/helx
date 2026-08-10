package main

import (
	"bytes"
	"context"
	"log"
	"os"

	v1 "k8s.io/api/admissionregistration/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	ctrl "sigs.k8s.io/controller-runtime"
)

func CreateMutationConfig(ctx context.Context, caPEM *bytes.Buffer) {

	var (
		webhookNamespace = os.Getenv("WEBHOOK_NAMESPACE")
		mutationCfgName  = os.Getenv("MUTATE_CONFIG")
		webhookService   = os.Getenv("WEBHOOK_SERVICE")
	)
	config := ctrl.GetConfigOrDie()
	kubeClient, err := kubernetes.NewForConfig(config)
	if err != nil {
		panic("failed to set go -client")
	}

	path := "/mutate"
	// fail := v1.Fail
	fail := v1.Ignore
	port := int32(8443)

	if err != nil {
		panic("failed to read certPath")
	}

	log.Println("WEBHOOK_NAMESPACE: ", webhookNamespace)
	log.Println("MUTATE_CONFIG: ", mutationCfgName)
	log.Println("WEBHOOK_SERVICE: ", webhookService)

	mutateconfig := &v1.MutatingWebhookConfiguration{
		ObjectMeta: metav1.ObjectMeta{
			Name: mutationCfgName,
		},
		Webhooks: []v1.MutatingWebhook{{
			Name: webhookService+"."+webhookNamespace+".svc",
			ClientConfig: v1.WebhookClientConfig{
				CABundle: caPEM.Bytes(), // CA bundle created in generateTLSCerts command
				Service: &v1.ServiceReference{
					Name:      webhookService,
					Namespace: webhookNamespace,
					Path:      &path,
					Port:      &port,
				},
			},
			Rules: []v1.RuleWithOperations{
				{
					Operations: []v1.OperationType{
						v1.Create, v1.Update,
					},
					Rule: v1.Rule{
						APIGroups:   []string{"apps"},
						APIVersions: []string{"v1"},
						Resources:   []string{"deployments"},
					},
				}},
				NamespaceSelector: &metav1.LabelSelector{
					MatchLabels: map[string]string{
							"enable-"+mutationCfgName: "true",
					},
				},
				AdmissionReviewVersions: []string{"v1"},
			FailurePolicy:           &fail,
			SideEffects: func() *v1.SideEffectClass {
				sideEffect := v1.SideEffectClassNone
				return &sideEffect
			}(),
		}},
	}

	if _, err := kubeClient.AdmissionregistrationV1().MutatingWebhookConfigurations().Create(
		ctx, mutateconfig, metav1.CreateOptions{},
	); err != nil {
		panic(err)
	}
}
