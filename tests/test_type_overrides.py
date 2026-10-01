"""``type_overrides``: the document describes what the project's serializer sends."""

from __future__ import annotations

import dataclasses
import datetime
import decimal

from typing import Any, Optional

import pytest

from openapi_spec_validator import validate

from qstd_openapi import OpenAPI, Routes, TypeOverride, openapi

NUMBER = {'type': 'number'}
AS_NUMBER_IN_DATACLASS_RESPONSES = TypeOverride(
    NUMBER,
    mode='serialization',
    within='dataclasses',
)


@dataclasses.dataclass
class WalletDTO:
    balance: decimal.Decimal
    history: list[decimal.Decimal]
    limit: Optional[decimal.Decimal] = None


def build(*routes: Any, **kwargs: Any) -> dict[str, Any]:
    spec = OpenAPI(info={'title': 'Users API', 'version': '1'}, **kwargs)
    spec.include(Routes(*routes))
    document = spec.build().document
    validate(document)
    return document


def response_schema(document: dict[str, Any], path: str, method: str) -> Any:
    response = document['paths'][path][method]['responses']['200']
    return response['content']['application/json']['schema']


def test_keys_must_be_classes() -> None:
    with pytest.raises(TypeError, match='must be classes'):
        OpenAPI(info={'title': 'Users API', 'version': '1'}, type_overrides={'x': {}})
    with pytest.raises(TypeError, match='TypeOverride'):
        OpenAPI(
            info={'title': 'Users API', 'version': '1'},
            type_overrides={decimal.Decimal: [NUMBER]},  # type: ignore[list-item]
        )


def test_builtin_types_without_pydantic() -> None:
    @openapi.response(list[Optional[decimal.Decimal]])
    @openapi.body(decimal.Decimal)
    async def update_balance() -> None:
        pass

    document = build(
        ('/balance', 'post', update_balance),
        schemas=(),
        type_overrides={decimal.Decimal: TypeOverride(NUMBER, mode='serialization')},
    )
    assert response_schema(document, '/balance', 'post') == {
        'type': 'array',
        'items': {'anyOf': [NUMBER, {'type': 'null'}]},
    }
    body = document['paths']['/balance']['post']['requestBody']
    assert body['content']['application/json']['schema'] == {
        'anyOf': [NUMBER, {'type': 'string'}],
    }


def test_within_applies_only_to_fields() -> None:
    @openapi.response(decimal.Decimal)
    async def get_balance() -> None:
        pass

    document = build(
        ('/balance', 'get', get_balance),
        schemas=(),
        type_overrides={decimal.Decimal: AS_NUMBER_IN_DATACLASS_RESPONSES},
    )
    assert response_schema(document, '/balance', 'get') == {'type': 'string'}


def test_first_applicable_override_wins() -> None:
    @openapi.response(datetime.datetime)
    @openapi.body(datetime.datetime)
    async def touch() -> None:
        pass

    document = build(
        ('/touch', 'post', touch),
        schemas=(),
        type_overrides={
            datetime.datetime: [
                TypeOverride({'type': 'integer'}, mode='serialization'),
                TypeOverride({'type': 'string'}),
            ],
        },
    )
    assert response_schema(document, '/touch', 'post') == {'type': 'integer'}
    body = document['paths']['/touch']['post']['requestBody']
    assert body['content']['application/json']['schema'] == {'type': 'string'}


