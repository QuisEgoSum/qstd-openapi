"""FastAPI integration in ``augment`` mode — **experimental**.

Covered by tests but not yet checked on a production project; the merging
rules may change in a minor release.

FastAPI keeps generating its document from signatures, ``response_model``
and dependencies; the library adds what was described with its decorators
(errors, extra responses, security, webhooks, raw patches...) on top.

Install with ``qstd-openapi[fastapi]``.

Usage::

    from qstd_openapi import OpenAPI
    from qstd_openapi.fastapi import OpenAPIRouter, augment

    users = OpenAPIRouter(APIRouter(prefix='/users'))

    @users.post('/register', tags=['Users'], response_model=UserDTO, errors=[UserAlreadyExistsError])
    async def register_user(body: UserRegisterInput) -> UserDTO: ...

    app.include_router(users.router)
    spec = OpenAPI(info={'title': 'Users API', 'version': '1.0.0'}, errors=[AppErrors(...)])
    spec.include(webhooks)          # routes of the app are added by augment()
    augment(app, spec)              # app.openapi() now returns the merged document

Merging rules, per operation (FastAPI's operation is the base):

- operations come from the library's build, so ``openapi.exclude`` and
  scope filters apply; routes FastAPI hides (``include_in_schema=False``)
  stay hidden;
- ``summary``, ``description``, ``operationId``, ``deprecated`` and the
  request body set with the library win; FastAPI fills the rest;
- tags and security requirements are combined;
- parameters: FastAPI's win, the library adds the missing ones;
- responses: a status described with the library replaces FastAPI's for
  that status, other FastAPI responses (e.g. 422) stay;
- components with the same name must match except for annotations
  (``title``, ``default``, ``description``, examples); FastAPI's copy is kept.
"""

from __future__ import annotations

import copy
import importlib
import inspect

from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar, Union, cast

from typing_extensions import Unpack

from qstd_openapi import openapi
from qstd_openapi.core.document import OpenAPI, validate_document
from qstd_openapi.core.sources import HTTP_METHODS, RouteEntry, SourceEntry
from qstd_openapi.dialects.openapi31 import OpenAPI31
from qstd_openapi.errors import ComponentConflictError

try:
    _routing: Any = importlib.import_module('fastapi.routing')
    _openapi_utils: Any = importlib.import_module('fastapi.openapi.utils')
except ImportError as exc:  # pragma: no cover - extra not installed
    raise ImportError(
        'qstd_openapi.fastapi needs FastAPI: install qstd-openapi[fastapi]',
    ) from exc

__all__ = (
    'FastAPIApiRouteOptions',
    'FastAPIRouteOptions',
    'FastAPIRoutes',
    'OpenAPIRouter',
    'augment',
    'merged_document',
)

F = TypeVar('F', bound=Callable[..., Any])
R = TypeVar('R')

JsonObject = dict[str, Any]

_ANNOTATIONS = frozenset({'title', 'description', 'default', 'examples', 'example'})
_OPERATION_SCALARS = (
    'summary',
    'description',
    'operationId',
    'deprecated',
    'requestBody',
)
_SKIPPED_METHODS = frozenset({'head', 'options'})
_NATIVE_OPTIONS = frozenset(
    {'tags', 'summary', 'description', 'deprecated', 'operation_id'},
)
_DESCRIBE_OPTIONS = frozenset(openapi.DescribeOptions.__annotations__) - _NATIVE_OPTIONS


class FastAPIRoutes:
    """Operations of a FastAPI application (``APIRoute`` included in the schema)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def collect(self) -> Iterable[SourceEntry]:
        entries: list[SourceEntry] = []
        for route in _api_routes(self.app):
            if not route.include_in_schema:
                continue
            for method in sorted(m.lower() for m in route.methods):
                if method in _SKIPPED_METHODS or method not in HTTP_METHODS:
                    continue
                entries.append(RouteEntry(route.path_format, method, route.endpoint))
        return entries


def _api_routes(app: Any) -> Iterable[Any]:
    """``APIRoute``-like objects with the effective path, including nested routers.

    FastAPI 0.13x+ keeps included routers lazily and exposes them through
    ``routing.iter_route_contexts``; older versions copy routes into ``app.routes``.
    """
    iterate = getattr(_routing, 'iter_route_contexts', None)
    if iterate is None:
        return [route for route in app.routes if isinstance(route, _routing.APIRoute)]
    return [
        context
        for context in iterate(app.routes)
        if isinstance(context.original_route, _routing.APIRoute)
    ]


def _fastapi_document(app: Any) -> JsonObject:
    """FastAPI's own document, generated without going through ``app.openapi``."""
    candidates: dict[str, Any] = dict(  # noqa: C408 - keyword names are FastAPI's
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        summary=getattr(app, 'summary', None),
        description=app.description,
        terms_of_service=app.terms_of_service,
        contact=app.contact,
        license_info=app.license_info,
        routes=app.routes,
        webhooks=app.webhooks.routes,
        tags=app.openapi_tags,
        servers=app.servers,
        separate_input_output_schemas=getattr(
            app,
            'separate_input_output_schemas',
            True,
        ),
    )
    accepted = inspect.signature(_openapi_utils.get_openapi).parameters
    kwargs = {k: v for k, v in candidates.items() if k in accepted}
    return cast('JsonObject', _openapi_utils.get_openapi(**kwargs))


