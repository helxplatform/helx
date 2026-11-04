import os

from allauth.account.models import EmailAddress
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, override_settings
from ldap3 import ALL_ATTRIBUTES, BASE, MOCK_SYNC, MODIFY_DELETE, Connection, Server
from mock import Mock, patch

from core.ldap_provision import provision
from middleware.filter_whitelist_middleware import AllowWhiteListedUserOnly

ADMIN = "cn=admin,dc=example,dc=org"
USERS = "ou=users,dc=example,dc=org"
GROUP = "cn=helx-users,ou=groups,dc=example,dc=org"


@override_settings(LDAP_PROVISION_EMAIL_DOMAINS=["duke.edu"])
@patch.dict(os.environ, {"LDAP_SEARCH_BASE": USERS, "LDAP_GROUP_DN": GROUP})
class LdapProvisionTests(TestCase):
    """ Test LDAP accounts created at first login, against an in-memory directory. """

    def setUp(self):
        self.conn = Connection(Server("mock"), user=ADMIN, password="pw", client_strategy=MOCK_SYNC)
        self.conn.strategy.add_entry(ADMIN, {"userPassword": "pw", "sn": "admin"})
        self.conn.strategy.add_entry(USERS, {"objectClass": ["organizationalUnit"], "ou": "users"})
        self.conn.bind()
        patcher = patch.object(AllowWhiteListedUserOnly, "_ldap_conn", return_value=self.conn)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _user(username="jdoe", email="jdoe@duke.edu", verified=True):
        user = User.objects.create(username=username, email=email,
                                   first_name="Jane", last_name="Doe")
        EmailAddress.objects.create(user=user, email=email, verified=verified, primary=True)
        return user

    def _add_account(self, rdn, **attrs):
        self.conn.strategy.add_entry(f"{rdn},{USERS}", {"objectClass": ["posixAccount"], **attrs})

    def _entry(self, uid):
        self.conn.search(USERS, f"(uid={uid})", attributes=ALL_ATTRIBUTES)
        return self.conn.entries[0].entry_attributes_as_dict if self.conn.entries else None

    def _members(self):
        if not self.conn.search(GROUP, "(objectClass=posixGroup)", BASE, attributes=["memberUid"]):
            return []
        return sorted(self.conn.entries[0].entry_attributes_as_dict.get("memberUid", []))

    def test_creates_entry_and_group(self):
        self.assertTrue(provision(self._user()))
        entry = self._entry("jdoe")
        self.assertEqual(entry["uidNumber"], ["2000000"])
        self.assertEqual(entry["gidNumber"], ["1025"])
        self.assertEqual(entry["homeDirectory"], ["/home/jdoe"])
        self.assertEqual(entry["mail"], ["jdoe@duke.edu"])
        self.assertEqual(entry["cn"], ["Jane Doe"])
        self.assertEqual(self._members(), ["jdoe"])

    def test_next_user_gets_next_uid_number(self):
        self._add_account("uid=onyen", uid="onyen", uidNumber="45678")  # outside the range
        provision(self._user())
        self.assertTrue(provision(self._user("asmith", "asmith@duke.edu")))
        self.assertEqual(self._entry("asmith")["uidNumber"], ["2000001"])
        self.assertEqual(self._members(), ["asmith", "jdoe"])

    def test_existing_uid_is_not_touched(self):
        # e.g. a synced UNC user with the same name.
        self._add_account("uid=jdoe", uid="jdoe", uidNumber="45678")
        self.assertFalse(provision(self._user()))
        self.assertEqual(self._entry("jdoe")["uidNumber"], ["45678"])
        self.assertEqual(self._members(), [])

    def test_existing_mail_is_not_touched(self):
        self._add_account("uid=janed", uid="janed", mail="jdoe@duke.edu", uidNumber="45678")
        self.assertFalse(provision(self._user()))
        self.assertIsNone(self._entry("jdoe"))

    def test_unverified_email_is_not_provisioned(self):
        self.assertFalse(provision(self._user(verified=False)))
        self.assertIsNone(self._entry("jdoe"))

    def test_other_domain_is_not_provisioned(self):
        # UNC users come from ldap-sync.
        self.assertFalse(provision(self._user(email="jdoe@unc.edu")))
        self.assertIsNone(self._entry("jdoe"))

    @override_settings(LDAP_PROVISION_EMAIL_DOMAINS=[])
    def test_off_by_default(self):
        self.assertFalse(provision(self._user()))
        self.assertIsNone(self._entry("jdoe"))

    def test_repeat_login_finishes_group_add(self):
        user = self._user()
        provision(user)
        self.conn.modify(GROUP, {"memberUid": [(MODIFY_DELETE, ["jdoe"])]})
        self.assertFalse(provision(user))
        self.assertEqual(self._members(), ["jdoe"])

    def test_concurrent_login_with_same_uid_number_retries(self):
        # Another login took 2000000 between our read and our add, and its DN sorts first.
        self._add_account("uid=aaa", uid="aaa", uidNumber="2000000")
        with patch("core.ldap_provision._next_uid_number", side_effect=[2000000, 2000001]):
            self.assertTrue(provision(self._user()))
        self.assertEqual(self._entry("jdoe")["uidNumber"], ["2000001"])
        self.assertEqual(self._entry("aaa")["uidNumber"], ["2000000"])

    def test_login_provisions(self):
        user_logged_in.send(sender=User, request=Mock(META={}), user=self._user())
        self.assertIsNotNone(self._entry("jdoe"))
