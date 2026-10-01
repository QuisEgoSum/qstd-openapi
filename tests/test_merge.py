from __future__ import annotations

import enum
import functools

from typing import Any

import pytest

from qstd_openapi import ScalarConflictError, markers, openapi, read_operation
from qstd_openapi.meta import (
    Content,
    ErrorRef,
    Parameter,
    ParameterModel,
    Response,
    ResponseHeader,
    Security,
    Webhook,
)


class UserDTO:
    pass


class UserPendingDTO:
    pass


class UserRegisterInput:
    pass


class UserQuery:
    pass


class UserAlreadyExistsError(Exception):
    pass


class WeakPasswordError(Exception):
    pass


class ApiScope(str, enum.Enum):
    CLIENT_API = 'client_api'
    USER_API = 'user_api'


def test_collections_accumulate_without_duplicates() -> None:
    @openapi.tag('Users')
    @openapi.tag('Users', 'Registration')
    @openapi.errors(UserAlreadyExistsError, WeakPasswordError)
    @openapi.errors(UserAlreadyExistsError)
    @openapi.scope(ApiScope.USER_API)
    async def register_user() -> None:
        pass

    meta = read_operation(register_user)
    assert meta.tags == ('Users', 'Registration')
    assert meta.errors == (
        ErrorRef(UserAlreadyExistsError),
        ErrorRef(WeakPasswordError),
    )
    assert meta.scopes == (ApiScope.USER_API,)


def test_str_enum_scope_is_not_split_into_characters() -> None:
    meta = read_operation(openapi.describe(scope=ApiScope.CLIENT_API)(lambda: None))
    assert meta.scopes == (ApiScope.CLIENT_API,)


def test_same_status_schemas_become_one_response() -> None:
    @openapi.responses(UserDTO, UserPendingDTO, status=201)
    @openapi.response(UserDTO, status=201, description='Created')
    @openapi.response_header('X-Request-Id', status=201)
    async def register_user() -> None:
        pass

    (created,) = read_operation(register_user).responses
    assert created == Response(
        status=201,
        description='Created',
        content=(Content('application/json', (UserDTO, UserPendingDTO)),),
        headers=(ResponseHeader('X-Request-Id'),),
    )


def test_status_strings_and_ints_are_the_same_status() -> None:
    meta = read_operation(
        openapi.describe(responses={'201': UserDTO, 201: UserPendingDTO})(lambda: None),
    )
    assert [r.status for r in meta.responses] == [201]


def test_markers_for_files() -> None:
    @openapi.body_form_data_file('avatar')
    @openapi.response_file('image/png')
    async def upload_avatar() -> None:
        pass

    meta = read_operation(upload_avatar)
    assert meta.body == (
        Content(
            'multipart/form-data',
            (markers.FormFields((('avatar', markers.File()),), ('avatar',)),),
        ),
    )
    assert meta.responses[0].content == (Content('image/png', (markers.File(),)),)


def test_no_content_has_no_body() -> None:
    meta = read_operation(openapi.no_content()(lambda: None))
    assert meta.responses == (Response(204),)


def test_security_alternatives() -> None:
    @openapi.security('UserSession')
    @openapi.security({'ApiKey': [], 'Signature': ['write']})
    async def handler() -> None:
        pass

    assert read_operation(handler).security == (
        Security((('ApiKey', ()), ('Signature', ('write',)))),
        Security((('UserSession', ()),)),
    )


def test_parameters_models_and_explicit() -> None:
    @openapi.query(UserQuery)
    @openapi.query('page', int, description='Page number')
    @openapi.path('user_id', int)
    @openapi.header('X-Request-Id')
    async def list_users() -> None:
        pass

    meta = read_operation(list_users)
    assert meta.parameter_models == (ParameterModel('query', UserQuery),)
    assert meta.parameters == (
        Parameter('header', 'X-Request-Id'),
        Parameter('path', 'user_id', int, required=True),
        Parameter('query', 'page', int, description='Page number'),
    )


def test_header_names_are_case_insensitive() -> None:
    @openapi.header('x-request-id', description='lower')
    @openapi.header('X-Request-Id', description='upper')
    async def handler() -> None:
        pass

    with pytest.raises(ScalarConflictError, match='parameters'):
        read_operation(handler)


