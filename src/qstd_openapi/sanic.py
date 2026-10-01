"""Sanic integration: route source, publishing endpoint and a documenting router.

Install with ``qstd-openapi[sanic]``.

Usage::

    from qstd_openapi import OpenAPI
    from qstd_openapi.sanic import OpenAPIBlueprint, SanicRoutes, mount

    users = OpenAPIBlueprint(Blueprint('Users', url_prefix='/users'))

    @users.post(
        '/register',
        tags=['Users'],
        body=UserRegisterInput,
        responses={201: UserDTO},
    )
    async def register_user(request): ...

    app.blueprint(users.blueprint)
    spec = OpenAPI(info={'title': 'Users API', 'version': '1.0.0'})
    spec.include(SanicRoutes(app))
    mount(app, spec, json_path='/openapi.json')
"""

from __future__ import annotations

import datetime
import importlib
import re
import uuid

from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Callable, Generic, Optional, TypeVar, Union, cast

from typing_extensions import Unpack

from qstd_openapi import openapi
from qstd_openapi.core.document import OpenAPI
from qstd_openapi.core.sources import HTTP_METHODS, RouteEntry, SourceEntry
from qstd_openapi.meta.model import Parameter
from qstd_openapi.serialization import dumps, dumps_yaml
from qstd_openapi.ui import DocsRenderer

try:
    _sanic: Any = importlib.import_module('sanic')
except ImportError as exc:  # pragma: no cover - extra not installed
    raise ImportError(
        'qstd_openapi.sanic needs Sanic: install qstd-openapi[sanic]',
    ) from exc

__all__ = ('OpenAPIBlueprint', 'SanicRouteOptions', 'SanicRoutes', 'mount')

F = TypeVar('F', bound=Callable[..., Any])
B = TypeVar('B')

_PARAMETER = re.compile(r'^<([^:>]+)(?::([^>]+))?>$')
_LABEL_TYPES: Mapping[str, Any] = MappingProxyType(
    {
        'int': int,
        'float': float,
        'uuid': uuid.UUID,
        'ymd': datetime.date,
    },
)
_DESCRIBE_OPTIONS = frozenset(openapi.DescribeOptions.__annotations__)
_SKIPPED_METHODS = frozenset({'head', 'options'})


def _path_and_parameters(parts: Sequence[str]) -> tuple[str, tuple[Parameter, ...]]:
    """``('users', '<user_id:int>')`` -> ``('/users/{user_id}', (Parameter...))``."""
    segments: list[str] = []
    parameters: list[Parameter] = []
    for part in parts:
        match = _PARAMETER.match(part)
        if match is None:
            segments.append(part)
            continue
        name, label = match.group(1), match.group(2) or 'str'
        segments.append(f'{{{name}}}')
        parameters.append(Parameter('path', name, _LABEL_TYPES.get(label, str)))
    return '/' + '/'.join(segment for segment in segments if segment), tuple(parameters)


class SanicRoutes:
    """Operations of a Sanic application.

    - path parameters come from the URL template with types from Sanic
      labels (``int``, ``float``, ``uuid``, ``ymd``; anything else is a string);
    - class-based views are documented per HTTP method;
    - ``HEAD``/``OPTIONS``, static files and websockets are skipped;
    - with ``blueprint_tags`` an operation without tags gets its blueprint's
      name as the tag.

    Routes are read when the document is built, so routes registered later
    are included as long as the document is (re)built afterwards.
    """

    def __init__(self, app: Any, *, blueprint_tags: bool = True) -> None:
        self.app = app
        self.blueprint_tags = blueprint_tags

    def collect(self) -> Iterable[SourceEntry]:
        blueprints: dict[int, str] = {}
        for name, blueprint in self.app.blueprints.items():
            for route in blueprint.routes:
                blueprints[id(route)] = name
        seen: set[tuple[str, str, int]] = set()
        entries: list[SourceEntry] = []
        for route in sorted(self.app.router.routes, key=lambda r: (r.path, r.name)):
            if route.extra.static or route.extra.websocket:
                continue
            path, parameters = _path_and_parameters(route.parts)
            tags = (
                (blueprints[id(route)],)
                if (self.blueprint_tags and id(route) in blueprints)
                else ()
            )
            name = _route_name(self.app.name, route.name)
            for method in sorted(m.lower() for m in route.methods):
                if method in _SKIPPED_METHODS or method not in HTTP_METHODS:
                    continue
                handler = self._handler(route.handler, method)
                # strict_slashes=False may register "/x" and "/x/" for one handler.
                key = (path.rstrip('/') or '/', method, id(handler))
                if key in seen:
                    continue
                seen.add(key)
                entries.append(
                    RouteEntry(path, method, handler, tags, parameters, name=name),
                )
        return entries

    @staticmethod
    def _handler(handler: Any, method: str) -> Any:
        view_class = getattr(handler, 'view_class', None)
        if view_class is not None:
            return getattr(view_class, method, handler)
        return handler


