# Ambassador Removal — Design, Changes, Assumptions & Validation

Status: **prototype, validated on `helx-internal` (dev)**
Owner: jseals
Last updated: 2026-07-14

## 1. Goal

Remove **Ambassador** (the EOL `datawire/ambassador` 1.14.4 API gateway) from the
HeLx deployment and consolidate its routing logic into **appstore**, keeping a
thin data-plane proxy (**resty / OpenResty**) for the byte-shuffling that Python
should not do (websocket upgrades, streaming).

## 2. Background — what Ambassador actually did

Investigation showed Ambassador was **only an internal ClusterIP prefix-router**,
configured entirely through `getambassador.io/config` **annotations on Services**
(Tycho stamps one per launched app). It did **not**:

- terminate TLS (ingress-nginx / resty does), or
- enforce auth (nginx `auth_request` → appstore `/auth/` does the decision;
  Ambassador Mappings set `bypass_auth: true`).

Request path (before):

```
user ─HTTPS→ ingress-nginx (TLS) → resty (edge: auth_request, ws, rewrites)
           → ambassador:80 (ClusterIP prefix router)
              ├ /                       → appstore:8000
              ├ /helx, /static/frontend → helx-ui:80
              ├ /ws                     → appstore-sockets:5555
              └ /private/{app}/{user}/{guid}/{conn} → {app}-{guid}:{port}
                 (per-app Mapping: rewrite, REMOTE_USER header, bypass_auth, use_websocket)
```

Key facts that made removal tractable:

- The launched-app Service name is **deterministic from the URL**:
  `{app}-{guid}` (Tycho `System.name = f"{app_id}-{identifier}"`).
- `/private` **already** hard-depends on appstore being up (the `auth_request`
  subrequest calls appstore on every request), so making appstore the router
  adds **no new failure mode**.
- Per-app routing data (port, rewrite target, conn_string) lives in the
  **app-registry** and is known to appstore/Tycho at launch.

## 3. Design (chosen approach)

**appstore = routing control plane; resty = data plane.**

```
user ─HTTPS→ ingress-nginx (TLS) → resty (edge)
           ├ /helx, /static/frontend → helx-ui
           ├ /ws                     → appstore-sockets
           ├ /, /api, /auth          → appstore
           └ /private/{app}/{user}/{guid}/…
                access_by_lua → subrequest → appstore /api/v1/private-route/
                    • verify the caller OWNS this system (NEW; Ambassador never did)
                    • return backend host/port + rewrite (+ REMOTE_USER / ACCESS_TOKEN)
                resty builds {app}-{guid}.<ns>.svc.cluster.local:<port> and proxies
```

Rejected alternative: making Django (ASGI) the full reverse proxy. appstore is
**WSGI/gunicorn** today; proxying websockets (Jupyter kernels, RStudio, webtop,
Guacamole) would require a WSGI→ASGI + Channels re-platform and put all app
traffic through Python. Keeping resty as the byte pump avoids that while still
moving every routing *decision* into appstore.

## 4. Changes by repo

### 4.1 appstore (`prototype/remove-ambassador`)

| Area | Change | Commit |
|---|---|---|
| `api/v1/views.py` | `private_route` resolver: parse `/private/{app}/{user}/{guid}`, verify ownership (path user == session user **and** guid ∈ `tycho.status`), resolve backend port from the **live k8s Service**, read rewrite/conn_string from registry, return `X-Backend-Host/Port`, `X-Rewrite`, `X-Prefix`, `REMOTE_USER`, `ACCESS_TOKEN`. `k8s_service_port()` helper. | `9b2dde0b`, `1c9ce060` |
| `api/v1/router.py` | register `/api/v1/private-route/` | `9b2dde0b` |
| `settings/base.py` | `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO","https")` (CSRF behind the TLS-terminating proxy) | `2a759444` |
| `tycho/model.py`, `tycho/kube.py` | split `system.amb` (emit Ambassador annotation) from `system.proxied` (ClusterIP + `/private` prefix). New `APP_ROUTING_MODE` env: `ambassador` \| `proxy` \| `none` (default `ambassador`, preserving legacy behavior). | `9b2dde0b` |
| `tycho/template/service.yaml`, `pod.yaml` | ClusterIP + `NB_PREFIX`/`FB_BASEURL` gate on `proxied`; annotation stays on `amb`; apps keep their real ports. | `9b2dde0b` |

### 4.2 helx-chart / resty (`prototype/remove-ambassador`)