def test_conflicting_scalars_are_an_error_by_default() -> None:
    @openapi.summary('Register a user')
    @openapi.summary('Create a user')
    async def register_user() -> None:
        pass

    with pytest.raises(ScalarConflictError) as exc_info:
        read_operation(register_user)

    error = exc_info.value
    assert error.field == 'summary'
    assert [value for value, _ in error.values] == ['Create a user', 'Register a user']
    message = str(error)
    assert '(summary #0)' in message
    assert '(summary #1)' in message
    assert "scalar_conflicts='last_wins'" in message


def test_equal_scalars_are_not_a_conflict() -> None:
    @openapi.summary('Register a user')
    @openapi.describe(summary='Register a user')
    async def register_user() -> None:
        pass

    assert read_operation(register_user).summary == 'Register a user'


def test_last_wins_takes_the_outermost_value() -> None:
    @openapi.summary('outer')
    @openapi.summary('inner')
    async def handler() -> None:
        pass

    assert read_operation(handler, 'last_wins').summary == 'outer'


def test_last_wins_wrapper_beats_wrapped_function() -> None:
    @openapi.summary('function')
    async def handler() -> None:
        pass

    @openapi.summary('wrapper')
    @functools.wraps(handler)
    async def wrapper() -> None:
        pass

    # Attached later in time, but to the inner function: still loses.
    openapi.summary('function, later')(handler)
    assert read_operation(wrapper, 'last_wins').summary == 'wrapper'


def test_unknown_strategy_name() -> None:
    with pytest.raises(ValueError, match='Unknown scalar_conflicts'):
        read_operation(lambda: None, 'first_wins')  # type: ignore[arg-type]


def test_flags_and_webhook() -> None:
    @openapi.webhook('user.registered', scope=ApiScope.CLIENT_API)
    @openapi.deprecated()
    @openapi.exclude()
    @openapi.body(UserDTO)
    async def send_user_registered() -> None:
        pass

    meta = read_operation(send_user_registered)
    assert meta.webhook == Webhook('user.registered', 'post')
    assert meta.scopes == (ApiScope.CLIENT_API,)
    assert meta.deprecated
    assert meta.exclude


def test_describe_matches_decorators() -> None:
    @openapi.tag('Users')
    @openapi.summary('Register a user')
    @openapi.operation_id('register_user')
    @openapi.body(UserRegisterInput)
    @openapi.response(UserDTO, status=201)
    @openapi.no_content(202)
    @openapi.errors(UserAlreadyExistsError, WeakPasswordError)
    @openapi.security('UserSession')
    @openapi.query(UserQuery)
    @openapi.extra({'x-internal': True})
    async def with_decorators() -> None:
        pass

    @openapi.describe(
        tags=['Users'],
        summary='Register a user',
        operation_id='register_user',
        body=UserRegisterInput,
        responses={201: UserDTO, 202: None},
        errors=[UserAlreadyExistsError, WeakPasswordError],
        security='UserSession',
        query=UserQuery,
        extra={'x-internal': True},
    )
    async def with_describe() -> None:
        pass

    decorated = read_operation(with_decorators)
    described = read_operation(with_describe)
    assert decorated.tags == described.tags
    assert decorated.summary == described.summary
    assert decorated.operation_id == described.operation_id
    assert decorated.body == described.body
    assert sorted(decorated.responses, key=str) == sorted(described.responses, key=str)
    assert set(decorated.errors) == set(described.errors)
    assert decorated.security == described.security
    assert decorated.parameter_models == described.parameter_models
    assert decorated.extra == described.extra


def test_describe_rejects_unknown_options() -> None:
    with pytest.raises(TypeError, match='Unknown describe options: tag'):
        openapi.describe(tag='Users')  # type: ignore[call-arg]


def test_scalar_conflicts_takes_only_built_in_modes() -> None:
    from qstd_openapi import OpenAPI

    class FirstWins:
        def resolve(self, field: str, values: Any) -> Any:  # noqa: ARG002
            return values[0].value

    info = {'title': 'Users API', 'version': '1.0.0'}
    with pytest.raises(ValueError, match="'error', 'last_wins'"):
        OpenAPI(info=info, scalar_conflicts=FirstWins())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="'error', 'last_wins'"):
        OpenAPI(info=info, scalar_conflicts='first_wins')  # type: ignore[arg-type]
    assert (
        OpenAPI(info=info, scalar_conflicts='last_wins').scalar_conflicts == 'last_wins'
    )
