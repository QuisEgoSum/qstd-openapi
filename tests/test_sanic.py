from __future__ import annotations

import asyncio
import functools
import itertools
import json

from typing import Any, Callable, Optional, TypeVar

import pytest

sanic = pytest.importorskip('sanic')
pydantic = pytest.importorskip('pydantic')
if pydantic.VERSION.startswith('1.'):
    pytest.skip('Pydantic 2 only', allow_module_level=True)

from openapi_spec_validator import validate  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sanic import Blueprint, Sanic, response  # noqa: E402
from sanic.views import HTTPMethodView  # noqa: E402

from qstd_openapi import OpenAPI, openapi  # noqa: E402
from qstd_openapi.contrib.app_errors import AppErrors  # noqa: E402
from qstd_openapi.sanic import OpenAPIBlueprint, SanicRoutes, mount  # noqa: E402

F = TypeVar('F', bound=Callable[..., Any])
_names = itertools.count()


# --- a tiny "project": errors, models, middlewares ---------------------------


class ApplicationError(Exception):
    message: str
    code: int


class AuthenticationError(ApplicationError):
    pass


class ConflictError(ApplicationError):
    pass


class ValidationError(ApplicationError):
    pass


class UnauthorizedError(AuthenticationError):
    message = 'Unauthorized'
    code = 1


class UserAlreadyExistsError(ConflictError):
    message = 'User already exists'
    code = 2


class SchemaValidationError(ValidationError):
    message = 'Validation errors'
    code = 3


STATUSES = {AuthenticationError: 401, ConflictError: 409, ValidationError: 400}


class UserRegisterInput(BaseModel):
    email: str
    password: str


class UserDTO(BaseModel):
    id: int
    email: str


def require_session() -> Callable[[F], F]:
    """Middleware documenting itself on the wrapper, before ``wraps``."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        @openapi.security('UserSession')
        @openapi.errors(UnauthorizedError)
        async def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
            return await func(request, *args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def validate_body(model: type) -> Callable[[F], F]:
    """Validator documenting the body via ``attach``."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
            return await func(request, *args, body=model(**request.json), **kwargs)

        return openapi.attach(  # type: ignore[return-value]
            wrapper,
            body=model,
            errors=[SchemaValidationError],
        )

    return decorator


def new_app() -> Any:
    return Sanic(f'test_app_{next(_names)}')


def new_spec(**kwargs: Any) -> OpenAPI:
    return OpenAPI(
        info={'title': 'Users API', 'version': '1.0.0'},
        security_schemes={
            'UserSession': {'type': 'apiKey', 'in': 'cookie', 'name': 'sid'},
        },
        errors=[AppErrors(ApplicationError, status_by_class=STATUSES)],
        **kwargs,
    )


def document_of(app: Any, **kwargs: Any) -> dict[str, Any]:
    spec = new_spec(**kwargs)
    spec.include(SanicRoutes(app))
    document = spec.build().document
    validate(document)
    return document


def ok(_: Any = None, **__: Any) -> Any:
    return response.json({})


# --- route source ------------------------------------------------------------


def test_routes_paths_parameters_and_blueprint_tags() -> None:
    app = new_app()
    users = Blueprint('Users', url_prefix='/users')

    @users.get('/<user_id:int>')
    @openapi.response(UserDTO)
    async def get_user(request: Any, user_id: int) -> Any:
        return ok()

    @users.get('/by-key/<key:uuid>/<day:ymd>/<slug:slug>')
    @openapi.tag('Lookup')
    async def lookup(request: Any, **_: Any) -> Any:
        return ok()

    @app.get('/health')
    async def health(request: Any) -> Any:
        return ok()

    app.blueprint(users)
    document = document_of(app)
    assert sorted(document['paths']) == [
        '/health',
        '/users/by-key/{key}/{day}/{slug}',
        '/users/{user_id}',
    ]
    get_user_op = document['paths']['/users/{user_id}']['get']
    assert get_user_op['tags'] == ['Users']
    assert get_user_op['parameters'] == [
        {
            'name': 'user_id',
            'in': 'path',
            'required': True,
            'schema': {'type': 'integer'},
        },
    ]
    lookup_op = document['paths']['/users/by-key/{key}/{day}/{slug}']['get']
    assert lookup_op['tags'] == ['Lookup']
    assert [p['schema'] for p in lookup_op['parameters']] == [
        {'format': 'uuid', 'type': 'string'},
        {'format': 'date', 'type': 'string'},
        {'type': 'string'},
    ]
    assert 'tags' not in document['paths']['/health']['get']


