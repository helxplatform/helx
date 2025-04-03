import logging
from django.contrib.auth.signals import user_logged_in, user_login_failed, user_logged_out
from django.dispatch import receiver

logger = logging.getLogger("django")

@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    logger.info(f"User { user.username } logged in")

@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    # The user object may be None if their session expired prior to logout.
    if user: logger.info(f"User { user.username } logged out")
    else: logger.info("User logged out (identity unavailable)")

@receiver(user_login_failed)
def on_user_failed_login(sender, credentials, request):
    # This will generally only work for form-based login (i.e., not for allauth).
    # Allauth failures are logged within the LoginRedirectAdapter `on_authentication_error` hook.
    logger.info(f"User failed to login with username { credentials.get('username', '<unknown>') }")