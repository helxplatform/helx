import logging

""" Used to filter out superfluous logs relating to particular API endpoints. """
class SuperfluousEndpointLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # We do not want to pollute logs with 403s here when all they indicate is that the user is logged out.
        if self.is_forbidden_user_list(record):
            # Downgrade from a WARNING to a DEBUG. We could also return False to filter it out entirely.
            record.levelname = "DEBUG"
            record.levelno = 10
        return True
    
    """ Does the log originate from a request endpoint?
    (This should always be true with proper logging configuration, but worthwhile adding the check.)
    """
    def is_request_log(self, record) -> bool:
        return hasattr(record, "request") and hasattr(record, "status_code")

    """
    A 403 Forbidden is returned by the `GET users` endpoint when a user is logged out/not authenticated.
    This response is expected and frequent behavior, since it is the endpoint the frontend uses to
    assess authentication status and thus is frequently called.
    """
    def is_forbidden_user_list(self, record) -> bool:
        return (
            self.is_request_log(record) and
            record.request.path_info == "/api/v1/users/" and
            record.status_code == 403
        )
