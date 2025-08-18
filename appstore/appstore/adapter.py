import logging
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from django.conf import settings
from django.forms import ValidationError

logger = logging.getLogger(__file__)

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
        url = self._logout_url(request)
        # Unset and let the frontend set it again on landing
        # Using get incase the session is cleared between login and logout to prevent
        # an error and returning of the route
        if request.session.get("helx_frontend"):
            del request.session["helx_frontend"]
        return url
    
class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        provider_id = provider.id if provider else "unknown"
        error_code = error.name if error else "unknown"
        exception_str = str(exception) if exception else "No exception details"

        logger.info(f"User failed to login using allauth:\nprovider id: { provider_id}\nerror code: { error_code }\nexception: { exception_str }")
        
        # Note: this is a no-op, since this hook is unimplemented in the default (super) adapter class.
        return super().on_authentication_error(request, provider, error, exception, extra_context)