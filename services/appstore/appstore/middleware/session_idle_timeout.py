from django.contrib.auth import logout
from django.contrib import messages
import logging
import time

from appstore.settings import base

logger = logging.getLogger(__name__)

SESSION_IDLE_TIMEOUT =  getattr(base, 'SESSION_IDLE_TIMEOUT', 300)

class SessionIdleTimeout:
    """Middleware class to timeout a session after a specified time period.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, *args, **kwargs):
        if request.user.is_authenticated:
            current_datetime = int(time.time())
            username = request.user.username

            # Check if session has activity tracking
            if request.session.has_key('last_activity'):
                last_activity = request.session['last_activity']
                idle_time = current_datetime - last_activity

                # Check if session has exceeded idle timeout
                if idle_time > SESSION_IDLE_TIMEOUT:
                    # Extract IP address for security tracking
                    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
                    if x_forwarded_for:
                        ip_address = x_forwarded_for.split(',')[0].strip()
                    else:
                        ip_address = request.META.get('REMOTE_ADDR', 'unknown')

                    # Log session expiry with full context
                    logger.warning(
                        f"Session expired: username={username} idle_time={idle_time}s "
                        f"timeout_threshold={SESSION_IDLE_TIMEOUT}s ip={ip_address} "
                        f"attempted_path={request.path}"
                    )

                    messages.info(request, "Session has expired due to prolonged inactivity. Please login to continue.", extra_tags="timeout")
                    logout(request)
                    return None

                # Session is still valid, update last activity
                request.session['last_activity'] = current_datetime

                # Optionally log session refresh for debugging (can be noisy)
                # Uncomment if you need to debug session activity tracking:
                # logger.debug(f"Session activity updated: username={username} path={request.path}")
            else:
                # First request after login, initialize activity tracking
                request.session['last_activity'] = current_datetime
                logger.debug(f"Session activity tracking initialized for user {username}")

        return None
