"""Metadata attached at every layer survives the usual wrapping patterns.

Each test mirrors a way project middlewares attach documentation around
``functools.wraps``; all of them must produce the same merged description.
"""

from __future__ import annotations

import functools

from typing import Any, Callable, TypeVar

import pytest

from qstd_openapi import OpenAPI, Routes, openapi, read_operation
from qstd_openapi.meta import ErrorRef, Security, read_contributions

F = TypeVar('F', bound=Callable[..., Any])


class UnauthorizedError(Exception):
    pass


class CaptchaInvalidError(Exception):
    pass


class UserRegisterInput:
    pass


def _handler() -> Callable[..., Any]:
    @openapi.tag('Users')
    async def register_user(request: object) -> None:
        pass

    return register_user


def _assert_documented(handler: Callable[..., Any], *, error: type) -> None:
    meta = read_operation(handler)
    assert meta.tags == ('Users',)
    assert meta.security == (Security((('UserSession', ()),)),)
    assert meta.errors == (ErrorRef(error),)


def test_attach_on_wrapper_before_wraps() -> None:
    """``@wraps`` above the openapi decorators: the copy must not erase them."""

    def require_session(func: F) -> F:
        @functools.wraps(func)
        @openapi.security('UserSession')
        @openapi.errors(UnauthorizedError)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    handler = require_session(_handler())
    _assert_documented(handler, error=UnauthorizedError)


def test_attach_on_wrapper_after_wraps() -> None:
    def require_session(func: F) -> F:
        @openapi.security('UserSession')
        @openapi.errors(UnauthorizedError)
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    handler = require_session(_handler())
    _assert_documented(handler, error=UnauthorizedError)


def test_attach_split_between_function_and_wrapper() -> None:
    def require_session(func: F) -> F:
        openapi.errors(UnauthorizedError)(func)

        @functools.wraps(func)
        @openapi.security('UserSession')
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    handler = require_session(_handler())
    _assert_documented(handler, error=UnauthorizedError)


def test_validator_pattern() -> None:
    """Errors on the wrapper before ``wraps``; the body on the function after it."""

    def validate_body(schema: type) -> Callable[[F], F]:
        def decorator(func: F) -> F:
            @functools.wraps(func)
            @openapi.errors(CaptchaInvalidError)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                return await func(*args, **kwargs)

            openapi.body(schema)(func)
            return wrapper  # type: ignore[return-value]

        return decorator

    handler = validate_body(UserRegisterInput)(_handler())
    meta = read_operation(handler)
    assert meta.tags == ('Users',)
    assert meta.errors == (ErrorRef(CaptchaInvalidError),)
    assert [content.schemas for content in meta.body] == [(UserRegisterInput,)]


def test_copied_record_is_not_read_twice() -> None:
    inner = _handler()

    @functools.wraps(inner)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await inner(*args, **kwargs)

    contributions = read_contributions(wrapper)
    assert [c.origin.api for c in contributions] == ['tag']


def test_attach_api_from_middleware() -> None:
    def require_captcha(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return openapi.attach(
            wrapper,
            errors=[CaptchaInvalidError],
            parameters=[openapi.Parameter('header', 'X-Captcha-Token')],
        )  # type: ignore[return-value]

    meta = read_operation(require_captcha(_handler()))
    assert meta.errors == (ErrorRef(CaptchaInvalidError),)
    assert [(p.location, p.name) for p in meta.parameters] == [
        ('header', 'X-Captcha-Token'),
    ]


def test_decorators_without_wraps_break_the_chain() -> None:
    """Documented limitation: without ``__wrapped__`` inner metadata is unreachable."""
    inner = _handler()

    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await inner(*args, **kwargs)

    assert read_operation(wrapper).tags == ()


def _passthrough(func: F) -> F:
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _documented_passthrough(func: F) -> F:
    @functools.wraps(func)
    @openapi.security('UserSession')
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return await func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


@pytest.mark.parametrize('wrap', [_passthrough, _documented_passthrough])
def test_exclude_survives_wrapping_decorator(
    wrap: Callable[[Callable[..., Any]], Callable[..., Any]],
) -> None:
    """Service endpoints (``/docs``) stay excluded under a ``wraps`` decorator."""

    @wrap
    @openapi.exclude()
    async def docs(request: object) -> None:
        pass

    assert read_operation(docs).exclude
    spec = OpenAPI(info={'title': 'Users API', 'version': '1.0.0'}, schemas=())
    spec.include(Routes(('/docs', 'get', docs)))
    assert spec.build().document['paths'] == {}


def test_exclude_above_wrapping_decorator() -> None:
    @openapi.exclude()
    @_documented_passthrough
    async def docs(request: object) -> None:
        pass

    assert read_operation(docs).exclude
