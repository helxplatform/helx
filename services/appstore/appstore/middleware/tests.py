import os
import socket
import time

from django.conf import settings
from django.contrib.auth.models import User, Group
from django.http import HttpResponseRedirect
from django.test import SimpleTestCase, TestCase

from ldap3.core.exceptions import LDAPSocketOpenError, LDAPSocketReceiveError
from mock import Mock, patch

from core.models import AuthorizedUser

from middleware.filter_whitelist_middleware import AllowWhiteListedUserOnly


class AllowWhiteListedUserOnlyTests(TestCase):
    """ Test the authorization filter middleware. """

    def setUp(self):
        """ Configure the authorization filter. """
        self.middleware = AllowWhiteListedUserOnly()
        self.request = Mock()
        self.request.META = {
            "HTTP_REMOTE_USER": "testuser",
            "REQUEST_METHOD": "POST",
            "HTTP_OPERATING_SYSTEM_VERSION": "ICE CREAM",
            "HTTP_PLATFORM": "ANDROID",
            "HTTP_APP_VERSION": "1.0.0",
            "HTTP_USER_AGENT": "AUTOMATED TEST",
            "HTTP_HOST": "localhost",
        }
        self.request.scheme = "http"
        self.request.path = "/apps/"
        self.request.session = {}
        self.groups = Group.objects.create(name="whitelisted")

    def test_request_processing(self):
        """ Test processing a request. """
        self.client.login(username="admin", password="adminx")
        response = self.middleware.process_request(self.request)
        self.assertIsNone(response)

    def _create_user_and_login(
        self, username="test", email="test@test.com", password="admin"
    ):
        """Test for creating user"""
        user = User.objects.create(username=username, email=email)
        user.set_password(password)
        user.save()
        self.client.login(username=username, password=password)
        return user

    def test_login_whitelisted_user(self):
        print("---- TESTING FOR WHITELISTED USER (steve_whitelist) ----- ")
        user = self._create_user_and_login(
            username="Steve_whitelist", email="steve@renci.com", password="admin"
        )
        AuthorizedUser.objects.create(email=user.email)
        self.request.user = user
        self.request.session = self.client.session
        response = self.middleware.process_request(self.request)
        self.assertFalse(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            list(self.request.user.groups.values_list("name", flat=True))[0],
            self.groups.name,
        )

    def test_login_whitelisted_username(self):
        print("---- TESTING FOR WHITELISTED USERNAME (steve_whitelist) ----- ")
        user = self._create_user_and_login(
            username="Steve_whitelist", email="steve@renci.com", password="admin"
        )
        AuthorizedUser.objects.create(username=user.username)
        self.request.user = user
        self.request.session = self.client.session
        response = self.middleware.process_request(self.request)
        self.assertFalse(isinstance(response, HttpResponseRedirect))
        self.assertEqual(
            list(self.request.user.groups.values_list("name", flat=True))[0],
            self.groups.name,
        )

    def test_redirect_non_whitelisted_user(self):
        user = self._create_user_and_login(
            username="Steve_nonwhitelist",
            email="steve@non-whitelestd.com",
            password="admin",
        )
        self.request.user = user
        self.request.session = self.client.session
        response = self.middleware.process_request(self.request)
        self.assertTrue(isinstance(response, HttpResponseRedirect))
        self.assertEqual(response.url, settings.LOGIN_WHITELIST_URL)


