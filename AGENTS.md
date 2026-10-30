# Agent guidance for helx

Read [`AGENTSINIT.md`](AGENTSINIT.md) before starting work here: that file
explains what HeLx does, how the services fit together, and where everything
is. You may skip it for a small, specific change the user asked for whose
effects stay where you make them, such as fixing a typo in a comment or
renaming a local variable. A change to a values file or a `Chart.yaml` never
qualifies; read its "Traps" section at least. This file holds the rules, and
they apply either way.

## Working in the repository

- Do not restructure service directories under `services/` without asking for
  approval.
- Do not commit or create branches unless requested. Preserve unrelated user
  changes, including untracked files and directories.
- Do not revert changes that you notice happen that you don't expect. They are very
  likely intentional changes made by the user. If you think it relevant, you may
  ask the user whether they made the changes or if they were unintentional.
- Call the container registry Harbor (`containers.renci.org/helxplatform`),
  even though its CI secrets are named `CONTAINERHUB_*`. Call the UI service
  `ui`, even though its image is named `helx-ui`.

## Versions

- Nothing bumps versions automatically. Image tags come from chart metadata
  (`v<appVersion>` of the owning chart), never from Git tags or commit
  messages.
- A change needs a bump only when a changed file reaches a published artifact.
  For a chart, its `.helmignore` decides; for an image, its `sources` and
  `excludes` in `.github/ci/images.yaml` plus the build context's
  `.dockerignore`. If a file never reaches an image, add it to that
  `.dockerignore` rather than adding a CI exception.
- An image change bumps `appVersion` and `version` in the owning chart's
  `Chart.yaml`; a chart change bumps its `version`. Either way, bump that
  chart's pin in `deploy/helm/helx-chart/Chart.yaml` in the same change, and the
  umbrella's own `version` if it is not above the last `v*` tag.
- Regenerate `Chart.lock` with `make sync-locks` or `make sync-helx-lock`, never
  `helm dependency update`.
- On pull requests into `develop`, a version only has to sit above the one
  released on `main`, so check that before bumping again. On pull requests into
  `main`, never pass `--above-release`: run
  `make ci-check-versions BASE=origin/main CHECK_VERSIONS_FLAGS=--include-untracked`.

## Charts

- Every container a chart renders, init containers and test pods included, must
  set `securityContext.allowPrivilegeEscalation: false`. AKS denies pods that
  leave it unset, and the umbrella build checks every
  `deploy/helm/values/azure/envs/*` environment.
- `resty` is deliberately ahead of upstream, so never overwrite it wholesale.
  Sync `ambassador`, `pod-reaper`, and `resty` only with
  `make pull-vendored-chart NAME=<name>`. A replay can exit cleanly without
  changing anything, so review `git diff --cached` and trust
  `make check-vendored-sync` over its exit status.

## CI

- Keep workflows thin: shared logic belongs in `.github/actions/` and
  `.github/scripts/ci.py`. [`.github/CI.md`](.github/CI.md) documents both.
- Touching anything in `REBUILD_ALL_IMAGE_PATHS` in `ci.py` (`build-service`,
  `images.yaml`, `ci.py`, `ci.yml`) builds every image. That is intentional,
  not a bug.
- The immutability preflight is skipped for candidate (`<version>-develop`)
  charts and must stay that way; it exists to protect released versions only.

## Checking your work

- Run `make pre-push` before you finish. For a chart change, also run
  `make build-chart SERVICE=<name>`. After editing a workflow or action,
  validate its YAML.
- CI never runs a service's own tests. When you change service code, run its
  tests yourself; `AGENTSINIT.md` lists the command for each service.

## Safety

- Never run anything against shared infrastructure, including read-only
  queries: Harbor (`containers.renci.org`), ACR (`aisandboxrencitgt.azurecr.io`),
  GHCR, and the `helxplatform/helm-charts` index. Test CI logic against
  synthetic fixtures (locally packaged charts, `example.invalid` URLs); scripts
  that touch a registry are for the user to run.
- Cluster investigations are read-only: `get`, `describe`, and `logs`. Give the
  user `exec`, restart, delete, and `helm upgrade` commands to run themselves,
  and say what breaks if one goes wrong.
- Before running a script, say what it does, what it writes, and what it
  touches, rather than asking for approval of an opaque `bash script.sh`.
- Runbooks and other procedure docs must read as timeless instructions: state
  what to look for, never what a previous run printed or when it happened.
  Temporary done markers are fine while someone is working through one.