def test_blueprint_tags_can_be_disabled() -> None:
    app = new_app()
    users = Blueprint('Users', url_prefix='/users')
    users.add_route(ok, '/')
    app.blueprint(users)
    spec = new_spec()
    spec.include(SanicRoutes(app, blueprint_tags=False))
    assert 'tags' not in spec.build().document['paths']['/users']['get']


def test_class_based_views_static_websockets_and_strict_slashes() -> None:
    app = new_app()

    class ItemView(HTTPMethodView):
        @openapi.response(UserDTO)
        async def get(self, request: Any, item_id: str) -> Any:
            return ok()

        @openapi.no_content()
        async def delete(self, request: Any, item_id: str) -> Any:
            return ok()

    app.add_route(ItemView.as_view(), '/items/<item_id>')

    @app.post('/users', strict_slashes=False)
    async def create(request: Any) -> Any:
        return ok()

    @app.websocket('/ws')
    async def feed(request: Any, ws: Any) -> None:
        pass

    app.static('/static', '.')
    document = document_of(app)
    assert sorted(document['paths']) == ['/items/{item_id}', '/users']
    item = document['paths']['/items/{item_id}']
    assert list(item) == ['get', 'delete']
    assert list(item['delete']['responses']) == ['204']


def test_middlewares_and_validators_document_themselves() -> None:
    app = new_app()
    users = Blueprint('Users', url_prefix='/users')

    @users.post('/register')
    @openapi.tag('Users')
    @openapi.errors(UserAlreadyExistsError)
    @openapi.response(UserDTO, status=201)
    @validate_body(UserRegisterInput)
    @require_session()
    async def register_user(request: Any, body: UserRegisterInput) -> Any:
        """Register a user."""
        return ok()

    app.blueprint(users)
    operation = document_of(app)['paths']['/users/register']['post']
    assert operation['summary'] == 'Register a user.'
    assert operation['security'] == [{'UserSession': []}]
    assert operation['requestBody']['content']['application/json']['schema'] == {
        '$ref': '#/components/schemas/UserRegisterInput',
    }
    assert sorted(operation['responses']) == ['201', '400', '401', '409']


# --- the three ways to describe the same operation ---------------------------


def test_decorators_describe_and_router_wrapper_give_the_same_operation() -> None:
    def build(register: Callable[[Any], None]) -> dict[str, Any]:
        app = new_app()
        users = Blueprint('Users', url_prefix='/users')
        register(users)
        app.blueprint(users)
        return document_of(app)['paths']['/users/register']['post']

    def with_decorators(users: Any) -> None:
        @users.post('/register')
        @openapi.tag('Users')
        @openapi.errors(UserAlreadyExistsError)
        @openapi.response(UserDTO, status=201)
        @openapi.body(UserRegisterInput)
        async def register_user(request: Any) -> Any:
            return ok()

    def with_describe(users: Any) -> None:
        @users.post('/register')
        @openapi.describe(
            tags=['Users'],
            errors=[UserAlreadyExistsError],
            responses={201: UserDTO},
            body=UserRegisterInput,
        )
        async def register_user(request: Any) -> Any:
            return ok()

    def with_router(users: Any) -> None:
        router = OpenAPIBlueprint(users)

        @router.post(
            '/register',
            tags=['Users'],
            errors=[UserAlreadyExistsError],
            responses={201: UserDTO},
            body=UserRegisterInput,
        )
        async def register_user(request: Any) -> Any:
            return ok()

    assert build(with_decorators) == build(with_describe) == build(with_router)


# --- router wrapper ----------------------------------------------------------


def test_router_wrapper_passes_sanic_options_through() -> None:
    app = new_app()
    router = OpenAPIBlueprint(Blueprint('Users', url_prefix='/users'))
    assert router.url_prefix == '/users'

    @router.get('/<user_id:int>', name='get_user_by_id', summary='Get a user')
    async def get_user(request: Any, user_id: int) -> Any:
        return ok()

    class ProfileView(HTTPMethodView):
        async def get(self, request: Any) -> Any:
            return ok()

    router.add_route(ProfileView.as_view(), '/me', methods=['GET'], tags=['Profile'])
    app.blueprint(router.blueprint)

    assert app.url_for('Users.get_user_by_id', user_id=1) == '/users/1'
    paths = document_of(app)['paths']
    assert paths['/users/{user_id}']['get']['summary'] == 'Get a user'
    assert paths['/users/me']['get']['tags'] == ['Profile']


