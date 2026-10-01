from __future__ import annotations

import functools

from typing import Any

import pytest

from qstd_openapi import AttachError, openapi, read_operation
from qstd_openapi.meta import read_contributions


def test_decorators_return_the_same_object() -> None:
    async def register_user() -> None:
        pass

    decorated = openapi.tag('Users')(openapi.summary('Register')(register_user))
    assert decorated is register_user


def test_attach_does_not_mutate_previous_records() -> None:
    async def register_user() -> None:
        pass

    openapi.tag('Users')(register_user)
    before = read_contributions(register_user)
    openapi.tag('Accounts')(register_user)
    after = read_contributions(register_user)

    assert [c.patch.tags for c in before] == [('Users',)]
    assert [c.patch.tags for c in after] == [('Users',), ('Accounts',)]


def test_origins_name_owner_api_and_order() -> None:
    @openapi.summary('Register')
    @openapi.tag('Users')
    async def register_user() -> None:
        pass

    origins = [str(c.origin) for c in read_contributions(register_user)]
    assert origins == [
        f'{__name__}.test_origins_name_owner_api_and_order.<locals>.register_user (tag #0)',
        f'{__name__}.test_origins_name_owner_api_and_order.<locals>.register_user (summary #1)',
    ]


class UserView:
    @openapi.tag('Users')
    async def get(self) -> None:
        pass

    @staticmethod
    @openapi.tag('Static')
    def static_handler() -> None:
        pass


def test_methods_are_read_through_bound_and_unbound_access() -> None:
    assert read_operation(UserView().get).tags == ('Users',)
    assert read_operation(UserView.get).tags == ('Users',)
    assert read_operation(UserView.static_handler).tags == ('Static',)


def test_attach_to_bound_method_stores_on_function() -> None:
    class ProfileView:
        async def get(self) -> None:
            pass

    view = ProfileView()
    openapi.attach(view.get, tags='Profile')
    assert read_operation(ProfileView.get).tags == ('Profile',)


def test_staticmethod_object_is_unwrapped() -> None:
    def handler() -> None:
        pass

    wrapped: Any = staticmethod(handler)
    openapi.tag('Users')(wrapped)
    assert read_operation(handler).tags == ('Users',)


def test_partial_is_followed_to_the_function() -> None:
    @openapi.tag('Users')
    def handler(prefix: str) -> None:
        pass

    assert read_operation(functools.partial(handler, 'x')).tags == ('Users',)


def test_callable_instance() -> None:
    class Handler:
        def __call__(self) -> None:
            pass

    handler = openapi.tag('Users')(Handler())
    assert read_operation(handler).tags == ('Users',)


def test_object_without_dict_is_an_error() -> None:
    with pytest.raises(AttachError, match='no __dict__'):
        openapi.tag('Users')(len)


def test_wrapper_cycle_does_not_hang() -> None:
    def handler() -> None:
        pass

    handler.__wrapped__ = handler  # type: ignore[attr-defined]
    openapi.tag('Users')(handler)
    assert read_operation(handler).tags == ('Users',)