def _route_name(app_name: str, route_name: Optional[str]) -> Optional[str]:
    """``'<app>.<blueprint>.<handler>'`` → ``'<blueprint>_<handler>'``."""
    if not route_name:
        return None
    prefix = f'{app_name}.'
    if route_name.startswith(prefix):
        route_name = route_name[len(prefix) :]
    return route_name.replace('.', '_')


def mount(
    app: Any,
    spec: OpenAPI,
    *,
    json_path: Optional[str] = '/openapi.json',
    yaml_path: Optional[str] = None,
    ui: Optional[Mapping[str, DocsRenderer]] = None,
    spec_url: Optional[str] = None,
    title: Optional[str] = None,
    name: str = 'qstd_openapi',
    decorators: Sequence[Callable[[Any], Any]] = (),
    build_on_start: bool = True,
) -> None:
    """Publish the document of ``spec``.

    - ``json_path`` / ``yaml_path``: endpoints with the document (YAML needs
      the ``yaml`` extra); ``None`` disables one;
    - ``ui``: ``{path: renderer}``, e.g. ``{'/docs': Redoc(), '/swagger': SwaggerUI()}``;
      pages load the document from ``spec_url`` (default: ``json_path``, or
      ``yaml_path`` if JSON is disabled) — set it when the app is served under a
      prefix or behind a proxy;
    - ``decorators`` wrap every endpoint (for example an auth check), innermost
      last as with stacked decorators;
    - ``build_on_start`` builds the document before the server starts, so a
      broken description fails the start instead of the first request.

    Route names are ``{name}_json``, ``{name}_yaml`` and ``{name}_ui_<n>``; the
    endpoints are excluded from the document.
    """
    http = _sanic.response.HTTPResponse

    async def openapi_json(request: Any) -> Any:  # noqa: ARG001
        return http(dumps(spec.build().document), content_type='application/json')

    async def openapi_yaml(request: Any) -> Any:  # noqa: ARG001
        return http(dumps_yaml(spec.build().document), content_type='application/yaml')

    if json_path:
        _add_endpoint(app, openapi_json, json_path, f'{name}_json', decorators)
    if yaml_path:
        _add_endpoint(app, openapi_yaml, yaml_path, f'{name}_yaml', decorators)

    document_url = spec_url or json_path or yaml_path
    if ui and not document_url:
        raise ValueError('ui pages need spec_url, json_path or yaml_path')
    page_title = title or str(spec.info.get('title', 'API'))
    for index, (path, renderer) in enumerate((ui or {}).items()):
        page = renderer.render(spec_url=cast(str, document_url), title=page_title)

        async def docs_page(request: Any, _page: str = page) -> Any:  # noqa: ARG001
            return http(_page, content_type='text/html; charset=utf-8')

        _add_endpoint(app, docs_page, path, f'{name}_ui_{index}', decorators)

    if build_on_start:

        async def build_document(*_: Any) -> None:
            spec.build()

        app.register_listener(build_document, 'before_server_start')


