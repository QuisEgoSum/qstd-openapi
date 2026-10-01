from __future__ import annotations

import dataclasses
import decimal

from typing import Any, Optional

import pytest

fastapi = pytest.importorskip('fastapi')
pydantic = pytest.importorskip('pydantic')
if pydantic.VERSION.startswith('1.'):
    pytest.skip('Pydantic 2 only', allow_module_level=True)

from fastapi import APIRouter, Depends, FastAPI, Response  # noqa: E402
from fastapi.security import APIKeyCookie  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from openapi_spec_validator import validate  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from qstd_openapi import OpenAPI, ScopeFilter, WebhookSet, openapi  # noqa: E402
from qstd_openapi.contrib.app_errors import AppErrors  # noqa: E402
from qstd_openapi.errors import ComponentConflictError  # noqa: E402
from qstd_openapi.fastapi import OpenAPIRouter, augment, merged_document  # noqa: E402


class ApplicationError(Exception):
    message: str
    code: int


class ConflictError(ApplicationError):
    pass


class NotFoundError(ApplicationError):
    pass


class UserAlreadyExistsError(ConflictError):
    message = 'User already exists'
    code = 1


class UserNotFoundError(NotFoundError):
    message = 'User not found'
    code = 2


@dataclasses.dataclass
class AddressDTO:
    city: str
    balance: decimal.Decimal


class UserRegisterInput(BaseModel):
    email: str
    address: AddressDTO


class UserDTO(BaseModel):
    id: int
    address: AddressDTO
    nickname: Optional[str] = None


class UserRegisteredEvent(BaseModel):
    user_id: int


session_cookie = APIKeyCookie(name='sid')


def new_spec(**kwargs: Any) -> OpenAPI:
    return OpenAPI(
        info={'title': 'Users API', 'version': '1.0.0'},
        errors=[
            AppErrors(
                ApplicationError,
                status_by_class={ConflictError: 409, NotFoundError: 404},
            ),
        ],
        **kwargs,
    )


def new_app() -> tuple[Any, Any]:
    app = FastAPI(title='Users API', version='1.0.0')
    users = OpenAPIRouter(APIRouter(prefix='/users', tags=['Users']))

    @users.post(
        '/register',
        response_model=UserDTO,
        status_code=201,
        errors=[UserAlreadyExistsError],
        summary='Register a user',
    )
    async def register_user(body: UserRegisterInput) -> Any:
        """Creates the account."""

    @users.get('/{user_id}', response_model=UserDTO)
    @openapi.errors(UserNotFoundError)
    async def get_user(user_id: int, sid: str = Depends(session_cookie)) -> Any:
        pass

    # Older FastAPI infers a response model from the string annotation
    # (``from __future__ import annotations``) and rejects it for 204.
    @users.delete(
        '/{user_id}',
        status_code=204,
        response_class=Response,
        response_model=None,
    )
    @openapi.exclude()
    async def delete_user(user_id: int) -> None:
        pass

    @app.get('/health', include_in_schema=False)
    async def health() -> dict[str, str]:
        return {'status': 'ok'}

    app.include_router(users.router)
    return app, users


def test_fastapi_document_is_augmented() -> None:
    app, _ = new_app()
    augment(app, new_spec())
    document = app.openapi()
    validate(document)

    assert sorted(document['paths']) == ['/users/register', '/users/{user_id}']
    register = document['paths']['/users/register']['post']
    assert register['tags'] == ['Users']
    assert register['summary'] == 'Register a user'
    assert register['description'] == 'Creates the account.'
    assert register['operationId'] == 'register_user_users_register_post'
    assert list(register['responses']) == ['201', '409', '422']
    assert register['responses']['409']['content']['application/json']['schema'] == {
        '$ref': '#/components/schemas/UserAlreadyExistsError',
    }

    get_user = document['paths']['/users/{user_id}']['get']
    assert get_user['parameters'][0]['schema'] == {
        'type': 'integer',
        'title': 'User Id',
    }
    assert get_user['security'] == [{'APIKeyCookie': []}]
    assert list(get_user['responses']) == ['200', '404', '422']

    schemas = document['components']['schemas']
    assert {
        'UserDTO',
        'AddressDTO-Input',
        'AddressDTO-Output',
        'HTTPValidationError',
    } <= set(
        schemas,
    )
    assert 'UserAlreadyExistsError' in schemas


