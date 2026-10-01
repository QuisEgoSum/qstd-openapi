"""Pydantic 2 provider (skipped when Pydantic 1 is installed)."""

from __future__ import annotations

import dataclasses
import datetime
import decimal

from typing import Any, Optional

import pytest

pydantic = pytest.importorskip('pydantic')
if pydantic.VERSION.startswith('1.'):
    pytest.skip('Pydantic 2 only', allow_module_level=True)

from openapi_spec_validator import validate  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from qstd_openapi import OpenAPI, Routes, openapi  # noqa: E402
from qstd_openapi.pydantic import PydanticSchemas  # noqa: E402


@dataclasses.dataclass
class AddressDTO:
    city: str
    balance: decimal.Decimal


@dataclasses.dataclass
class UserDTO:
    """A registered user."""

    id: int
    email: str
    created_at: datetime.datetime
    address: AddressDTO
    nickname: Optional[str] = None


class UserRegisterInput(BaseModel):
    email: str
    password: str
    address: AddressDTO


class UserRegisterOutput(BaseModel):
    status: str
    user: Optional[UserDTO] = None


class UserQuery(BaseModel):
    page: int = 1
    size: int = Field(20, description='Page size')


class AliasedDTO(BaseModel):
    user_id: int = Field(alias='userId')


def build(*routes: Any, **kwargs: Any) -> dict[str, Any]:
    spec = OpenAPI(info={'title': 'Users API', 'version': '1'}, **kwargs)
    spec.include(Routes(*routes))
    document = spec.build().document
    validate(document)
    return document


def test_pydantic_is_used_by_default_when_installed() -> None:
    spec = OpenAPI(info={'title': 'Users API', 'version': '1'})
    assert [type(p).__name__ for p in spec.schema_providers] == ['PydanticSchemas']


def test_models_and_dataclasses_become_components() -> None:
    @openapi.body(UserRegisterInput)
    @openapi.response(UserRegisterOutput, status=201)
    async def register_user() -> None:
        pass

    document = build(('/users', 'post', register_user))
    operation = document['paths']['/users']['post']
    assert operation['requestBody']['content']['application/json']['schema'] == {
        '$ref': '#/components/schemas/UserRegisterInput',
    }
    schemas = document['components']['schemas']
    # The dataclass with a Decimal differs between input and output modes.
    assert set(schemas) == {
        'UserRegisterInput',
        'UserRegisterOutput',
        'UserDTO',
        'AddressDTO-Input',
        'AddressDTO-Output',
    }
    assert schemas['AddressDTO-Output']['properties']['balance']['type'] == 'string'
    assert 'anyOf' in schemas['AddressDTO-Input']['properties']['balance']
    assert schemas['UserDTO']['properties']['nickname']['anyOf'] == [
        {'type': 'string'},
        {'type': 'null'},
    ]


def test_generic_response_types() -> None:
    @openapi.response(list[UserDTO])
    async def list_users() -> None:
        pass

    document = build(('/users', 'get', list_users))
    schema = document['paths']['/users']['get']['responses']['200']['content'][
        'application/json'
    ]['schema']
    assert schema == {
        'type': 'array',
        'items': {'$ref': '#/components/schemas/UserDTO'},
    }


def test_query_model_expands_into_parameters_and_is_not_a_component() -> None:
    @openapi.query(UserQuery)
    async def list_users() -> None:
        pass

    document = build(('/users', 'get', list_users))
    assert document['paths']['/users']['get']['parameters'] == [
        {'name': 'page', 'in': 'query', 'schema': {'default': 1, 'type': 'integer'}},
        {
            'name': 'size',
            'in': 'query',
            'description': 'Page size',
            'schema': {'default': 20, 'type': 'integer'},
        },
    ]
    assert 'components' not in document


def test_by_alias_setting() -> None:
    @openapi.response(AliasedDTO)
    async def handler() -> None:
        pass

    by_alias = build(('/x', 'get', handler))
    by_name = build(('/x', 'get', handler), schemas=[PydanticSchemas(by_alias=False)])
    assert list(by_alias['components']['schemas']['AliasedDTO']['properties']) == [
        'userId',
    ]
    assert list(by_name['components']['schemas']['AliasedDTO']['properties']) == [
        'user_id',
    ]


def test_same_model_from_two_operations_is_one_component() -> None:
    @openapi.response(UserDTO)
    async def get_user() -> None:
        pass

    @openapi.response(list[UserDTO])
    async def list_users() -> None:
        pass

    document = build(('/users/{id}', 'get', get_user), ('/users', 'get', list_users))
    assert sorted(document['components']['schemas']) == ['AddressDTO', 'UserDTO']


def test_type_adapter_instance_is_accepted_as_schema() -> None:
    """A ready ``TypeAdapter`` describes the same schema as the type it wraps."""
    from pydantic import TypeAdapter

    @openapi.response(TypeAdapter(list[UserDTO]))
    @openapi.body(TypeAdapter(UserRegisterInput))
    async def register_users() -> None:
        pass

    @openapi.response(list[UserDTO])
    @openapi.body(UserRegisterInput)
    async def register_users_by_type() -> None:
        pass

    by_adapter = build(('/users', 'post', register_users), operation_ids=None)
    by_type = build(('/users', 'post', register_users_by_type), operation_ids=None)
    assert by_adapter == by_type
    assert by_adapter['paths']['/users']['post']['requestBody']['content'][
        'application/json'
    ]['schema'] == {'$ref': '#/components/schemas/UserRegisterInput'}
