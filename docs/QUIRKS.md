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
later. The applied object doesn't belong to the Helm release, which has three
consequences:

- **Upgrades don't reach the live webhook.** An upgrade that changes a
  `webhook.*` value, or a certificate rotation, updates the ConfigMap but not
  the configuration the admin already applied. The admin has to re-apply it.
- **Uninstalling leaves it behind.** `helm uninstall` removes the ConfigMap but
  not the applied configuration. With the default `failurePolicy: Ignore` the
  leftover webhook won't block anything, but it should still be deleted:

  ```sh
  kubectl delete mutatingwebhookconfiguration <fullname>-webhook-<namespace>
  ```

- **Switching back to `create` fails at first.** Helm won't take over an object
  it doesn't own, so delete the applied configuration (same command as above)
  before switching `webhook.mode` back to `create`.

See "Deploying without cluster-level permission" in
[`services/user-mutator/chart/README.md`](../services/user-mutator/chart/README.md)
for how the mode works and the command the admin runs.