def test_explicit_library_values_win_but_fastapi_fills_the_rest() -> None:
    app = FastAPI(title='Users API', version='1.0.0')

    @app.get('/users', response_model=list[UserDTO], summary='FastAPI summary')
    @openapi.summary('Library summary')
    @openapi.response(UserDTO, status=200, description='Library description')
    @openapi.extra({'x-internal': True})
    async def list_users() -> Any:
        pass

    augment(app, new_spec())
    operation = app.openapi()['paths']['/users']['get']
    assert operation['summary'] == 'Library summary'
    assert operation['x-internal'] is True
    assert operation['responses']['200']['description'] == 'Library description'
    assert operation['responses']['200']['content']['application/json']['schema'] == {
        '$ref': '#/components/schemas/UserDTO',
    }


def test_scopes_and_webhooks_apply() -> None:
    app, _ = new_app()
    webhooks = WebhookSet()

    @webhooks.register('user.registered', scope='client')
    @openapi.body(UserRegisteredEvent)
    async def send_user_registered() -> None:
        pass

    @app.get('/admin/stats')
    @openapi.scope('admin')
    async def stats() -> dict[str, int]:
        return {}

    client_spec = new_spec(scopes=ScopeFilter(include={'client'}))
    client_spec.include(webhooks)
    document = merged_document(app, client_spec)
    validate(document)
    assert '/admin/stats' not in document['paths']
    assert list(document['webhooks']) == ['user.registered']

    admin = merged_document(app, new_spec(scopes=ScopeFilter(include={'admin'})))
    assert '/admin/stats' in admin['paths']
    assert 'webhooks' not in admin


def test_component_conflicts_are_detected() -> None:
    app = FastAPI(title='Users API', version='1.0.0')

    def other_user_dto() -> type:
        class UserDTO(BaseModel):  # same name, different fields
            other: str

        return UserDTO

    Shadow = other_user_dto()

    @app.get('/a', response_model=UserDTO)
    async def first() -> Any:
        pass

    @app.get('/b')
    @openapi.response(Shadow)
    async def second() -> Any:
        pass

    with pytest.raises(ComponentConflictError, match='UserDTO'):
        merged_document(app, new_spec())


def test_openapi_endpoint_serves_the_merged_document_and_caches_it() -> None:
    app, _ = new_app()
    augment(app, new_spec())
    client: Any = TestClient(app)
    body = client.get('/openapi.json').json()
    assert '409' in body['paths']['/users/register']['post']['responses']
    assert app.openapi() is app.openapi()


def test_router_wrapper_options() -> None:
    app = FastAPI(title='Users API', version='1.0.0')
    router = OpenAPIRouter(APIRouter())
    assert router.prefix == ''

    @router.get(
        '/items/{item_id}',
        tags=['Items'],
        operation_id='get_item',
        responses={404: None},
        fastapi_responses={418: {'description': 'Teapot'}},
        name='item',
    )
    async def get_item(item_id: int) -> dict[str, int]:
        return {'item_id': item_id}

    app.include_router(router.router)
    augment(app, new_spec())
    operation = app.openapi()['paths']['/items/{item_id}']['get']
    assert operation['tags'] == ['Items']
    assert operation['operationId'] == 'get_item'
    assert set(operation['responses']) == {'200', '404', '418', '422'}
    assert app.url_path_for('item', item_id=1) == '/items/1'


@pytest.mark.no_shadow
def test_validate_checks_the_merged_document() -> None:
    from qstd_openapi.errors import InvalidDocumentError

    app = FastAPI(title='Users API', version='1.0.0')

    @app.get('/users/me')
    @openapi.extra({'responses': {'200': {'content': 'not a mapping'}}})
    async def me() -> dict[str, int]:
        return {}

    valid = FastAPI(title='Users API', version='1.0.0')

    @valid.get('/users/me')
    async def valid_me() -> dict[str, int]:
        return {}

    assert merged_document(valid, new_spec(validate=True))['paths']
    with pytest.raises(InvalidDocumentError):
        merged_document(app, new_spec(validate=True))
