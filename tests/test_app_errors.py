from __future__ import annotations

import abc
import enum

from typing import Any, ClassVar, Optional

import pytest

from openapi_spec_validator import validate

from qstd_openapi import OpenAPI, Routes, openapi
from qstd_openapi.contrib.app_errors import AppErrors
from qstd_openapi.errors import ErrorAnnotationError, UnsupportedSchemaError


class ApplicationError(Exception):
    message: str
    code: int


class ValidationError(ApplicationError):
    pass


class AuthenticationError(ApplicationError):
    pass


class ConflictError(ApplicationError):
    pass


class Target(enum.Enum):
    BODY = 'body'
    QUERY = 'query'


class ItemError(ValidationError):
    code = 2
    location: list[str]


class SchemaValidationError(ValidationError):
    """Request did not pass validation."""

    message = 'Validation errors'
    code = 1
    target: Target
    errors: list[ItemError]
    registry: ClassVar[dict[int, Any]] = {}


class NotProvidedError(ValidationError):
    message = 'No request {target} provided'
    code = 3


class UnauthorizedError(AuthenticationError):
    message = 'Unauthorized'
    code = 10


class UserAlreadyExistsError(ConflictError):
    message = 'User already exists'
    code = 11
    status_code = 422


class ForcedDynamicError(ApplicationError):
    message = 'Rate limited'
    code = 12
    __openapi_message__ = 'dynamic'


STATUSES = {ValidationError: 400, AuthenticationError: 401, ConflictError: 409}


def build(*errors: type, provider: AppErrors) -> dict[str, Any]:
    @openapi.errors(*errors)
    async def register_user() -> None:
        pass

    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1'},
        schemas=(),
        errors=[provider],
    )
    spec.include(Routes(('/users', 'post', register_user)))
    document = spec.build().document
    validate(document)
    return document


def test_status_by_class_and_attribute() -> None:
    provider = AppErrors(ApplicationError, status_by_class=STATUSES)
    assert provider.status_for(ItemError) == 400
    assert provider.status_for(UnauthorizedError) == 401
    assert provider.status_for(UserAlreadyExistsError) == 422
    assert provider.status_for(ForcedDynamicError) == 500


def test_status_function_wins() -> None:
    provider = AppErrors(
        ApplicationError,
        status=lambda _error: 418,
        status_by_class=STATUSES,
    )
    assert provider.status_for(UserAlreadyExistsError) == 418


def test_schema_follows_to_dict_convention() -> None:
    provider = AppErrors(ApplicationError, status_by_class=STATUSES)
    document = build(SchemaValidationError, provider=provider)
    schemas = document['components']['schemas']
    assert schemas['SchemaValidationError'] == {
        'title': 'SchemaValidationError',
        'type': 'object',
        'description': 'Request did not pass validation.',
        'properties': {
            'code': {'type': 'integer', 'const': 1},
            'error': {'type': 'string', 'const': 'SchemaValidationError'},
            'message': {'type': 'string', 'const': 'Validation errors'},
            'target': {'$ref': '#/components/schemas/Target'},
            'errors': {
                'type': 'array',
                'items': {'$ref': '#/components/schemas/ItemError'},
            },
        },
        'required': ['code', 'error', 'message', 'target', 'errors'],
        'additionalProperties': False,
    }
    # Nested error without a class-level message: plain string.
    assert schemas['ItemError']['properties']['message'] == {'type': 'string'}
    assert schemas['Target'] == {
        'enum': ['body', 'query'],
        'title': 'Target',
        'type': 'string',
    }


def test_message_modes() -> None:
    provider = AppErrors(ApplicationError)
    assert provider.schema_for(NotProvidedError)['properties']['message'] == {
        'type': 'string',
        'examples': ['No request {target} provided'],
    }
    assert provider.schema_for(ForcedDynamicError)['properties']['message'] == {
        'type': 'string',
        'examples': ['Rate limited'],
    }
    assert provider.schema_for(UnauthorizedError)['properties']['message'] == {
        'type': 'string',
        'const': 'Unauthorized',
    }


def test_errors_with_the_same_status_become_one_of() -> None:
    provider = AppErrors(ApplicationError, status_by_class=STATUSES)
    document = build(
        SchemaValidationError,
        NotProvidedError,
        UnauthorizedError,
        provider=provider,
    )
    responses = document['paths']['/users']['post']['responses']
    assert list(responses) == ['400', '401']
    assert responses['400'] == {
        'description': 'Bad Request',
        'content': {
            'application/json': {
                'schema': {
                    'oneOf': [
                        {'$ref': '#/components/schemas/SchemaValidationError'},
                        {'$ref': '#/components/schemas/NotProvidedError'},
                    ],
                },
            },
        },
    }


def test_unevaluable_annotation_is_reported() -> None:
    namespace: dict[str, Any] = {}
    exec(
        'class BrokenError(Exception):\n'
        '    code = 99\n'
        "    detail: 'UndefinedName'\n",
        namespace,
    )
    provider = AppErrors(Exception)
    with pytest.raises(ErrorAnnotationError, match='BrokenError'):
        provider.schema_for(namespace['BrokenError'])


def test_parametrized_generics_with_abc_based_errors() -> None:
    """On 3.9/3.10 ``isinstance(list[int], type)`` is True; issubclass on an ABC raises."""

    class AbcApplicationError(Exception, metaclass=abc.ABCMeta):
        code = 1

    provider = AppErrors(AbcApplicationError)
    assert not provider.supports(list[int])
    assert provider.supports(AbcApplicationError)


class UserStorageError(ApplicationError):
    """Keeps the low-level exception for logs; it is not part of the response."""

    message = 'Storage is unavailable'
    code = 13
    origin: Optional[Exception] = None


def test_unsupported_payload_field_is_named_in_the_error() -> None:
    provider = AppErrors(ApplicationError, status_by_class=STATUSES)
    with pytest.raises(
        UnsupportedSchemaError,
        match=r"UserStorageError.*'origin'.*_origin.*ClassVar",
    ):
        build(UserStorageError, provider=provider)


def test_private_and_classvar_fields_are_not_documented() -> None:
    class PrivateOriginError(ApplicationError):
        message = 'Storage is unavailable'
        code = 14
        _origin: Optional[Exception] = None
        attempts: ClassVar[int] = 3

    provider = AppErrors(ApplicationError)
    assert provider.payload_fields(PrivateOriginError) == {}


def test_subclass_replaces_payload_rule() -> None:
    """A project with another serialization rule overrides one step."""

    class ProjectErrors(AppErrors):
        def payload_fields(self, error: type) -> dict[str, Any]:
            fields = super().payload_fields(error)
            fields.pop('origin', None)
            return fields

    document = build(UserStorageError, provider=ProjectErrors(ApplicationError))
    schema = document['components']['schemas']['UserStorageError']
    assert list(schema['properties']) == ['code', 'error', 'message']
