# mypy: warn-unused-ignores
# pyright: reportUnnecessaryTypeIgnoreComment=true
"""Static checks of the public API; checked by mypy and pyright, never executed.

Every ``# type: ignore[...]`` marks a line that must be a type error: if the
error disappears, both checkers report the comment as unused.
"""

from __future__ import annotations

from typing import Any

from typing_extensions import assert_type

from qstd_openapi import openapi
from qstd_openapi.fastapi import OpenAPIRouter
from qstd_openapi.sanic import OpenAPIBlueprint


class UserDTO:
    pass


class UserAlreadyExistsError(Exception):
    pass


class Blueprint:
    """Stands in for a framework router; only the wrapper's typing is checked."""


async def register_user() -> None:
    pass


def describe_options() -> None:
    openapi.describe(
        tags=['Users'],
        summary='Register a user',
        body=UserDTO,
        responses={201: UserDTO, 409: None},
        errors=[UserAlreadyExistsError],
        security={'UserSession': []},
    )
    openapi.describe(respons=UserDTO)  # type: ignore[call-arg]
    openapi.describe(tags=1)  # type: ignore[arg-type]
    openapi.describe(deprecated='yes')  # type: ignore[arg-type]
    openapi.attach(register_user, sumary='Register')  # type: ignore[call-arg]
    openapi.attach(register_user, scope=['user_api'], exclude=False)
    openapi.errors(UserAlreadyExistsError, KeyError)
    openapi.describe(errors='UserAlreadyExistsError')  # type: ignore[arg-type]
    openapi.describe(errors=[UserAlreadyExistsError()])  # type: ignore[list-item]
    openapi.errors('UserAlreadyExistsError')  # type: ignore[arg-type]


def sanic_blueprint() -> None:
    users = OpenAPIBlueprint(Blueprint())
    assert_type(users.blueprint, Blueprint)
    users.post(
        '/register',
        name='register',
        version=1,
        ctx={'auth': False},
        tags=['Users'],
        body=UserDTO,
        errors=[UserAlreadyExistsError],
    )
    users.route('/users', methods=['GET', 'POST'], response=UserDTO)
    users.add_route(register_user, '/register', methods=['POST'], body=UserDTO)
    users.post('/register', respons=UserDTO)  # type: ignore[call-arg]
    users.post('/register', name=1)  # type: ignore[arg-type]
    users.get('/register', strict_slashes='yes')  # type: ignore[arg-type]
    users.post('/register', errors='UserAlreadyExistsError')  # type: ignore[arg-type]


def fastapi_router() -> None:
    users = OpenAPIRouter(Blueprint())
    assert_type(users.router, Blueprint)
    users.post(
        '/register',
        status_code=201,
        tags=['Users'],
        body=UserDTO,
        responses={409: UserAlreadyExistsError},
        fastapi_responses={404: {'description': 'Not found'}},
        errors=[UserAlreadyExistsError],
    )
    users.api_route('/users', methods=['GET'], response=UserDTO)
    users.add_api_route('/register', register_user, methods=['POST'])
    users.post('/register', respons=UserDTO)  # type: ignore[call-arg]
    users.post('/register', tags='Users')  # type: ignore[arg-type]
    users.get('/users', methods=['GET'])  # type: ignore[call-arg]
    users.post('/register', errors=['UserAlreadyExistsError'])  # type: ignore[list-item]


def untyped_delegation(users: OpenAPIBlueprint[Any]) -> None:
    # Other attributes are delegated to the wrapped object without types.
    users.middleware('request')
