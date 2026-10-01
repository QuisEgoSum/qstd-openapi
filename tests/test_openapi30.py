from __future__ import annotations

import dataclasses
import decimal
import enum

from typing import Any, Literal, Optional

import pytest

from openapi_spec_validator import validate

from qstd_openapi import Document, OpenAPI, Routes, WebhookSet, openapi
from qstd_openapi.contrib.app_errors import AppErrors
from qstd_openapi.dialects import OpenAPI30
from qstd_openapi.dialects.openapi30 import convert_schema

REF = {'$ref': '#/components/schemas/User'}


@pytest.mark.parametrize(
    ('schema', 'expected'),
    [
        (
            {
                'anyOf': [{'type': 'string'}, {'type': 'null'}],
                'title': 'Nick',
                'default': None,
            },
            {'type': 'string', 'title': 'Nick', 'default': None, 'nullable': True},
        ),
        ({'anyOf': [REF, {'type': 'null'}]}, {'allOf': [REF], 'nullable': True}),
        (
            {'anyOf': [REF, {'type': 'null'}], 'default': None, 'title': 'Owner'},
            {'allOf': [REF], 'title': 'Owner', 'nullable': True},
        ),
        (
            {'anyOf': [{'type': 'string'}, {'type': 'integer'}, {'type': 'null'}]},
            {'anyOf': [{'type': 'string'}, {'type': 'integer'}], 'nullable': True},
        ),
        ({'type': ['string', 'null']}, {'type': 'string', 'nullable': True}),
        (
            {'type': ['string', 'integer']},
            {'anyOf': [{'type': 'string'}, {'type': 'integer'}]},
        ),
        ({'const': 'person', 'type': 'string'}, {'type': 'string', 'enum': ['person']}),
        ({'enum': ['a', None]}, {'enum': ['a'], 'nullable': True}),
        (
            {'type': 'string', 'examples': ['x', 'y']},
            {'type': 'string', 'example': 'x'},
        ),
        (
            {'type': 'number', 'exclusiveMinimum': 0, 'exclusiveMaximum': 10},
            {
                'type': 'number',
                'minimum': 0,
                'exclusiveMinimum': True,
                'maximum': 10,
                'exclusiveMaximum': True,
            },
        ),
        (
            {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True},
            {'type': 'number', 'minimum': 0, 'exclusiveMinimum': True},
        ),
        (
            {'$ref': REF['$ref'], 'description': 'Owner'},
            {'allOf': [REF], 'description': 'Owner'},
        ),
        (
            {
                'type': 'array',
                'prefixItems': [{'type': 'string'}, {'type': 'integer'}],
                'minItems': 2,
            },
            {
                'type': 'array',
                'minItems': 2,
                'items': {'anyOf': [{'type': 'string'}, {'type': 'integer'}]},
            },
        ),
        (
            {
                'type': 'string',
                'contentMediaType': 'image/png',
                '$comment': 'x',
                'if': {},
            },
            {'type': 'string'},
        ),
        (
            {
                'type': 'object',
                'properties': {'tags': {'type': 'array', 'items': {'const': 1}}},
                'additionalProperties': {'type': ['integer', 'null']},
            },
            {
                'type': 'object',
                'properties': {'tags': {'type': 'array', 'items': {'enum': [1]}}},
                'additionalProperties': {'type': 'integer', 'nullable': True},
            },
        ),
    ],
)
def test_schema_conversion(schema: dict[str, Any], expected: dict[str, Any]) -> None:
    assert convert_schema(schema) == expected


def test_version_guard() -> None:
    with pytest.raises(ValueError, match=r'3\.1\.0'):
        OpenAPI30('3.1.0')


class Role(enum.Enum):
    USER = 'user'
    ADMIN = 'admin'


class ApplicationError(Exception):
    message: str
    code: int


class UserAlreadyExistsError(ApplicationError):
    message = 'User already exists'
    code = 1
    status_code = 409
    roles: list[Role]


@dataclasses.dataclass
class UserDTO:
    id: int
    role: Role
    balance: decimal.Decimal
    kind: Literal['person'] = 'person'
    nickname: Optional[str] = None


def build(*sources: Any, **kwargs: Any) -> dict[str, Any]:
    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1', 'summary': '3.1 only'},
        dialect=OpenAPI30(),
        errors=[AppErrors(ApplicationError)],
        **kwargs,
    )
    spec.include(*sources)
    document = spec.build().document
    validate(document)
    return document


