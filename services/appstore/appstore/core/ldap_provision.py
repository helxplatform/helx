"""Find, or create, the LDAP entry a social login's username comes from.

With USERNAME_FROM_LDAP, a social login's username is the uid of the one LDAP
entry whose mail is the login's verified email (see appstore.adapter). ldap-sync
only syncs UNC users, so users from other institutions have no entry. For an
email in LDAP_PROVISION_EMAIL_DOMAINS, this creates one, shaped like the ones
ldap-sync writes, and adds its uid to the LDAP_GROUP_DN posixGroup. Existing
entries are never changed. The uid is <local part>.<institution> (jdoe.duke), so
it can never be a UNC onyen, and one already in use, in LDAP or Django, is never
reused: the new entry gets a numbered one (jdoe.duke2) instead.
"""
import logging
import os
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from ldap3 import BASE, MODIFY_ADD, SUBTREE
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn

from middleware.filter_whitelist_middleware import AllowWhiteListedUserOnly

logger = logging.getLogger(__name__)

# The object classes ldap-sync gives synced users.
USER_OBJECT_CLASSES = ["top", "inetOrgPerson", "posixAccount", "helxUser"]
# Tries at claiming a uidNumber when concurrent logins pick the same one.
CLAIM_ATTEMPTS = 5
# Numbered uids tried after the plain one (jdoe.duke2 ... jdoe.duke99).
UID_SUFFIXES = 99
# LDAP result code for adding a value an attribute already has.
ATTRIBUTE_OR_VALUE_EXISTS = 20


def login_uid(email, user):
    """The uid of the one LDAP entry whose mail is email, creating the entry first
    when there's none and email's domain is in LDAP_PROVISION_EMAIL_DOMAINS.

    email must be verified. user is the unsaved login user, for names. Returns
    None when there's no entry, more than one, or LDAP can't be reached: the
    caller refuses the login.
    """
    base = os.getenv("LDAP_SEARCH_BASE")
    if not base:
        logger.error("[LDAP username] LDAP_SEARCH_BASE unset; can't look up %s", email)
        return None
    email = email.lower()
    provisioned = email.rpartition("@")[2] in settings.LDAP_PROVISION_EMAIL_DOMAINS

    conn = None
    # A cached connection the server has dropped fails once; retry on a fresh one.
    for attempt in range(2):
        if attempt:
            AllowWhiteListedUserOnly._ldap_discard_conn(conn)
        conn = AllowWhiteListedUserOnly._ldap_conn()
        if not conn:
            continue
        try:
            return _login_uid(conn, base, email, user, provisioned)
        except Exception as exc:                               # noqa: BLE001
            logger.error("[LDAP username] lookup for %s failed: %s", email, exc)
    AllowWhiteListedUserOnly._ldap_discard_conn(conn)
    logger.error("[LDAP username] giving up on %s", email)
    return None


def _login_uid(conn, base, email, user, provisioned):
    group_dn = os.getenv("LDAP_GROUP_DN")
    if provisioned and not group_dn:
        logger.error("[LDAP username] LDAP_GROUP_DN unset; not provisioning %s", email)
        provisioned = False

    uids = _uids_with_mail(conn, base, email)
    if not uids and provisioned:
        uid = _provision(conn, base, group_dn, email, user)
        uids = [uid] if uid else []
    if len(uids) != 1 or not uids[0]:
        logger.warning("[LDAP username] %d LDAP entries have mail %s (uids %s); refusing",
                       len(uids), email, uids)
        return None
    if provisioned:
        # Every login, so it also finishes a group add that failed earlier.
        _add_to_group(conn, group_dn, uids[0])
    return uids[0]


def _uids_with_mail(conn, base, email):
    """The first uid of each entry whose mail is email (None for an entry without one)."""
    conn.search(base, f"(mail={escape_filter_chars(email)})", SUBTREE, attributes=["uid"])
    return [(e.entry_attributes_as_dict.get("uid") or [None])[0] for e in conn.entries]


