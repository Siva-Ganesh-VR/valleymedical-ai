"""Domain errors. The API layer maps these to HTTP responses."""


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class InvalidStateError(DomainError):
    status_code = 409
    code = "invalid_state"


class ForbiddenError(DomainError):
    status_code = 403
    code = "forbidden"


class ValidationFailedError(DomainError):
    status_code = 422
    code = "validation_failed"


class ConfigurationError(Exception):
    """Raised at startup when configuration is unusable."""
