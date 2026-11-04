# Deployment quirks

Behaviour you should know about before deploying this repo. Each entry covers
something that works as designed but can still surprise you: a step the chart
can't do for you, or a setting that has side effects later. Entries are grouped
by service. Full configuration details stay in each chart's README; this file
only flags the parts that are easy to miss.

## user-mutator

### `webhook.mode: saveToConfigMap`

In this mode the chart doesn't create the `MutatingWebhookConfiguration`.
Instead it stores the manifest in a ConfigMap, and a cluster admin applies it
later.

**The admin must read the manifest before applying it.** Anyone who can edit
ConfigMaps in the release namespace can change what the ConfigMap holds, and
the admin applies it with cluster-level permission. Piping it straight into
`kubectl apply` would apply anything added to it, for example a second
document binding someone to `cluster-admin`. So save it to a file, run
`kubectl diff -f` on it, and check that it holds one
`MutatingWebhookConfiguration` that selects only the namespaces the admin
agreed to (by default just the release namespace). The install notes print
these commands.

The applied object doesn't belong to the Helm release, which has three
consequences:

- **Upgrades don't reach the live webhook.** An upgrade that changes a
  `webhook.*` value, or a certificate rotation, updates the ConfigMap but not
  the configuration the admin already applied. The admin has to re-apply it,
  reading it again the same way.
- **Uninstalling leaves it behind.** `helm uninstall` removes the ConfigMap but
  not the applied configuration. With the default `failurePolicy: Ignore` the
  leftover webhook won't block anything, but it should still be deleted:

  ```sh
  kubectl delete mutatingwebhookconfiguration <fullname>-webhook-<namespace>
  ```

- **Switching back to `create` fails at first.** Helm won't take over an object
  it doesn't own, so delete the applied configuration (same command as above)
  before switching `webhook.mode` back to `create`.

The chart default is `create`, so every environment that needs this mode has
to set it. A deployer with only namespace access gets a permissions error.
Whoever does have cluster permission, such as a cluster admin running Helm
by hand or an Argo CD project that allows cluster-scoped resources, would
create the webhook without any error. Under Argo CD, give namespace-only
environments a project with an empty `clusterResourceWhitelist`.

See "Deploying without cluster-level permission" in
[`services/user-mutator/chart/README.md`](../services/user-mutator/chart/README.md)
for how the mode works and the command the admin runs.
