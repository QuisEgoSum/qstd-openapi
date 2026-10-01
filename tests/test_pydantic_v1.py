"""Pydantic 1 API: real Pydantic 1.10, or ``pydantic.v1`` inside Pydantic 2."""

from __future__ import annotations

import dataclasses
import enum

from typing import Any, Literal, Optional

import pytest

pydantic = pytest.importorskip('pydantic')
v1: Any
if pydantic.VERSION.startswith('1.'):
    v1 = pydantic
else:
    v1 = pytest.importorskip('pydantic.v1')

from openapi_spec_validator import validate  # noqa: E402

from qstd_openapi import OpenAPI, Routes, openapi  # noqa: E402
from qstd_openapi.pydantic import PydanticSchemas  # noqa: E402


class Role(enum.Enum):
    USER = 'user'
    ADMIN = 'admin'


@dataclasses.dataclass
class AddressDTO:
    city: str
    zip: Optional[str] = None


class UserDTO(v1.BaseModel):
    id: int
    role: Role
    kind: Literal['person'] = 'person'
    address: AddressDTO
    nickname: Optional[str] = None
    tags: list[str] = v1.Field(default_factory=list)


def build(*routes: Any) -> dict[str, Any]:
    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1'},
        schemas=[PydanticSchemas()],
    )
    spec.include(Routes(*routes))
    document = spec.build().document
    validate(document)
    return document


def test_v1_output_is_normalized() -> None:
    @openapi.response(UserDTO)
    async def get_user() -> None:
        pass

    document = build(('/users/{id}', 'get', get_user))
    schemas = document['components']['schemas']
    assert sorted(schemas) == ['AddressDTO', 'Role', 'UserDTO']
    assert schemas['Role'] == {
        'title': 'Role',
        'enum': ['user', 'admin'],
        'type': 'string',
    }
    user = schemas['UserDTO']['properties']
    assert user['kind'] == {
        'title': 'Kind',
        'default': 'person',
        'const': 'person',
        'type': 'string',
    }
    assert user['nickname'] == {
        'anyOf': [{'type': 'string'}, {'type': 'null'}],
        'title': 'Nickname',
        'default': None,
    }
    assert user['role'] == {'$ref': '#/components/schemas/Role'}
    assert schemas['AddressDTO']['properties']['zip']['anyOf'] == [
        {'type': 'string'},
        {'type': 'null'},
    ]
    assert document['paths']['/users/{id}']['get']['responses']['200']['content'] == {
        'application/json': {'schema': {'$ref': '#/components/schemas/UserDTO'}},
    }


def test_v1_generic_types() -> None:
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
    assert 'ParsingModel' not in str(document)


def test_repeated_builds_get_complete_components() -> None:
    """Pydantic 1 caches Model.schema(); editing it in place broke the second build."""

    @openapi.response(UserDTO)
    async def get_user() -> None:
        pass

    first = build(('/users/{id}', 'get', get_user))
    second = build(('/users/{id}', 'get', get_user))
    assert first == second
    assert sorted(second['components']['schemas']) == ['AddressDTO', 'Role', 'UserDTO']
