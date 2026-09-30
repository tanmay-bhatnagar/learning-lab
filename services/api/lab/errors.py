"""Domain errors raised by storage and business logic; mapped to HTTP in the HTTP layer."""


class DomainError(Exception):
    """Base for errors the HTTP layer maps to status codes."""

    status_code: int = 500

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InvalidInput(DomainError):
    status_code = 400


class Forbidden(DomainError):
    status_code = 403


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class TooLarge(DomainError):
    status_code = 413


class DoesNotFit(DomainError):
    status_code = 422


class CorruptData(DomainError):
    status_code = 500


class EmbeddingUnavailable(Exception):
    """The embedding model cannot serve requests now; retrieval may degrade to keyword search."""
