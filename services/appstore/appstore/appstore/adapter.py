import logging
from allauth.account.adapter import DefaultAccountAdapter, get_adapter as get_account_adapter
from allauth.account.utils import user_username
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from django.conf import settings
from django.forms import ValidationError
from django.http import HttpResponseRedirect

from core import ldap_provision

logger = logging.getLogger(__name__)

class RestrictEmailAdapter(DefaultAccountAdapter):
    def clean_email(self, email):
        RestrictedList = ["Your restricted list goes here."]
        if email in RestrictedList:
            raise ValidationError(
                "You are restricted from registering. Please contact admin."
            )
        return email

class LoginRedirectAdapter(DefaultAccountAdapter, DefaultSocialAccountAdapter):
    """
    For regular form login redirect the user to the correct
    frontend based on where they started. Frontends set
    a session key in the respective view class.

    https://django-allauth.readthedocs.io/en/latest/advanced.html#custom-redirects
    """
    
    def generate_unique_username(self, txts, regex=None):
        # Split the email to use as generated username (jdoe@gmail.com -> jdoe)
        # rather than the first name. allauth still sanitizes and suffixes on collision.
        email = next((t for t in txts if t and "@" in t), None)
        if email:
            txts = [email] + [t for t in txts if t != email]
        return super().generate_unique_username(txts, regex)

    def _login_url(self, request):
        if request.session.get("helx_frontend") == "django":
            url = "/apps/"
        elif request.session.get("helx_frontend") == "react":
            url = "/helx/"
        else:
            url = settings.LOGIN_REDIRECT_URL
        return url

    def _logout_url(self, request):
        if request.session.get("helx_frontend") == "django":
            url = "/"
        elif request.session.get("helx_frontend") == "react":
            url = "/helx/login/"
        else:
            url = settings.ACCOUNT_LOGOUT_REDIRECT_URL
        return url

    def get_login_redirect_url(self, request):
        return self._login_url(request)

    def get_connect_redirect_url(self, request, socialaccount):
        return self._login_url(request)

    def get_logout_redirect_url(self, request):
        username = request.user.username if request.user.is_authenticated else "anonymous"
        frontend = request.session.get("helx_frontend", "unknown")
        url = self._logout_url(request)
        logger.info(f"User {username} logging out from {frontend} frontend, redirecting to {url}")
        # Unset and let the frontend set it again on landing
        # Using get incase the session is cleared between login and logout to prevent
        # an error and returning of the route
        if request.session.get("helx_frontend"):
            del request.session["helx_frontend"]
        return url
    
class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        """With USERNAME_FROM_LDAP, make the username the LDAP uid for the login's
        verified email, refusing the login when there's none or it doesn't match
        the existing user's. See settings.USERNAME_FROM_LDAP."""
        if not settings.USERNAME_FROM_LDAP or sociallogin.account.get_provider(request).id == "saml":
            return
        user = sociallogin.user
        email = next((a.email for a in sociallogin.email_addresses if a.verified), None)
        if not email:
            self._refuse("%s has no verified email", user_username(user))
        uid = ldap_provision.login_uid(email, user)
        if not uid:
            self._refuse("no LDAP entry for %s", email)
        if sociallogin.is_existing:
            if user_username(user) != uid:
                self._refuse("%s is user %s, but its LDAP uid is %s",
                             email, user_username(user), uid)
            return
        try:
            # Validity and availability; allauth would otherwise replace a
            # rejected username with one built from the email.
            get_account_adapter(request).clean_username(uid)
        except ValidationError as err:
            self._refuse("LDAP uid %s for %s can't be a username: %s", uid, email, err)
        user_username(user, uid)

    @staticmethod
    def _refuse(message, *args):
        logger.warning("Refusing social login: " + message, *args)
        raise ImmediateHttpResponse(HttpResponseRedirect(settings.LOGIN_WHITELIST_URL))

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        provider_id = provider.id if provider else "unknown"
        error_code = error.name if error else "unknown"
        exception_str = str(exception) if exception else "No exception details"

        # Extract IP address for security tracking
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR', 'unknown')

        logger.warning(
            f"Social login failed: provider={provider_id} error={error_code} "
            f"ip={ip_address} exception={exception_str}"
        )

        # Note: this is a no-op, since this hook is unimplemented in the default (super) adapter class.
        return super().on_authentication_error(request, provider, error, exception, extra_context)