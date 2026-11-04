"""Create an LDAP account at first login for users from allowed email domains.

ldap-sync only syncs UNC users, so users from other institutions have no LDAP
entry: they can't pass the LDAP group check or launch apps. For a user whose
verified email is in LDAP_PROVISION_EMAIL_DOMAINS, this adds an entry shaped
like the ones ldap-sync writes and adds its uid to the LDAP_GROUP_DN posixGroup.
Existing entries are never changed; a uid or mail already in use is logged and
left for an admin to resolve.
"""
import logging
import os

from allauth.account.models import EmailAddress
from django.conf import settings
from ldap3 import BASE, MODIFY_ADD, SUBTREE
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn

from middleware.filter_whitelist_middleware import AllowWhiteListedUserOnly

logger = logging.getLogger(__name__)

# The object classes ldap-sync gives synced users.
USER_OBJECT_CLASSES = ["top", "inetOrgPerson", "posixAccount", "helxUser"]
# Tries at claiming a uidNumber when concurrent logins pick the same one.
CLAIM_ATTEMPTS = 5
# LDAP result code for adding a value an attribute already has.
ATTRIBUTE_OR_VALUE_EXISTS = 20


def provision(user):
    """Create the user's LDAP entry if they qualify. Returns True if created."""
    email = (user.email or "").lower()
    if not email or email.rpartition("@")[2] not in settings.LDAP_PROVISION_EMAIL_DOMAINS:
        return False

    base, group_dn = os.getenv("LDAP_SEARCH_BASE"), os.getenv("LDAP_GROUP_DN")
    if not (base and group_dn):
        logger.warning("[LDAP provision] LDAP_SEARCH_BASE or LDAP_GROUP_DN unset; "
                       "not provisioning %s", user.username)
        return False
    if "@" in user.username:
        logger.warning("[LDAP provision] username %s contains '@'; not provisioning "
                       "(turn on USERNAME_FROM_EMAIL_LOCALPART)", user.username)
        return False
    if not EmailAddress.objects.filter(user=user, email__iexact=email, verified=True).exists():
        logger.warning("[LDAP provision] %s is not verified; not provisioning %s",
                       email, user.username)
        return False

    conn = AllowWhiteListedUserOnly._ldap_conn()
    if not conn:
        logger.error("[LDAP provision] no LDAP connection; not provisioning %s", user.username)
        return False
    try:
        return _provision(conn, user, email, base, group_dn)
    except Exception as exc:                                   # noqa: BLE001
        # The next login tries again.
        logger.error("[LDAP provision] failed for %s: %s", user.username, exc)
        AllowWhiteListedUserOnly._ldap_discard_conn(conn)
        return False


def _provision(conn, user, email, base, group_dn):
    uid = user.username
    conn.search(base,
                f"(|(uid={escape_filter_chars(uid)})(mail={escape_filter_chars(email)}))",
                SUBTREE, attributes=["uid", "mail"])
    if conn.entries:
        entry = conn.entries[0].entry_attributes_as_dict
        if (len(conn.entries) == 1 and uid in entry.get("uid", [])
                and email in [m.lower() for m in entry.get("mail", [])]):
            # Provisioned earlier; finish a group add that may have failed.
            _add_to_group(conn, group_dn, uid)
        else:
            logger.warning("[LDAP provision] uid %s or mail %s is already used by %s; "
                           "not provisioning", uid, email,
                           ", ".join(e.entry_dn for e in conn.entries))
        return False

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
            logger.error("[LDAP provision] uidNumber range %d-%d is full; not provisioning %s",
                         settings.LDAP_PROVISION_UID_MIN, settings.LDAP_PROVISION_UID_MAX, uid)
            return False
        attrs["uidNumber"] = str(number)
        if not conn.add(dn, USER_OBJECT_CLASSES, attrs):
            # e.g. a concurrent login of the same user added it first.
            logger.error("[LDAP provision] adding %s failed: %s", dn, conn.result)
            return False
        if _claimed(conn, base, dn, number):
            _add_to_group(conn, group_dn, uid)
            logger.info("[LDAP provision] created %s (uidNumber %d)", dn, number)
            return True
        conn.delete(dn)
    logger.error("[LDAP provision] no free uidNumber for %s after %d tries", uid, CLAIM_ATTEMPTS)
    return False


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
        logger.error("[LDAP provision] adding %s to %s failed: %s", uid, group_dn, conn.result)
