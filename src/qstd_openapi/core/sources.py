"""Where operations come from: route sources and webhook sets."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, TypeVar, Union

from qstd_openapi import openapi
from qstd_openapi.meta.model import Parameter

F = TypeVar('F', bound=Callable[..., Any])

HTTP_METHODS = ('get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace')


@dataclass(frozen=True)
class RouteEntry:
    """One ``(path, method)`` served by ``handler``.

    ``tags`` and ``parameters`` are defaults known to the source (a router
    name, path parameters parsed from the URL template); explicit metadata on
    the handler overrides them. ``name`` is the route's name in the framework
    (unique in the application), used for the default ``operationId``.
    """

    path: str
    method: str
    handler: Any
    tags: tuple[str, ...] = ()
    parameters: tuple[Parameter, ...] = ()
    name: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.path.startswith('/'):
            raise ValueError(f'Path must start with "/": {self.path!r}')
        method = self.method.lower()
        if method not in HTTP_METHODS:
            raise ValueError(f'Unsupported HTTP method {self.method!r}')
        object.__setattr__(self, 'method', method)


@dataclass(frozen=True)
class WebhookEntry:
    """A function that sends a webhook; name and method come from its metadata."""

    handler: Any


SourceEntry = Union[RouteEntry, WebhookEntry]


class OperationSource(Protocol):
    def collect(self) -> Iterable[SourceEntry]: ...


class Routes:
    """Routes listed by hand: ``Routes(('/users', 'post', register_user), ...)``."""

    def __init__(self, *routes: Union[RouteEntry, tuple[str, str, Any]]) -> None:
        self._routes = tuple(
            route if isinstance(route, RouteEntry) else RouteEntry(*route)
            for route in routes
        )

    def collect(self) -> Iterable[SourceEntry]:
        return self._routes


class WebhookSet:
    """Webhooks of one module, included into a document explicitly.

    Usage::

        webhooks = WebhookSet()

        @webhooks.register('user.registered', scope=ApiScope.CLIENT_API)
        @openapi.body(UserRegisteredEvent)
        async def send_user_registered(user): ...

        spec.include(webhooks)
    """

    def __init__(self, *handlers: Any) -> None:
        self._handlers: list[Any] = list(handlers)

    def add(self, handler: F) -> F:
        """Include a function already marked with ``openapi.webhook``."""
        if handler not in self._handlers:
            self._handlers.append(handler)
        return handler

    def register(
        self,
        name: str,
        method: str = 'post',
        *,
        scope: Optional[Union[Hashable, Iterable[Hashable]]] = None,
    ) -> Callable[[F], F]:
        def decorate(handler: F) -> F:
            openapi.webhook(name, method, scope=scope)(handler)
            return self.add(handler)

        return decorate

    def collect(self) -> Iterable[SourceEntry]:
        return tuple(WebhookEntry(handler) for handler in self._handlers)