def _add_endpoint(
    app: Any,
    endpoint: Callable[..., Any],
    path: str,
    name: str,
    decorators: Sequence[Callable[[Any], Any]],
) -> None:
    handler: Any = openapi.exclude()(endpoint)
    for decorator in reversed(decorators):
        handler = decorator(handler)
    if handler is not endpoint and hasattr(handler, '__dict__'):
        openapi.exclude()(handler)
    app.add_route(handler, path, methods=['GET'], name=name)


class SanicRouteOptions(openapi.DescribeOptions, total=False):
    """``describe`` options plus Sanic's own route options."""

    host: Union[str, list[str], None]
    strict_slashes: Optional[bool]
    stream: bool
    version: Union[int, str, float, None]
    name: Optional[str]
    ignore_body: bool
    apply: bool
    subprotocols: Optional[list[str]]
    websocket: bool
    unquote: bool
    static: bool
    version_prefix: str
    error_format: Optional[str]
    ctx: Mapping[str, Any]
    """Route context: ``ctx={'auth': False}`` is Sanic's ``ctx_auth=False``."""


class OpenAPIBlueprint(Generic[B]):
    """A Sanic ``Blueprint`` (or app) whose route decorators also take ``describe`` options.

    ``users.post('/register', tags=['Users'], body=Model, name='register')``
    registers the route with Sanic (``name`` and other Sanic options are passed
    through) and attaches the documentation options to the handler. The
    wrapped object is ``.blueprint`` (typed); other attributes (``middleware``,
    ``exception``...) are also delegated to it, untyped.
    """

    def __init__(self, blueprint: B) -> None:
        self.blueprint: B = blueprint

    def __getattr__(self, name: str) -> Any:
        return getattr(self.blueprint, name)

    def route(
        self,
        uri: str,
        methods: Iterable[str] = ('GET',),
        **options: Unpack[SanicRouteOptions],
    ) -> Callable[[F], F]:
        return self._register('route', uri, {'methods': list(methods), **options})

    def get(self, uri: str, **options: Unpack[SanicRouteOptions]) -> Callable[[F], F]:
        return self._register('get', uri, dict(options))

    def post(self, uri: str, **options: Unpack[SanicRouteOptions]) -> Callable[[F], F]:
        return self._register('post', uri, dict(options))

    def put(self, uri: str, **options: Unpack[SanicRouteOptions]) -> Callable[[F], F]:
        return self._register('put', uri, dict(options))

    def patch(self, uri: str, **options: Unpack[SanicRouteOptions]) -> Callable[[F], F]:
        return self._register('patch', uri, dict(options))

    def delete(
        self,
        uri: str,
        **options: Unpack[SanicRouteOptions],
    ) -> Callable[[F], F]:
        return self._register('delete', uri, dict(options))

    def add_route(
        self,
        handler: F,
        uri: str,
        methods: Iterable[str] = ('GET',),
        **options: Unpack[SanicRouteOptions],
    ) -> F:
        described, sanic_options = _split(dict(options))
        self._describe(handler, described)
        blueprint: Any = self.blueprint
        blueprint.add_route(handler, uri, methods=list(methods), **sanic_options)
        return handler

    def _register(
        self,
        method: str,
        uri: str,
        options: Mapping[str, object],
    ) -> Callable[[F], F]:
        described, sanic_options = _split(options)
        register = getattr(self.blueprint, method)(uri, **sanic_options)

        def decorate(handler: F) -> F:
            self._describe(handler, described)
            register(handler)
            return handler

        return decorate

    @staticmethod
    def _describe(handler: Any, described: dict[str, Any]) -> None:
        if not described:
            return
        view_class = getattr(handler, 'view_class', None)
        targets = (
            [getattr(view_class, m) for m in HTTP_METHODS if hasattr(view_class, m)]
            if view_class is not None
            else [handler]
        )
        for target in targets:
            openapi.attach(target, **described)


def _split(options: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    described = {k: v for k, v in options.items() if k in _DESCRIBE_OPTIONS}
    rest = {
        k: v for k, v in options.items() if k not in _DESCRIBE_OPTIONS and k != 'ctx'
    }
    for key, value in cast('Mapping[str, Any]', options.get('ctx', {})).items():
        rest[f'ctx_{key}'] = value
    return described, rest