def _strip_annotations(value: Any) -> Any:
    if isinstance(value, dict):
        items = cast('JsonObject', value).items()
        return {k: _strip_annotations(v) for k, v in items if k not in _ANNOTATIONS}
    if isinstance(value, list):
        return [_strip_annotations(item) for item in cast('list[object]', value)]
    return value


def _merge_components(base: JsonObject, ours: JsonObject) -> None:
    for section, entries in cast('Mapping[str, JsonObject]', ours).items():
        target = cast('JsonObject', base.setdefault(section, {}))
        for name, schema in entries.items():
            existing = target.get(name)
            if existing is None:
                target[name] = schema
            elif _strip_annotations(existing) != _strip_annotations(schema):
                raise ComponentConflictError(
                    f'components/{section}/{name} differs between FastAPI and '
                    'qstd-openapi descriptions; rename one of the models',
                )


def _merge_operation(base: JsonObject, ours: JsonObject) -> JsonObject:
    operation = copy.deepcopy(base)
    for key, value in ours.items():
        if key == 'tags':
            tags = cast('list[str]', operation.setdefault('tags', []))
            tags.extend(tag for tag in value if tag not in tags)
        elif key == 'security':
            requirements = cast(
                'list[JsonObject]',
                operation.setdefault('security', []),
            )
            requirements.extend(r for r in value if r not in requirements)
        elif key == 'parameters':
            parameters = cast(
                'list[JsonObject]',
                operation.setdefault('parameters', []),
            )
            taken = {(p['in'], p['name']) for p in parameters}
            parameters.extend(p for p in value if (p['in'], p['name']) not in taken)
        elif key == 'responses':
            responses = cast('JsonObject', operation.setdefault('responses', {}))
            responses.update(value)
            operation['responses'] = dict(sorted(responses.items(), key=_status_order))
        elif key in _OPERATION_SCALARS or key not in operation:
            operation[key] = value
        elif isinstance(value, dict) and isinstance(operation[key], dict):
            operation[key] = {**operation[key], **cast('JsonObject', value)}
        else:
            operation[key] = value
    return operation


def _status_order(item: tuple[str, Any]) -> tuple[int, str]:
    key = item[0]
    return (0, key.zfill(3)) if key.isdigit() else (1, key)


def _merge(base: JsonObject, ours: JsonObject) -> JsonObject:
    document = copy.deepcopy(base)
    base_paths = cast('JsonObject', base.get('paths', {}))
    paths: JsonObject = {}
    for path, operations in cast(
        'Mapping[str, JsonObject]',
        ours.get('paths', {}),
    ).items():
        merged: JsonObject = {}
        for method, operation in operations.items():
            native = cast('JsonObject', base_paths.get(path, {})).get(method)
            merged[method] = (
                _merge_operation(native, operation) if native else operation
            )
        paths[path] = merged
    document['paths'] = paths

    components = cast('JsonObject', document.setdefault('components', {}))
    _merge_components(components, cast('JsonObject', ours.get('components', {})))
    if not components:
        del document['components']

    info = cast('JsonObject', document.setdefault('info', {}))
    for key, value in cast('JsonObject', ours.get('info', {})).items():
        info.setdefault(key, value)

    for key, value in ours.items():
        if key in ('paths', 'components', 'info'):
            continue
        current = document.get(key)
        if current is None:
            document[key] = value
        elif key == 'tags':
            names = {tag.get('name') for tag in cast('list[JsonObject]', current)}
            current.extend(tag for tag in value if tag.get('name') not in names)
        elif isinstance(current, dict) and isinstance(value, dict):
            for name, item in cast('JsonObject', value).items():
                cast('JsonObject', current).setdefault(name, item)
    return document


def merged_document(app: Any, spec: OpenAPI) -> JsonObject:
    """FastAPI's document of ``app`` merged with what ``spec`` describes."""
    native = _fastapi_document(app)
    native_schemes = cast(
        'JsonObject',
        cast('JsonObject', native.get('components', {})).get('securitySchemes', {}),
    )
    # Merge in 3.1 (what FastAPI produces), then render with the user's dialect.
    variant = spec.derive(
        default_response=False,
        docstrings=False,
        security_schemes={**native_schemes, **spec.security_schemes},
        dialect=OpenAPI31(),
        validate=False,
        operation_ids=None,  # FastAPI names every operation itself
    )
    variant.include(FastAPIRoutes(app))
    merged = _merge(native, variant.build().document)
    webhooks = OpenAPI31().extract_webhooks(merged)
    document = spec.dialect.finalize(merged, webhooks)
    if spec.validate:
        validate_document(document)
    return document


