"""``AppErrors`` with error classes declared without ``from __future__ import annotations``.

Since Python 3.14 (PEP 649) such classes keep their annotations lazily and
have no ``__annotations__`` key in their ``__dict__``. This module must not
use the future import, otherwise it tests the eager path again.
"""

import sys

from typing import Any, ClassVar, Optional

import pytest

from qstd_openapi.contrib.app_errors import AppErrors
from qstd_openapi.errors import ErrorAnnotationError


class ApplicationError(Exception):
    message: str
    code: int
    request_id: str


class UserAlreadyExistsError(ApplicationError):
    message = 'User already exists'
    code = 11
    email: str
    suggestions: Optional[list[str]] = None
    profile: 'UserProfile'
    _origin: Optional[Exception] = None
    registry: ClassVar[dict[int, Any]] = {}


class UserProfile:
    pass


def test_payload_fields_without_future_import() -> None:
    provider = AppErrors(ApplicationError)
    assert provider.payload_fields(UserAlreadyExistsError) == {
        'request_id': str,
        'email': str,
        'suggestions': Optional[list[str]],
        'profile': UserProfile,
    }


def test_schema_lists_payload_fields_as_required() -> None:
    schema = AppErrors(ApplicationError).schema_for(UserAlreadyExistsError)
    assert schema['required'] == [
        'code',
        'error',
        'message',
        'request_id',
        'email',
        'suggestions',
        'profile',
    ]


def test_mro_mixing_eager_and_lazy_annotations() -> None:
    namespace: dict[str, Any] = {'ApplicationError': ApplicationError}
    exec(
        'from __future__ import annotations\n'
        'class UserRegisterError(ApplicationError):\n'
        '    code = 2\n'
        '    user_id: int\n',
        namespace,
    )
    provider = AppErrors(ApplicationError)
    assert provider.payload_fields(namespace['UserRegisterError']) == {
        'request_id': str,
        'user_id': int,
    }


@pytest.mark.skipif(sys.version_info < (3, 14), reason='lazy annotations: PEP 649')
def test_unquoted_undefined_name_is_reported() -> None:
    namespace: dict[str, Any] = {}
    exec(
        'class UserRegisterError(Exception):\n'
        '    code = 99\n'
        '    detail: UndefinedName\n',
        namespace,
    )
    provider = AppErrors(Exception)
    with pytest.raises(ErrorAnnotationError, match='UserRegisterError'):
        provider.schema_for(namespace['UserRegisterError'])