def test_full_document_in_3_0() -> None:
    pytest.importorskip('pydantic')

    @openapi.response(UserDTO, status=201)
    @openapi.errors(UserAlreadyExistsError)
    @openapi.body_form_data_file('avatar')
    async def register_user() -> None:
        pass

    webhooks = WebhookSet()

    @webhooks.register('user.registered')
    @openapi.body(UserDTO)
    async def send_user_registered() -> None:
        pass

    document = build(Routes(('/users', 'post', register_user)), webhooks)
    assert document['openapi'] == '3.0.3'
    assert 'summary' not in document['info']
    assert 'webhooks' not in document
    hook = document['x-webhooks']['user.registered']['post']
    assert hook['responses'] == {'200': {'description': 'OK'}}

    schemas = document['components']['schemas']
    user = schemas['UserDTO']['properties']
    assert user['nickname'] == {
        'type': 'string',
        'nullable': True,
        'title': 'Nickname',
        'default': None,
    }
    assert user['kind']['enum'] == ['person']
    assert user['role'] == {'$ref': '#/components/schemas/Role'}
    error = schemas['UserAlreadyExistsError']['properties']
    assert error['code'] == {'type': 'integer', 'enum': [1]}

    body = document['paths']['/users']['post']['requestBody']['content'][
        'multipart/form-data'
    ]
    assert body['schema']['properties']['avatar'] == {
        'type': 'string',
        'format': 'binary',
        'description': 'File',
    }


def test_operations_without_responses_get_a_default() -> None:
    document = OpenAPI30().finalize(
        {'info': {'title': 't', 'version': '1'}, 'paths': {'/x': {'get': {}}}},
        {},
    )
    validate(document)
    assert document['paths']['/x']['get']['responses'] == {
        'default': {'description': 'Default response'},
    }


def test_including_3_0_and_3_1_documents() -> None:
    legacy = {
        'openapi': '3.0.3',
        'info': {'title': 'Legacy', 'version': '1'},
        'paths': {
            '/items': {
                'get': {
                    'responses': {
                        '200': {
                            'description': 'OK',
                            'content': {
                                'application/json': {
                                    'schema': {'type': 'string', 'nullable': True},
                                },
                            },
                        },
                    },
                },
            },
        },
        'x-webhooks': {
            'item.created': {'post': {'responses': {'200': {'description': 'OK'}}}},
        },
    }
    modern = {
        'openapi': '3.1.0',
        'info': {'title': 'Modern', 'version': '1'},
        'paths': {
            '/things': {
                'get': {
                    'responses': {
                        '200': {
                            'description': 'OK',
                            'content': {
                                'application/json': {
                                    'schema': {'type': ['string', 'null']},
                                },
                            },
                        },
                    },
                },
            },
        },
    }
    document = build(
        Document(legacy, origin='legacy', path_prefix='/legacy'),
        Document(modern, origin='modern', path_prefix='/modern'),
        schemas=(),
    )
    schema = document['paths']['/modern/things']['get']['responses']['200']['content']
    assert schema['application/json']['schema'] == {'type': 'string', 'nullable': True}
    assert list(document['x-webhooks']) == ['item.created']


def test_fastapi_in_3_0() -> None:
    pytest.importorskip('fastapi')
    pydantic = pytest.importorskip('pydantic')
    if pydantic.VERSION.startswith('1.'):
        pytest.skip('Pydantic 2 only')
    from fastapi import FastAPI
    from pydantic import BaseModel

    from qstd_openapi.fastapi import augment

    class ProfileDTO(BaseModel):
        nickname: Optional[str] = None

    app = FastAPI(title='Users API', version='1')

    @app.get('/profile', response_model=ProfileDTO)
    @openapi.errors(UserAlreadyExistsError)
    async def profile() -> Any:
        pass

    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1'},
        dialect=OpenAPI30(),
        errors=[AppErrors(ApplicationError)],
    )
    augment(app, spec)
    document = app.openapi()
    validate(document)
    assert document['openapi'] == '3.0.3'
    assert document['components']['schemas']['ProfileDTO']['properties']['nickname'][
        'nullable'
    ]
    assert '409' in document['paths']['/profile']['get']['responses']
