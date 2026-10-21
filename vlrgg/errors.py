"""Failures the API reports to its clients, each with its HTTP status."""


class ApiError(Exception):
    status = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class BadRequest(ApiError):
    status = 400


class NotFound(ApiError):
    status = 404


class UpstreamFailed(ApiError):
    """vlr.gg answered with an error, or with a page the parsers do not recognise."""
    status = 502


class UpstreamDown(ApiError):
    """Too many recent failures; vlr.gg is left alone for a while."""
    status = 503


class UpstreamTimeout(ApiError):
    status = 504