| Area | Change | Commit |
|---|---|---|
| `charts/resty/templates/nginx-default-configmap.yaml` | remove all `ambassador:80`. Explicit backends: `/helx`+`/static/frontend`→helx-ui, `/ws`→appstore-sockets, `/`→appstore, `/auth`→appstore, `/airflow`→airflow. Dynamic `/private`: `access_by_lua` subrequest to the resolver, build `{app}-{guid}` host from regex, proxy over cluster DNS. | `f0a172d` |
| same | build backend host from URL regex (resolver returned bare app_id); use **FQDNs** for all upstreams (variable `proxy_pass` uses the `resolver`, which ignores DNS search domains) | `2322aa8` |
| same | forward `Host` + `X-Forwarded-*` on `/private` (a variable upstream defaults `Host` to the backend DNS name; pgAdmin et al. build URLs/cookies/CSRF from it) | `0410b31` |
| same | rewrite redirect `Location` headers for **stripped** apps (re-add the `/private/{app}/{user}/{guid}` prefix; what Ambassador+old nginx did via `X-Original-Path`) | `3f57534` |
| `charts/resty/values.yaml` | `dnsResolver`, `global.{appstore,ui,appstore_sockets,airflow}_service_name`, `apps_namespace`, `cluster_dns_suffix` | `f0a172d` |

### 4.3 helx-apps (`ambassador_removal` branch — the proving-ground registry)

- Registry rebased onto the cut-down **edu720-azure** base + a `helx` context
  (appstore `product=helx` **requires** a matching context or `_grok` raises
  `ContextException`). Later migrated wholesale from **cddp-staging** (known-good
  images) and the desktop family + cloudbeaver re-added.
- Per-app `securityContext: {runAsUser: 30000}` for **jupyter** and **rstudio**
  (see §6).
- Per-app rewrite (see §5).

Relevant commits: `456c3f0` (cddp-staging migrate), `9816c82` (desktops+cloudbeaver),
`9d03a72` (jupyter revert + uid), `61656db` (rstudio uid), `827e7e3` (cloudbeaver preserve).

## 5. Per-app routing model

Two behaviors, declared per app in the registry and honored identically by the
resolver + resty (exactly as Ambassador used them):

- **Preserve path** (prefix-aware apps): no rewrite / `proxy-rewrite-rule: True`.
  App serves under `/private/{app}/{user}/{guid}/…` using injected `NB_PREFIX`.
- **Strip to `/`** (root-serving apps): `proxy-rewrite: {enabled: True, target: /}`.
  resty strips the prefix; redirect `Location` headers get the prefix re-added.

| App | Port | Routing | Notes |
|---|---|---|---|
| filebrowser | 8888* | preserve | *registry port is stale (8888); real Service port resolved live (8080) |
| jupyter-helx-notebook | 8888 | preserve | reads `NB_PREFIX`; kernel websocket |
| pgadmin | 8080 | preserve | Flask; needs real `Host`/`X-Forwarded-*` |
| rstudio-server | 8787 | strip → `/` | redirects (needs `Location` rewrite); session events channel |
| webtop / -octave / -image-apps | 3000 | strip → `/` | KasmVNC desktops; socket.io |
| slicer | 6901 | strip → `/` | KasmVNC desktop |
| cloudbeaver | 8978 | preserve | prefix-aware for static; **API/WS servlets not yet** (see §8) |

## 6. Assumptions

1. Launched-app Service name is `{app}-{guid}` (deterministic from the URL).
2. The authoritative backend port is the **live k8s Service** port, not the
   registry `services` value (which can be stale, e.g. filebrowser 8888 vs 8080)
   and not Tycho `status` (returns a stub `port=80` in proxied mode).
3. appstore has in-cluster read access to Services in its namespace.
4. `/private` already depends on appstore (auth), so routing through it adds no
   new dependency.
5. ingress-nginx sets `X-Forwarded-Proto: https`, forwarded through resty.
6. `NFSRODS_UID` is unset on the deployment, so a per-app registry
   `securityContext.runAsUser` is honored (Tycho `set_security_context` last-wins).
7. Per-app app-spec `entrypoint`/`command` is parsed by Tycho with a naive
   whitespace `.split()` and only when given as a **string**; a YAML list is
   passed through unsplit (bad exec), and `${VAR}` is **not** shell-expanded.
   ⇒ rely on the image reading `NB_PREFIX` from env, not a command arg.

## 7. Bugs found & fixed (routing)

- **CSRF 403 on launch** — Django saw the proxied request as HTTP; browser sends
  an `https` Origin → CSRF rejects every POST → user bounced to sign-in.
  Fix: `SECURE_PROXY_SSL_HEADER`.
- **filebrowser 502** — resolver returned the stale registry port (8888) vs the
  live Service port (8080). Fix: look up the live Service port.