def augment(app: Any, spec: OpenAPI) -> None:
    """Make ``app.openapi()`` return the merged document.

    The result is cached in ``app.openapi_schema`` like FastAPI does; set it to
    ``None`` to rebuild after routes or descriptions change. ``spec`` should
    not include the app's routes itself: they are added here.
    """

    def openapi_schema() -> JsonObject:
        if app.openapi_schema is None:
            app.openapi_schema = merged_document(app, spec)
        return cast('JsonObject', app.openapi_schema)

    app.openapi = openapi_schema


class FastAPIRouteOptions(openapi.DocumentationOptions, total=False):
    """Library options plus FastAPI's own path operation options.

    ``tags``, ``summary``, ``description``, ``deprecated`` and ``operation_id``
    are FastAPI's; ``responses`` is the library's ``{status: schema}`` mapping
    and FastAPI's raw ``responses`` is ``fastapi_responses``.
    """

    response_model: Any
    status_code: Optional[int]
    tags: Optional[list[Union[str, Enum]]]
    dependencies: Optional[Sequence[Any]]
    summary: Optional[str]
    description: Optional[str]
    response_description: str
    fastapi_responses: Optional[dict[Union[int, str], dict[str, Any]]]
    deprecated: Optional[bool]
    operation_id: Optional[str]
    response_model_include: Any
    response_model_exclude: Any
    response_model_by_alias: bool
    response_model_exclude_unset: bool
    response_model_exclude_defaults: bool
    response_model_exclude_none: bool
    include_in_schema: bool
    response_class: Any
    name: Optional[str]
    callbacks: Optional[list[Any]]
    openapi_extra: Optional[dict[str, Any]]
    generate_unique_id_function: Callable[[Any], str]


class FastAPIApiRouteOptions(FastAPIRouteOptions, total=False):
    """Options of ``api_route`` and ``add_api_route``: also the HTTP methods."""

    methods: Optional[list[str]]


class OpenAPIRouter(Generic[R]):
    """An ``APIRouter`` (or app) whose route decorators also take ``describe`` options.

    ``tags``, ``summary``, ``description``, ``deprecated`` and ``operation_id``
    are FastAPI's own options and go to FastAPI. The other ``describe``
    options (``errors``, ``responses``, ``security``, ``scope``, ...) are
    attached to the endpoint; note that ``responses`` therefore means the
    library's ``{status: schema}`` mapping — FastAPI's raw ``responses``
    can be passed as ``fastapi_responses``. Everything else goes to FastAPI.
    The wrapped object is ``.router`` (typed); other attributes are also
    delegated to it, untyped.
    """

    def __init__(self, router: R) -> None:
        self.router: R = router

    def __getattr__(self, name: str) -> Any:
        return getattr(self.router, name)

    def api_route(
        self,
        path: str,
        /,
        **options: Unpack[FastAPIApiRouteOptions],
    ) -> Callable[[F], F]:
        return self._register('api_route', path, options)

    def get(
        self,
        path: str,
        /,
        **options: Unpack[FastAPIRouteOptions],
    ) -> Callable[[F], F]:
        return self._register('get', path, options)

    def post(
        self,
        path: str,
        /,
        **options: Unpack[FastAPIRouteOptions],
    ) -> Callable[[F], F]:
        return self._register('post', path, options)

    def put(
        self,
        path: str,
        /,
        **options: Unpack[FastAPIRouteOptions],
    ) -> Callable[[F], F]:
        return self._register('put', path, options)

    def patch(
        self,
        path: str,
        /,
        **options: Unpack[FastAPIRouteOptions],
    ) -> Callable[[F], F]:
        return self._register('patch', path, options)

    def delete(
        self,
        path: str,
        /,
        **options: Unpack[FastAPIRouteOptions],
    ) -> Callable[[F], F]:
        return self._register('delete', path, options)

    def add_api_route(
        self,
        path: str,
        endpoint: F,
        /,
        **options: Unpack[FastAPIApiRouteOptions],
    ) -> F:
        described, native = _split(options)
        if described:
            openapi.attach(endpoint, **described)
        router: Any = self.router
        router.add_api_route(path, endpoint, **native)
        return endpoint

    def _register(
        self,
        method: str,
        path: str,
        options: Mapping[str, Any],
    ) -> Callable[[F], F]:
        described, native = _split(options)
        register = getattr(self.router, method)(path, **native)

        def decorate(endpoint: F) -> F:
            if described:
                openapi.attach(endpoint, **described)
            register(endpoint)
            return endpoint

        return decorate


def _split(options: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    described = {k: v for k, v in options.items() if k in _DESCRIBE_OPTIONS}
    native = {k: v for k, v in options.items() if k not in _DESCRIBE_OPTIONS}
    if 'fastapi_responses' in native:
        native['responses'] = native.pop('fastapi_responses')
    return described, native
