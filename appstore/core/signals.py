import logging
from django.contrib.auth.signals import user_logged_in, user_login_failed, user_logged_out
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Extract client IP address from request, checking for proxy headers."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', 'unknown')
    return ip


def get_user_agent(request):
    """Extract user agent from request."""
    return request.META.get('HTTP_USER_AGENT', 'unknown')


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    """Log successful user login with context."""
    ip_address = get_client_ip(request)
    user_agent = get_user_agent(request)
    logger.info(
        f"User login successful: username={user.username} "
        f"ip={ip_address} user_agent={user_agent}"
    )


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    """Log user logout with context."""
    # The user object may be None if their session expired prior to logout.
    ip_address = get_client_ip(request) if request else 'unknown'

    if user:
        logger.info(
            f"User logout: username={user.username} ip={ip_address}"
        )
    else:
        logger.info(
            f"User logout: username=<unavailable> ip={ip_address} "
            "(user identity unavailable, likely expired session)"
        )


@receiver(user_login_failed)
def on_user_failed_login(sender, credentials, request, **kwargs):
    """Log failed login attempt with context."""
    # This will generally only work for form-based login (i.e., not for allauth).
    # Allauth failures are logged within the SocialAccountAdapter `on_authentication_error` hook.
    username = credentials.get('username', '<unknown>')
    ip_address = get_client_ip(request) if request else 'unknown'
    user_agent = get_user_agent(request) if request else 'unknown'

    logger.warning(
        f"User login failed: username={username} "
        f"ip={ip_address} user_agent={user_agent}"
    )