- **Backend host NXDOMAIN** — resolver returned bare `app_id`; Service is
  `{app}-{guid}`. Fix: build the host from URL regex. Plus **FQDNs** for all
  upstreams (variable `proxy_pass` + `resolver` ignores search domains; broke `/ws`).
- **pgAdmin blank page** — no `Host`/`X-Forwarded-*` forwarded on `/private`
  (variable upstream → `Host` defaulted to the backend DNS name) → pgAdmin's
  session/CSRF context broke (`400 "CSRF token is missing"`). Fix: forward them.
- **rstudio off-app redirect** — a stripped app's root-relative `302` sent the
  browser to the site root. Fix: rewrite redirect `Location` headers.
- **cloudbeaver 404** — assumed strip; it is prefix-aware. Fix: preserve.

## 8. Validation (live, `helx-internal`, product=helx)

Control plane: resolver + ownership check + CSRF + dynamic proxy: **✅**.

| App | Result | Notes |
|---|---|---|
| filebrowser | ✅ | preserve; live-port fix |
| pgadmin | ✅ | preserve; forwarded-headers fix |
| webtop (+ octave/image-apps) | ✅ | strip; socket.io works |
| slicer | ✅ (routing) | strip |
| rstudio-server | ✅ | strip + redirect-rewrite + R-session events; needed uid 30000 |
| jupyter-helx-notebook | ✅ | preserve + kernel APIs; needed uid 30000 |
| cloudbeaver | ⚠️ UI loads; API/WS 405/404 | app-config (see below) — **not routing** |

### cloudbeaver open item
resty correctly forwards the full `/private/cloudbeaver/…/` path (UI static loads
200). But cloudbeaver's **GraphQL (`/api/gql`) and WebSocket (`/api/ws`) servlets
are not mounted under the dynamic prefix** — `POST /private/…/api/gql` hits
Jetty's static handler → `405 "POST not supported by this URL"`; root `/api/gql`
→ 404. cloudbeaver's `rootURI`/`serverURL` must place the API + WS servlets under
the same `NB_PREFIX`-derived base as the static content. This is a cloudbeaver
image/config task (in development), not a routing change. **TODO: inspect the
image config / source for the servlet base-path knob.**

## 9. Environmental issues surfaced (NOT routing / not this work)

- HeLx runs launched apps as **root** (`TYCHO_APP_RUN_AS_USER=0`), but jupyter and
  rstudio images expect non-root, and the shared NFS home dir is owned by uid
  **30000**. Worked around per-app with `securityContext.runAsUser: 30000`.
  A coherent cluster-wide uid strategy is the real fix.
- NFS (Trident) home dir has mixed ownership across app UIDs.

## 10. How it's deployed on `helx-internal` (dev)

Applied **outside** the `helx` Helm release (direct `kubectl`), so a `helm upgrade`
would revert them until folded into the chart:

- appstore image `containers.renci.org/helxplatform/appstore:test_413`
  (digest `sha256:651f74…`, built from the appstore branch).
- appstore env (via `kubectl set env`): `CSRF_DOMAINS=https://helx-internal.renci.org`,
  `EXTERNAL_TYCHO_APP_REGISTRY_BRANCH=ambassador_removal`.
  (`APP_ROUTING_MODE` left at default `ambassador`; Ambassador is present but
  bypassed by resty, so app Services are still ClusterIP with the real port.)
- resty ConfigMap `helx-default-nginx-conf` patched with the rendered de-Ambassador
  config (backup saved before patching).
- helx-apps registry served from the `ambassador_removal` branch.

Cluster access: `ks` = `kubectl --kubeconfig=/Users/jseals/.kube/sterling` (OIDC).

## 11. Remaining work

1. **cloudbeaver** API/WS servlet base-path (image/config).
2. Fold the resty config + values into the deployed `helx` chart (so `helm upgrade`
   stops reverting the live patch); set `global.*_service_name` / `apps_namespace`.
3. Flip `APP_ROUTING_MODE=proxy` (stop emitting the now-unused Ambassador
   annotation), then scale down / remove the `helx-ambassador` deployment + service.
4. Rebuild appstore from branch tip so all fixes are in the image (no live `cp`).
5. Verify helx-ui's positional URL parsing (`split("/")[6]`, `parts.length-2`)
   against the unchanged `/private/…` scheme.
6. (Optional) fold `appstore-sockets` into appstore if pursuing full consolidation
   (requires ASGI/Channels).

## 12. Branch index

| Repo | Branch |
|---|---|
| appstore | `prototype/remove-ambassador` |
| helx-chart | `prototype/remove-ambassador` |
| helx-apps | `ambassador_removal` (registry + app-specs proving ground) |
