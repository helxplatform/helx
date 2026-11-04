from types import SimpleNamespace

from allauth.account.utils import user_username
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

from appstore.adapter import LoginRedirectAdapter, SocialAccountAdapter


class UsernameFromEmailLocalpartTests(TestCase):
    """SocialAccountAdapter.populate_user with USERNAME_FROM_EMAIL_LOCALPART."""

    def setUp(self):
        self.request = RequestFactory().get("/")

    def _signup_username(self, data):
        """Populate a new user from provider data the way a social signup does."""
        user = get_user_model()()
        SocialAccountAdapter().populate_user(self.request, SimpleNamespace(user=user), data)
        LoginRedirectAdapter().populate_username(self.request, user)
        return user_username(user)

    @override_settings(USERNAME_FROM_EMAIL_LOCALPART=True)
    def test_email_username_becomes_localpart(self):
        data = {"username": "Jane.Smith@duke.edu", "email": "Jane.Smith@duke.edu"}
        self.assertEqual(self._signup_username(data), "jane.smith")

    @override_settings(USERNAME_FROM_EMAIL_LOCALPART=True)
    def test_taken_localpart_gets_a_different_username(self):
        get_user_model().objects.create_user(username="jsmith", email="jsmith@unc.edu")
        username = self._signup_username({"username": "jsmith@duke.edu", "email": "jsmith@duke.edu"})
        self.assertNotEqual(username, "jsmith")
        self.assertTrue(username.startswith("jsmith"))
        self.assertNotIn("@", username)

    @override_settings(USERNAME_FROM_EMAIL_LOCALPART=True)
    def test_username_without_at_is_kept(self):
        data = {"username": "jsmith", "email": "jane.smith@duke.edu"}
        self.assertEqual(self._signup_username(data), "jsmith")

    @override_settings(USERNAME_FROM_EMAIL_LOCALPART=False)
    def test_switch_off_keeps_email_username(self):
        data = {"username": "jsmith@duke.edu", "email": "jsmith@duke.edu"}
        self.assertEqual(self._signup_username(data), "jsmith@duke.edu")
