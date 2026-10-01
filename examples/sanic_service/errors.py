"""Application errors and their HTTP representation."""

from __future__ import annotations

from typing import Any


class ApplicationError(Exception):
    code: int
    message: str
    status_code = 500

    def __init__(self, **payload: Any) -> None:
        super().__init__(self.message)
        self.payload = payload
        for name, value in payload.items():
            setattr(self, name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            'code': self.code,
            'error': type(self).__name__,
            'message': self.message,
            **self.payload,
        }


class UnauthorizedError(ApplicationError):
    code = 1000
    message = 'Unauthorized'
    status_code = 401


class UserAlreadyExistsError(ApplicationError):
    """A user with this email is already registered."""

    code = 1001
    message = 'User already exists'
    status_code = 409
    email: str
