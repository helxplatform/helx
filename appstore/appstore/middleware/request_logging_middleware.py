import json
import logging
import time
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Middleware to log API request and response details for visibility.

    Logs:
    - Request: method, path, user, query params, body (for non-GET requests)
    - Response: status code, response time
    - Errors: exception details if request fails
    """

    def process_request(self, request):
        """Log incoming request details."""
        # Store start time for response time calculation
        request._start_time = time.time()

        # Only log API requests (not static files, admin, etc.)
        if not request.path.startswith('/api/'):
            return None

        username = request.user.username if request.user.is_authenticated else "anonymous"

        # Build log message
        log_parts = [
            f"method={request.method}",
            f"path={request.path}",
            f"user={username}",
        ]

        # Add query params if present
        if request.GET:
            log_parts.append(f"query_params={dict(request.GET)}")

        # Add request body for POST/PUT/PATCH (excluding sensitive data)
        if request.method in ['POST', 'PUT', 'PATCH'] and hasattr(request, 'body'):
            try:
                # Try to parse as JSON
                if request.content_type == 'application/json':
                    body = json.loads(request.body.decode('utf-8'))
                    # Redact sensitive fields
                    if isinstance(body, dict):
                        body = self._redact_sensitive_fields(body)
                    log_parts.append(f"body={json.dumps(body)}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                # If not JSON or can't decode, just log content type
                log_parts.append(f"content_type={request.content_type}")

        logger.info(f"API Request: {' '.join(log_parts)}")
        return None

    def process_response(self, request, response):
        """Log response details."""
        # Only log API requests
        if not request.path.startswith('/api/'):
            return response

        # Calculate response time if we have start time
        response_time = None
        if hasattr(request, '_start_time'):
            response_time = (time.time() - request._start_time) * 1000  # Convert to ms

        username = request.user.username if request.user.is_authenticated else "anonymous"

        # Build log message
        log_parts = [
            f"method={request.method}",
            f"path={request.path}",
            f"user={username}",
            f"status={response.status_code}",
        ]

        if response_time is not None:
            log_parts.append(f"response_time={response_time:.2f}ms")

        # Log at different levels based on status code
        if 200 <= response.status_code < 300:
            logger.info(f"API Response: {' '.join(log_parts)}")
        elif 400 <= response.status_code < 500:
            logger.warning(f"API Response: {' '.join(log_parts)}")
        else:
            logger.error(f"API Response: {' '.join(log_parts)}")

        return response

    def process_exception(self, request, exception):
        """Log exception details."""
        # Only log API requests
        if not request.path.startswith('/api/'):
            return None

        username = request.user.username if request.user.is_authenticated else "anonymous"

        logger.error(
            f"API Exception: method={request.method} path={request.path} "
            f"user={username} exception={type(exception).__name__}: {str(exception)}"
        )
        return None

    @staticmethod
    def _redact_sensitive_fields(data):
        """Redact sensitive fields from request body."""
        sensitive_keys = {
            'password', 'passwd', 'pwd', 'secret', 'token', 'api_key',
            'apikey', 'access_token', 'refresh_token', 'auth', 'authorization',
            'private_key', 'privatekey', 'credential', 'credentials'
        }

        if not isinstance(data, dict):
            return data

        redacted = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in sensitive_keys):
                redacted[key] = "***REDACTED***"
            elif isinstance(value, dict):
                redacted[key] = RequestLoggingMiddleware._redact_sensitive_fields(value)
            elif isinstance(value, list):
                redacted[key] = [
                    RequestLoggingMiddleware._redact_sensitive_fields(item)
                    if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                redacted[key] = value

        return redacted