def _provision(conn, base, group_dn, email, user):
    """Create an entry for email and return its uid, or None if that failed."""
    uid = _free_uid(conn, base, email)
    if uid is None:
        logger.error("[LDAP username] no free uid for %s", email)
        return None

    _ensure_group(conn, group_dn)
    dn = f"uid={escape_rdn(uid)},{base}"
    name = user.get_full_name()
    attrs = {
        "uid": uid,
        "cn": name or uid,
        "sn": user.last_name or uid,
        "givenName": user.first_name,
        "displayName": name,
        "mail": email,
        "gidNumber": str(settings.LDAP_PROVISION_GID_NUMBER),
        "homeDirectory": f"/home/{uid}",
        "ou": "users",
        # user-mutator copies supplementalGroups into the pod security context.
        "supplementalGroups": "0",
    }
    attrs = {k: v for k, v in attrs.items() if v}

    for _ in range(CLAIM_ATTEMPTS):
        number = _next_uid_number(conn, base)
        if number is None:
            logger.error("[LDAP username] uidNumber range %d-%d is full; not provisioning %s",
                         settings.LDAP_PROVISION_UID_MIN, settings.LDAP_PROVISION_UID_MAX, email)
            return None
        attrs["uidNumber"] = str(number)
        if not conn.add(dn, USER_OBJECT_CLASSES, attrs):
            # e.g. a concurrent login took this uid first. Not retried under
            # another uid: if it's the same user, that would give them two entries.
            logger.error("[LDAP username] adding %s failed: %s", dn, conn.result)
            return None
        if _claimed(conn, base, dn, number):
            # _login_uid then adds uid to the group.
            logger.info("[LDAP username] created %s for %s (uidNumber %d)", dn, email, number)
            return uid
        conn.delete(dn)
    logger.error("[LDAP username] no free uidNumber for %s after %d tries", email, CLAIM_ATTEMPTS)
    return None


def _free_uid(conn, base, email):
    """<local part>.<institution> as a uid (jdoe@duke.edu -> jdoe.duke), numbered
    if LDAP or Django already has it.

    ldap-sync writes each UNC user to uid=<onyen>,<base>. The institution suffix
    keeps a provisioned uid from ever being an onyen (assuming onyens never
    contain a dot), so a later UNC sync can't overwrite the entry.
    """
    # Keep characters valid in a uid and a Kubernetes label.
    clean = lambda s: re.sub(r"[^a-z0-9._-]", "", s.lower())
    local, _, domain = email.partition("@")
    institution = clean(domain.split(".")[0]) or "ext"
    # Linux usernames are at most 32 characters; leave room for a number.
    local = clean(local)[:29 - len(institution)] or "user"
    if not local[0].isalpha():
        local = "u" + local
    stem = f"{local}.{institution}"
    for n in range(1, UID_SUFFIXES + 1):
        uid = stem if n == 1 else f"{stem}{n}"
        conn.search(base, f"(uid={escape_filter_chars(uid)})", SUBTREE, attributes=[])
        if not conn.entries and not get_user_model().objects.filter(username__iexact=uid).exists():
            return uid
    return None


def _next_uid_number(conn, base):
    """One above the highest uidNumber in the provisioning range, or None if full."""
    # ponytail: reads every account's uidNumber, fine for thousands of users. The
    # admin bind is exempt from the server's size limit; any other bind needs
    # a paged search here.
    conn.search(base, "(objectClass=posixAccount)", SUBTREE, attributes=["uidNumber"])
    low, high = settings.LDAP_PROVISION_UID_MIN, settings.LDAP_PROVISION_UID_MAX
    used = [int(n) for e in conn.entries
            for n in e.entry_attributes_as_dict.get("uidNumber", [])
            if low <= int(n) <= high]
    number = max(used) + 1 if used else low
    return number if number <= high else None


def _claimed(conn, base, dn, number):
    """Whether dn keeps uidNumber number: LDAP doesn't enforce unique uidNumbers,
    so concurrent logins can pick the same one. Each sees every entry holding it,
    and the lowest DN keeps it; the others delete their entries and try again."""
    conn.search(base, f"(uidNumber={number})", SUBTREE, attributes=[])
    return min(e.entry_dn.lower() for e in conn.entries) == dn.lower()


def _ensure_group(conn, group_dn):
    """Create the posixGroup if it's missing (ldap-sync creates it at its first sync)."""
    if conn.search(group_dn, "(objectClass=posixGroup)", BASE, attributes=[]) and conn.entries:
        return
    cn = group_dn.split(",", 1)[0].split("=", 1)[1]
    # Fails harmlessly if a concurrent login created it first.
    conn.add(group_dn, ["top", "posixGroup"],
             {"cn": cn, "gidNumber": str(settings.LDAP_PROVISION_GID_NUMBER)})


def _add_to_group(conn, group_dn, uid):
    if not conn.modify(group_dn, {"memberUid": [(MODIFY_ADD, [uid])]}) \
            and conn.result.get("result") != ATTRIBUTE_OR_VALUE_EXISTS:
        logger.error("[LDAP username] adding %s to %s failed: %s", uid, group_dn, conn.result)
