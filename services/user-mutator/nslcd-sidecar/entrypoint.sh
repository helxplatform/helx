#!/bin/sh
# nslcd sidecar entrypoint.
#
# Adapts to OpenShift's arbitrary runtime UID: nslcd needs its own UID to be
# resolvable in /etc/passwd, and it will run as the current (non-root) user
# without dropping privileges. The socket lives on the shared emptyDir mounted
# at /var/run/nslcd, which the app container reads via libnss-ldapd.
set -eu

uid="$(id -u)"

# Ensure the runtime UID is resolvable (arbitrary-UID OpenShift case).
if ! getent passwd "$uid" >/dev/null 2>&1; then
    echo "nslcd:x:${uid}:0:nslcd sidecar:/var/run/nslcd:/sbin/nologin" >> /etc/passwd 2>/dev/null || true
fi

# Make sure the shared socket dir exists (emptyDir is mounted here).
mkdir -p /var/run/nslcd 2>/dev/null || true

# Run in the foreground (-d) so the container stays alive and logs to stderr.
# nslcd started as a non-root user runs as that user; the generated nslcd.conf
# deliberately omits uid/gid directives so no setuid is attempted.
exec nslcd -d
