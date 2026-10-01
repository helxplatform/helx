# nslcd sidecar for the user-mutator LDAP (nss-pam-ldapd) migration.
#
# The webhook injects this container alongside every launched app pod. It runs
# the nslcd daemon (the maintained successor to the EOL libnss-ldap in-process
# module), reads /etc/nslcd.conf (mounted from the user-mutator ConfigMap), and
# serves the NSS socket on a shared emptyDir at /var/run/nslcd/socket. The app
# container's libnss-ldapd client talks to that socket.
FROM debian:trixie-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      nslcd libnss-ldapd ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# OpenShift runs containers with an arbitrary, non-root UID that is not present
# in /etc/passwd. nslcd wants its own UID resolvable, and needs to write the
# socket dir. Make both group-writable (group 0) so the entrypoint can adapt at
# runtime regardless of the assigned UID.
RUN chgrp 0 /etc/passwd && chmod g=u /etc/passwd \
 && mkdir -p /var/run/nslcd && chgrp 0 /var/run/nslcd && chmod g=u /var/run/nslcd

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Default to a non-root UID; OpenShift overrides this with its own from the
# namespace range. Either way the entrypoint handles the UID.
USER 65534

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
