"""Authentication that documents the contract it adds to a handler."""

from __future__ import annotations

import functools

from typing import Any, Callable, TypeVar, cast

from qstd_openapi import openapi

from .errors import UnauthorizedError

F = TypeVar('F', bound=Callable[..., Any])


def require_session(func: F) -> F:
    @functools.wraps(func)
    async def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
        if request.headers.get('X-Session') != 'demo':
            raise UnauthorizedError()
        return await func(request, *args, **kwargs)

    return cast(
        'F',
        openapi.attach(
            wrapper,
            security='UserSession',
            errors=[UnauthorizedError],
        ),
    )
