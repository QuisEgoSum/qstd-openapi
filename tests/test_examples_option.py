"""``examples=`` for request bodies, responses and parameters."""

from __future__ import annotations

from typing import Any

import pytest

from openapi_spec_validator import validate

from qstd_openapi import OpenAPI, Routes, ScalarConflictError, openapi
from qstd_openapi.dialects import OpenAPI30

USER = {'type': 'object', 'properties': {'email': {'type': 'string'}}}
ALICE = {'email': 'alice@example.com'}


def build(handler: Any, **kwargs: Any) -> dict[str, Any]:
    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1.0.0'},
        schemas=(),
        **kwargs,
    )
    spec.include(Routes(('/users', 'post', handler)))
    document = spec.build().document
    validate(document)
    return document['paths']['/users']['post']


def test_decorators() -> None:
    @openapi.body(USER, examples={'alice': ALICE})
    @openapi.response(
        USER,
        status=201,
        examples={'created': openapi.Example(ALICE, summary='A new user')},
    )
    @openapi.query('invite', str, examples={'code': 'X1'})
    async def register_user() -> None:
        pass

    operation = build(register_user)
    body = operation['requestBody']['content']['application/json']
    assert body == {'schema': USER, 'examples': {'alice': {'value': ALICE}}}
    response = operation['responses']['201']['content']['application/json']
    assert response['examples'] == {
        'created': {'summary': 'A new user', 'value': ALICE},
    }
    assert operation['parameters'][0]['examples'] == {'code': {'value': 'X1'}}


def test_describe_and_several_sources_accumulate() -> None:
    @openapi.describe(
        body=USER,
        body_examples={'alice': ALICE},
        responses={201: USER, 409: None},
        response_examples={201: {'alice': ALICE}},
    )
    @openapi.body_one_of(USER, {'type': 'string'}, examples={'raw': 'alice'})
    @openapi.responses(USER, status=201, examples={'bob': {'email': 'bob@example.com'}})
    async def register_user() -> None:
        pass

    operation = build(register_user)
    body = operation['requestBody']['content']['application/json']
    assert list(body['examples']) == ['raw', 'alice']
    response = operation['responses']['201']['content']['application/json']
    assert list(response['examples']) == ['bob', 'alice']


def test_examples_without_a_schema() -> None:
    @openapi.describe(response_examples={200: {'empty': []}})
    async def list_users() -> None:
        pass

    content = build(list_users)['responses']['200']['content']['application/json']
    assert content == {'examples': {'empty': {'value': []}}}


def test_one_name_with_different_values_is_a_conflict() -> None:
    @openapi.body(USER, examples={'user': ALICE})
    @openapi.body(USER, examples={'user': {'email': 'bob@example.com'}})
    async def register_user() -> None:
        pass

    with pytest.raises(ScalarConflictError, match="examples"):
        build(register_user)
    assert build(register_user, scalar_conflicts='last_wins')['requestBody']


def test_model_parameters_reject_examples() -> None:
    with pytest.raises(TypeError, match='one parameter'):
        openapi.query(USER, examples={'x': 1})


def test_openapi30_keeps_media_type_examples() -> None:
    @openapi.body(USER, examples={'alice': ALICE})
    @openapi.header('X-Invite', examples={'code': 'X1'})
    async def register_user() -> None:
        pass

    operation = build(register_user, dialect=OpenAPI30())
    body = operation['requestBody']['content']['application/json']
    assert body['examples'] == {'alice': {'value': ALICE}}
    assert operation['parameters'][0]['examples'] == {'code': {'value': 'X1'}}
