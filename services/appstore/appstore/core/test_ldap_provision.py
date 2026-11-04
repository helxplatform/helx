import os

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from ldap3 import ALL_ATTRIBUTES, BASE, MOCK_SYNC, MODIFY_DELETE, Connection, Server
from mock import patch

from core.ldap_provision import login_uid
from middleware.filter_whitelist_middleware import AllowWhiteListedUserOnly

ADMIN = "cn=admin,dc=example,dc=org"
USERS = "ou=users,dc=example,dc=org"
GROUP = "cn=helx-users,ou=groups,dc=example,dc=org"


@override_settings(LDAP_PROVISION_EMAIL_DOMAINS=["duke.edu"])
@patch.dict(os.environ, {"LDAP_SEARCH_BASE": USERS, "LDAP_GROUP_DN": GROUP})
class LoginUidTests(TestCase):
    """ Test finding and creating LDAP entries for logins, against an in-memory directory. """

    def setUp(self):
        self.conn = Connection(Server("mock"), user=ADMIN, password="pw", client_strategy=MOCK_SYNC)
        self.conn.strategy.add_entry(ADMIN, {"userPassword": "pw", "sn": "admin"})
        self.conn.strategy.add_entry(USERS, {"objectClass": ["organizationalUnit"], "ou": "users"})
        self.conn.bind()
        patcher = patch.object(AllowWhiteListedUserOnly, "_ldap_conn", return_value=self.conn)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The unsaved user of a social login, for names.
        self.user = User(first_name="Jane", last_name="Doe")

    def _add_account(self, uid, **attrs):
        self.conn.strategy.add_entry(f"uid={uid},{USERS}",
                                     {"objectClass": ["posixAccount"], "uid": uid, **attrs})

    def _entry(self, uid):
        self.conn.search(USERS, f"(uid={uid})", attributes=ALL_ATTRIBUTES)
        return self.conn.entries[0].entry_attributes_as_dict if self.conn.entries else None

    def _members(self):
        if not self.conn.search(GROUP, "(objectClass=posixGroup)", BASE, attributes=["memberUid"]):
            return []
        return sorted(self.conn.entries[0].entry_attributes_as_dict.get("memberUid", []))

    def test_existing_entry_gives_its_uid(self):
        # e.g. a synced UNC user, whose uid isn't their email's local part.
        self._add_account("onyen", mail="Jane_Doe@unc.edu", uidNumber="45678")
        self.assertEqual(login_uid("jane_doe@unc.edu", self.user), "onyen")
        self.assertEqual(self._members(), [])

    def test_no_entry_outside_provisioned_domains_is_refused(self):
        # A Google jdoe must not become UNC's jdoe.
        self._add_account("jdoe", mail="jdoe@unc.edu", uidNumber="45678")
        self.assertIsNone(login_uid("jdoe@gmail.com", self.user))

    def test_several_entries_with_the_mail_are_refused(self):
        self._add_account("a", mail="jdoe@unc.edu", uidNumber="1")
        self._add_account("b", mail="jdoe@unc.edu", uidNumber="2")
        self.assertIsNone(login_uid("jdoe@unc.edu", self.user))

    def test_creates_entry_and_group(self):
        self.assertEqual(login_uid("JDoe@duke.edu", self.user), "jdoe")
        entry = self._entry("jdoe")
        self.assertEqual(entry["uidNumber"], ["2000000"])
        self.assertEqual(entry["gidNumber"], ["1025"])
        self.assertEqual(entry["homeDirectory"], ["/home/jdoe"])
        self.assertEqual(entry["mail"], ["jdoe@duke.edu"])
        self.assertEqual(entry["cn"], ["Jane Doe"])
        self.assertEqual(self._members(), ["jdoe"])

    def test_repeat_login_finds_the_created_entry(self):
        login_uid("jdoe@duke.edu", self.user)
        self.assertEqual(login_uid("jdoe@duke.edu", self.user), "jdoe")
        self.assertIsNone(self._entry("jdoe2"))

    def test_next_user_gets_next_uid_number(self):
        self._add_account("onyen", uidNumber="45678")  # outside the range
        login_uid("jdoe@duke.edu", self.user)
        self.assertEqual(login_uid("asmith@duke.edu", self.user), "asmith")
        self.assertEqual(self._entry("asmith")["uidNumber"], ["2000001"])
        self.assertEqual(self._members(), ["asmith", "jdoe"])

    def test_uid_taken_in_ldap_gets_a_number(self):
        # UNC's jdoe keeps her uid and entry.
        self._add_account("jdoe", mail="jdoe@unc.edu", uidNumber="45678")
        self.assertEqual(login_uid("jdoe@duke.edu", self.user), "jdoe2")
        self.assertEqual(self._entry("jdoe")["mail"], ["jdoe@unc.edu"])
        self.assertEqual(self._entry("jdoe2")["homeDirectory"], ["/home/jdoe2"])

    def test_uid_taken_in_django_gets_a_number(self):
        User.objects.create(username="jdoe", email="jdoe@gmail.com")
        self.assertEqual(login_uid("jdoe@duke.edu", self.user), "jdoe2")

    def test_local_part_is_made_a_valid_uid(self):
        self.assertEqual(login_uid("Jane.Doe+x@duke.edu", self.user), "jane.doex")
        self.assertEqual(login_uid("1jd@duke.edu", self.user), "u1jd")

    @override_settings(LDAP_PROVISION_EMAIL_DOMAINS=[])
    def test_provisioning_off(self):
        self.assertIsNone(login_uid("jdoe@duke.edu", self.user))
        self.assertIsNone(self._entry("jdoe"))

    def test_repeat_login_finishes_group_add(self):
        login_uid("jdoe@duke.edu", self.user)
        self.conn.modify(GROUP, {"memberUid": [(MODIFY_DELETE, ["jdoe"])]})
        self.assertEqual(login_uid("jdoe@duke.edu", self.user), "jdoe")
        self.assertEqual(self._members(), ["jdoe"])

    def test_concurrent_login_with_same_uid_number_retries(self):
        # Another login took 2000000 between our read and our add, and its DN sorts first.
        self._add_account("aaa", uidNumber="2000000")
        with patch("core.ldap_provision._next_uid_number", side_effect=[2000000, 2000001]):
            self.assertEqual(login_uid("jdoe@duke.edu", self.user), "jdoe")
        self.assertEqual(self._entry("jdoe")["uidNumber"], ["2000001"])
        self.assertEqual(self._entry("aaa")["uidNumber"], ["2000000"])

    def test_no_connection_is_refused(self):
        with patch.object(AllowWhiteListedUserOnly, "_ldap_conn", return_value=None):
            self.assertIsNone(login_uid("jdoe@duke.edu", self.user))