def test_router_wrapper_ctx_option_becomes_route_context() -> None:
    app = new_app()
    router = OpenAPIBlueprint(Blueprint('Users', url_prefix='/users'))

    @router.get('/me', name='me', ctx={'auth': False})
    async def me(request: Any) -> Any:
        return ok()

    app.blueprint(router.blueprint)
    app.router.finalize()
    route = next(r for r in app.router.routes if r.name.endswith('.me'))
    assert route.ctx.auth is False


def test_operation_ids_from_route_names() -> None:
    app = new_app()
    users = Blueprint('Users', url_prefix='/users')

    @users.get('/me')
    async def me(request: Any) -> Any:
        return ok()

    @users.route('/avatar', methods=['PUT', 'DELETE'], name='avatar')
    async def change_avatar(request: Any) -> Any:
        return ok()

    class ProfileView(HTTPMethodView):
        async def get(self, request: Any) -> Any:
            return ok()

        async def patch(self, request: Any) -> Any:
            return ok()

    users.add_route(ProfileView.as_view(), '/profile')

    @app.get('/health', name='health_check')
    async def health(request: Any) -> Any:
        return ok()

    app.blueprint(users)
    document = document_of(app)
    found = {
        f'{method.upper()} {path}': operation['operationId']
        for path, item in document['paths'].items()
        for method, operation in item.items()
    }
    assert found == {
        'GET /users/me': 'Users_me',
        'PUT /users/avatar': 'Users_avatar_put',
        'DELETE /users/avatar': 'Users_avatar_delete',
        'GET /users/profile': 'Users_ProfileView_get',
        'PATCH /users/profile': 'Users_ProfileView_patch',
        'GET /health': 'health_check',
    }


# --- publishing --------------------------------------------------------------


def _get(app: Any, path: str) -> tuple[int, Optional[Any]]:
    async def call() -> tuple[int, Optional[Any]]:
        _, result = await app.asgi_client.get(path)
        body = json.loads(result.body) if result.status == 200 else None
        return result.status, body

    return asyncio.run(call())


def test_mount_publishes_the_document() -> None:
    app = new_app()

    @app.get('/users')
    @openapi.response(UserDTO)
    async def list_users(request: Any) -> Any:
        return ok()

    spec = new_spec()
    spec.include(SanicRoutes(app))
    mount(app, spec, json_path='/openapi.json')

    status, body = _get(app, '/openapi.json')
    assert status == 200
    assert body is not None
    assert list(body['paths']) == ['/users']  # the endpoint itself is excluded
    validate(body)


def test_mount_decorators_protect_the_endpoint() -> None:
    app = new_app()

    def deny(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(request: Any, *args: Any, **kwargs: Any) -> Any:
            return response.json({}, status=401)

        return wrapper  # type: ignore[return-value]

    spec = new_spec()
    spec.include(SanicRoutes(app))
    mount(app, spec, decorators=[deny], build_on_start=False)
    assert _get(app, '/openapi.json') == (401, None)
    assert spec.build().document['paths'] == {}


def test_mount_yaml_and_documentation_pages() -> None:
    pytest.importorskip('yaml')
    from qstd_openapi.ui import Redoc, SwaggerUI

    app = new_app()

    @app.get('/users')
    @openapi.response(UserDTO)
    async def list_users(request: Any) -> Any:
        return ok()

    spec = new_spec()
    spec.include(SanicRoutes(app))
    mount(
        app,
        spec,
        yaml_path='/openapi.yaml',
        ui={'/docs': Redoc(), '/swagger': SwaggerUI()},
        spec_url='/api/openapi.json',
    )

    async def fetch(path: str) -> tuple[int, str, str]:
        _, result = await app.asgi_client.get(path)
        return result.status, result.headers.get('content-type'), result.text

    status, content_type, text = asyncio.run(fetch('/openapi.yaml'))
    assert (status, content_type) == (200, 'application/yaml')
    assert text.startswith('openapi: 3.1.0')
    status, content_type, text = asyncio.run(fetch('/docs'))
    assert (status, content_type) == (200, 'text/html; charset=utf-8')
    assert 'Redoc.init("/api/openapi.json"' in text
    assert '<title>Users API</title>' in text
    assert asyncio.run(fetch('/swagger'))[0] == 200
    # Documentation endpoints are not documented themselves.
    assert list(spec.build().document['paths']) == ['/users']
