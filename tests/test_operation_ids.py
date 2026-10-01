"""Automatic ``operationId``: on by default, explicit ``operation_id`` wins."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from qstd_openapi import OpenAPI, Routes, WebhookSet, openapi
from qstd_openapi.core.sources import RouteEntry, SourceEntry
from qstd_openapi.errors import DuplicateOperationIdError
from qstd_openapi.meta import OperationMeta


async def get_user() -> None:
    pass


async def update_user() -> None:
    pass


@openapi.operation_id('registerUser')
async def register_user() -> None:
    pass


@openapi.webhook('user.registered')
async def user_registered() -> None:
    pass


class NamedRoutes:
    """A source that knows route names, like the Sanic adapter."""

    def __init__(self, *entries: RouteEntry) -> None:
        self.entries = entries

    def collect(self) -> tuple[SourceEntry, ...]:
        return self.entries


def ids(*sources: Any, **kwargs: Any) -> dict[str, Optional[str]]:
    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1.0.0'},
        schemas=(),
        **kwargs,
    )
    spec.include(*sources)
    document = spec.build().document
    result: dict[str, Optional[str]] = {}
    for section in ('paths', 'webhooks'):
        for name, item in document.get(section, {}).items():
            for method, operation in item.items():
                result[f'{method.upper()} {name}'] = operation.get('operationId')
    return result


def test_function_names_by_default_explicit_wins() -> None:
    webhooks = WebhookSet(user_registered)
    routes = Routes(('/users/me', 'get', get_user), ('/users', 'post', register_user))
    assert ids(routes, webhooks) == {
        'GET /users/me': 'get_user',
        'POST /users': 'registerUser',
        'POST user.registered': 'user_registered',
    }


def test_route_names_from_the_source() -> None:
    source = NamedRoutes(
        RouteEntry('/users/me', 'get', get_user, name='Users_me'),
        RouteEntry('/users/me', 'patch', update_user, name='Users_update_me'),
    )
    assert ids(source) == {
        'GET /users/me': 'Users_me',
        'PATCH /users/me': 'Users_update_me',
    }
    assert ids(source, operation_ids='function') == {
        'GET /users/me': 'get_user',
        'PATCH /users/me': 'update_user',
    }


def test_one_handler_on_several_methods_gets_a_suffix() -> None:
    source = NamedRoutes(
        RouteEntry('/users/me', 'get', get_user, name='Users_me'),
        RouteEntry('/users/me', 'put', get_user, name='Users_me'),
    )
    assert ids(source) == {
        'GET /users/me': 'Users_me_get',
        'PUT /users/me': 'Users_me_put',
    }


def test_different_handlers_with_one_name_are_an_error() -> None:
    def make() -> Any:
        async def get_user() -> None:
            pass

        return get_user

    routes = Routes(('/users/me', 'get', get_user), ('/admin/users/me', 'get', make()))
    with pytest.raises(DuplicateOperationIdError, match=r"'get_user'.*operation_id"):
        ids(routes)


def test_generated_id_does_not_take_an_explicit_one() -> None:
    @openapi.operation_id('get_user')
    async def read_profile() -> None:
        pass

    routes = Routes(('/users/me', 'get', get_user), ('/profile', 'get', read_profile))
    with pytest.raises(DuplicateOperationIdError, match="'get_user'"):
        ids(routes)


def test_custom_strategy_and_disabled() -> None:
    def strategy(entry: SourceEntry, _meta: OperationMeta) -> Optional[str]:
        if isinstance(entry, RouteEntry):
            return f'{entry.method}{entry.path.replace("/", "_")}'
        return None

    routes = Routes(('/users/me', 'get', get_user))
    webhooks = WebhookSet(user_registered)
    assert ids(routes, webhooks, operation_ids=strategy) == {
        'GET /users/me': 'get_users_me',
        'POST user.registered': None,
    }
    assert ids(routes, operation_ids=None) == {'GET /users/me': None}


def test_unknown_strategy_name() -> None:
    with pytest.raises(ValueError, match='operation_ids'):
        OpenAPI(info={'title': 'Users API', 'version': '1.0.0'}, operation_ids='path')  # type: ignore[arg-type]


def test_one_handler_on_several_paths() -> None:
    routes = Routes(('/users/me', 'get', get_user), ('/profile', 'get', get_user))
    assert ids(routes) == {
        'GET /users/me': 'get_user_get_users_me',
        'GET /profile': 'get_user_get_profile',
    }