class TestPydantic2:
    """A project serializer: models via ``model_dump(mode='json')``, dataclasses natively."""

    @pytest.fixture(autouse=True)
    def _pydantic2(self) -> None:
        pydantic = pytest.importorskip('pydantic')
        if pydantic.VERSION.startswith('1.'):
            pytest.skip('Pydantic 2 only')

    # The 3.0 rendering of an optional Decimal request field keeps
    # ``default: null`` next to ``anyOf`` + ``nullable``, which older
    # openapi-spec-validator releases reject; this test is about 3.1 only.
    @pytest.mark.no_shadow
    def test_dataclass_fields_differ_from_model_fields(self) -> None:
        from pydantic import BaseModel

        class UserDTO(BaseModel):
            id: int
            bonus: decimal.Decimal

        @openapi.response(WalletDTO)
        async def get_wallet() -> None:
            pass

        @openapi.response(UserDTO)
        async def get_user() -> None:
            pass

        @openapi.body(WalletDTO)
        async def put_wallet() -> None:
            pass

        document = build(
            ('/wallet', 'get', get_wallet),
            ('/wallet', 'put', put_wallet),
            ('/user', 'get', get_user),
            type_overrides={decimal.Decimal: AS_NUMBER_IN_DATACLASS_RESPONSES},
        )
        schemas = document['components']['schemas']
        wallet = schemas['WalletDTO-Output']['properties']
        assert wallet['balance'] == {**NUMBER, 'title': 'Balance'}
        assert wallet['history']['items'] == NUMBER
        assert wallet['limit']['anyOf'] == [NUMBER, {'type': 'null'}]
        # Requests and model fields keep the Pydantic schema.
        assert 'anyOf' in schemas['WalletDTO-Input']['properties']['balance']
        assert schemas['UserDTO']['properties']['bonus']['type'] == 'string'

    def test_plain_schema_applies_everywhere(self) -> None:
        from pydantic import BaseModel

        class UserDTO(BaseModel):
            id: int
            bonus: decimal.Decimal

        @openapi.response(UserDTO)
        @openapi.body(UserDTO)
        async def update_user() -> None:
            pass

        document = build(
            ('/user', 'put', update_user),
            type_overrides={decimal.Decimal: NUMBER},
        )
        schemas = document['components']['schemas']
        assert list(schemas) == ['UserDTO']
        assert schemas['UserDTO']['properties']['bonus'] == {**NUMBER, 'title': 'Bonus'}

    def test_class_key_replaces_the_component_body(self) -> None:
        from pydantic import BaseModel

        class UserDTO(BaseModel):
            wallet: WalletDTO
            wallets: list[WalletDTO]

        @openapi.response(UserDTO)
        async def get_user() -> None:
            pass

        opaque = {'type': 'object', 'description': 'Wallet, see the billing API'}
        document = build(('/user', 'get', get_user), type_overrides={WalletDTO: opaque})
        schemas = document['components']['schemas']
        assert schemas['WalletDTO'] == opaque
        assert schemas['UserDTO']['properties']['wallet'] == {
            '$ref': '#/components/schemas/WalletDTO',
        }


class TestPydantic1:
    @pytest.fixture
    def v1(self) -> Any:
        pydantic = pytest.importorskip('pydantic')
        if pydantic.VERSION.startswith('1.'):
            return pydantic
        return pytest.importorskip('pydantic.v1')

    def test_model_and_dataclass_fields(self, v1: Any) -> None:
        class UserDTO(v1.BaseModel):  # type: ignore[name-defined, misc]
            bonus: decimal.Decimal
            wallet: WalletDTO

        @openapi.response(UserDTO)
        async def get_user() -> None:
            pass

        @openapi.body(UserDTO)
        async def put_user() -> None:
            pass

        document = build(
            ('/user', 'get', get_user),
            ('/user', 'put', put_user),
            type_overrides={
                decimal.Decimal: [
                    AS_NUMBER_IN_DATACLASS_RESPONSES,
                    TypeOverride({'type': 'string'}, mode='serialization'),
                ],
            },
        )
        schemas = document['components']['schemas']
        assert sorted(schemas) == [
            'UserDTO',
            'UserDTO-Output',
            'WalletDTO',
            'WalletDTO-Output',
        ]
        wallet = schemas['WalletDTO-Output']['properties']
        assert wallet['balance'] == {**NUMBER, 'title': 'Balance'}
        assert wallet['history']['items'] == NUMBER
        assert wallet['limit']['anyOf'] == [NUMBER, {'type': 'null'}]
        user = schemas['UserDTO-Output']['properties']
        assert user['bonus'] == {'type': 'string', 'title': 'Bonus'}
        assert user['wallet'] == {'$ref': '#/components/schemas/WalletDTO-Output'}
        # Requests keep Pydantic 1's own schema.
        assert schemas['UserDTO']['properties']['bonus']['type'] == 'number'
        assert response_schema(document, '/user', 'get') == {
            '$ref': '#/components/schemas/UserDTO-Output',
        }
