"""Typed exception hierarchy for XeisWorks Office."""


class XwOfficeError(Exception):
    """Base exception for all XeisWorks Office errors."""


class ApiError(XwOfficeError):
    """Base for all API communication errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SevdeskApiError(ApiError):
    """Error communicating with sevDesk API."""


class WixApiError(ApiError):
    """Error communicating with Wix API."""


class MollieApiError(ApiError):
    """Error communicating with Mollie API."""


class PrintError(XwOfficeError):
    """Error during printing operations."""


class ConfigError(XwOfficeError):
    """Error in configuration loading or validation."""


class DatabaseError(XwOfficeError):
    """Error in database operations."""
