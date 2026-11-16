from types import SimpleNamespace

from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from mock import patch

from appstore.adapter import SocialAccountAdapter


@override_settings(USERNAME_FROM_LDAP=True)
@patch("core.ldap_provision.login_uid", return_value="onyen")
class UsernameFromLdapTests(TestCase):
    """SocialAccountAdapter.pre_social_login with USERNAME_FROM_LDAP."""

    def setUp(self):
        self.request = RequestFactory().get("/")

    @staticmethod
    def _login(user=None, verified=True, provider="openid_connect", existing=False):
        user = user or get_user_model()(username="jdoe@unc.edu", email="jdoe@unc.edu")
        return SimpleNamespace(
            user=user,
            email_addresses=[EmailAddress(email=user.email, verified=verified)],
            account=SimpleNamespace(get_provider=lambda request: SimpleNamespace(id=provider)),
            is_existing=existing,
        )

    def _pre_social_login(self, login):
        SocialAccountAdapter().pre_social_login(self.request, login)
        return login.user.username

    def _assert_refused(self, login):
        with self.assertRaises(ImmediateHttpResponse) as caught:
            self._pre_social_login(login)
        self.assertEqual(caught.exception.response.url, settings.LOGIN_WHITELIST_URL)

    def test_new_user_gets_ldap_uid(self, login_uid):
        self.assertEqual(self._pre_social_login(self._login()), "onyen")
        self.assertEqual(login_uid.call_args.args[0], "jdoe@unc.edu")

    def test_no_ldap_entry_is_refused(self, login_uid):
        login_uid.return_value = None
        self._assert_refused(self._login())

    def test_unverified_email_is_refused(self, login_uid):
        self._assert_refused(self._login(verified=False))
        login_uid.assert_not_called()

    def test_existing_user_with_matching_uid_logs_in(self, login_uid):
        user = get_user_model().objects.create(username="onyen", email="jdoe@unc.edu")
        self.assertEqual(self._pre_social_login(self._login(user, existing=True)), "onyen")

    def test_existing_user_with_other_uid_is_refused(self, login_uid):
        user = get_user_model().objects.create(username="jdoe", email="jdoe@unc.edu")
        self._assert_refused(self._login(user, existing=True))

    def test_uid_taken_by_another_django_user_is_refused(self, login_uid):
        # allauth would otherwise build a different username from the email.
        get_user_model().objects.create(username="onyen", email="someone@else.org")
        self._assert_refused(self._login())

    def test_saml_keeps_its_username(self, login_uid):
        self.assertEqual(self._pre_social_login(self._login(provider="saml")), "jdoe@unc.edu")
        login_uid.assert_not_called()

    @override_settings(USERNAME_FROM_LDAP=False)
    def test_switch_off(self, login_uid):
        self.assertEqual(self._pre_social_login(self._login()), "jdoe@unc.edu")
        login_uid.assert_not_called()


class PasswordLoginTests(TestCase):
    """The allauth password login form, as the HeLx login page posts it."""

    def test_rate_limit_setting_parses(self):
        from allauth.account import app_settings
        from allauth.core.ratelimit import _parse_rates

        rates = [tuple(r) for r in _parse_rates(app_settings.RATE_LIMITS["login_failed"])]
        self.assertIn((10, 86400, "key"), rates)  # per username, per day
        self.assertIn((25, 60, "ip"), rates)      # per address, per minute

    def test_password_login_reaches_the_password_check(self):
        # Used to raise AttributeError ('int' object has no attribute 'strip')
        # from allauth's rate limiter before checking the password.
        get_user_model().objects.create_user(username="breakglass", password="right-password")
        wrong = self.client.post("/accounts/login/", {"login": "breakglass", "password": "wrong"})
        self.assertEqual(wrong.status_code, 200)  # form shown again with an error
        right = self.client.post("/accounts/login/", {"login": "breakglass", "password": "right-password"})
        self.assertEqual(right.status_code, 302)  # logged in, redirected