@patch.dict(os.environ, {
    "LDAP_URI": "ldap://openldap",
    "LDAP_GROUP_DN": "cn=users,ou=groups,dc=example,dc=org",
})
@patch("middleware.filter_whitelist_middleware.Server", Mock())
class LdapGroupMemberRetryTests(SimpleTestCase):
    """ Test that a dropped LDAP connection is replaced rather than reused. """

    def setUp(self):
        AllowWhiteListedUserOnly._ldap_conn.cache_clear()
        self.user = Mock(username="tcheek9", email="tcheek9@example.org")

    def tearDown(self):
        AllowWhiteListedUserOnly._ldap_conn.cache_clear()

    @staticmethod
    def _live_conn(member=True):
        conn = Mock()
        conn.search.return_value = True
        conn.entries = [Mock(entry_dn="uid=tcheek9,ou=users,dc=example,dc=org")]
        conn.compare.return_value = member
        return conn

    @staticmethod
    def _dead_conn():
        conn = Mock()
        conn.search.side_effect = LDAPSocketReceiveError(
            "error receiving data: [Errno 104] Connection reset by peer"
        )
        return conn

    def _check(self, connections):
        with patch("middleware.filter_whitelist_middleware.Connection",
                   side_effect=connections) as factory:
            result = AllowWhiteListedUserOnly._ldap_group_member(self.user)
        return result, factory.call_count

    def test_reconnects_after_dropped_connection(self):
        dead = self._dead_conn()
        result, connects = self._check([dead, self._live_conn()])
        self.assertTrue(result)
        self.assertEqual(connects, 2)
        dead.unbind.assert_called_once()

    def test_retries_failed_connect(self):
        result, connects = self._check([
            LDAPSocketOpenError("socket connection error"),
            self._live_conn(),
        ])
        self.assertTrue(result)
        self.assertEqual(connects, 2)

    def test_gives_up_after_two_retries(self):
        connections = [self._dead_conn() for _ in range(3)]
        result, connects = self._check(connections)
        self.assertFalse(result)
        self.assertEqual(connects, 3)
        # The last dead connection is not left cached for the next request.
        self.assertEqual(AllowWhiteListedUserOnly._ldap_conn.cache_info().currsize, 0)
        for conn in connections:
            conn.unbind.assert_called_once()

    def test_compare_failure_is_retried(self):
        broken = self._live_conn()
        broken.compare.side_effect = LDAPSocketReceiveError("connection reset")
        result, connects = self._check([broken, self._live_conn()])
        self.assertTrue(result)
        self.assertEqual(connects, 2)

    def test_non_member_is_not_retried(self):
        result, connects = self._check([self._live_conn(member=False)])
        self.assertFalse(result)
        self.assertEqual(connects, 1)

    def test_no_match_is_not_retried(self):
        conn = self._live_conn()
        conn.entries = []
        result, connects = self._check([conn])
        self.assertFalse(result)
        self.assertEqual(connects, 1)

    def test_reuses_healthy_connection(self):
        with patch("middleware.filter_whitelist_middleware.Connection",
                   side_effect=[self._live_conn()]) as factory:
            self.assertTrue(AllowWhiteListedUserOnly._ldap_group_member(self.user))
            self.assertTrue(AllowWhiteListedUserOnly._ldap_group_member(self.user))
        self.assertEqual(factory.call_count, 1)

    @patch.dict(os.environ, {"LDAP_URI": ""})
    def test_ldap_disabled_does_not_retry(self):
        result, connects = self._check([])
        self.assertFalse(result)
        self.assertEqual(connects, 0)


class LdapTimeoutTests(SimpleTestCase):
    """ Test that an unresponsive LDAP server cannot hang a request. """

    def setUp(self):
        AllowWhiteListedUserOnly._ldap_conn.cache_clear()
        self.user = Mock(username="tcheek9", email="tcheek9@example.org")

    def tearDown(self):
        AllowWhiteListedUserOnly._ldap_conn.cache_clear()

    @patch.dict(os.environ, {"LDAP_URI": "ldap://openldap"})
    def test_timeouts_passed_to_ldap3(self):
        with patch("middleware.filter_whitelist_middleware.Server") as server, \
                patch("middleware.filter_whitelist_middleware.Connection") as connection:
            AllowWhiteListedUserOnly._ldap_conn()
        self.assertEqual(server.call_args.kwargs["connect_timeout"],
                         AllowWhiteListedUserOnly.LDAP_CONNECT_TIMEOUT)
        self.assertEqual(connection.call_args.kwargs["receive_timeout"],
                         AllowWhiteListedUserOnly.LDAP_RECEIVE_TIMEOUT)

    def test_unresponsive_server_gives_up(self):
        # The kernel completes the TCP handshake for a listening socket even
        # though nothing ever accepts or answers, like a hung slapd.
        silent = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        silent.bind(("127.0.0.1", 0))
        silent.listen(8)
        self.addCleanup(silent.close)
        port = silent.getsockname()[1]

        env = {
            "LDAP_URI": f"ldap://127.0.0.1:{port}",
            "LDAP_GROUP_DN": "cn=users,ou=groups,dc=example,dc=org",
        }
        with patch.dict(os.environ, env), \
                patch.object(AllowWhiteListedUserOnly, "LDAP_RECEIVE_TIMEOUT", 1):
            start = time.monotonic()
            result = AllowWhiteListedUserOnly._ldap_group_member(self.user)
            elapsed = time.monotonic() - start

        self.assertFalse(result)
        # Three attempts, each ending on the receive timeout.
        self.assertGreaterEqual(elapsed, 2.5)
        self.assertLess(elapsed, 10)
