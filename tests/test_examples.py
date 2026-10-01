"""Examples stay runnable and their HTTP responses match the documented shape."""

from __future__ import annotations

import asyncio
import importlib

from typing import Any

import pytest

from openapi_spec_validator import validate


def _example(name: str, *requirements: str) -> Any:
    pydantic = pytest.importorskip('pydantic')
    if pydantic.VERSION.startswith('1.'):
        pytest.skip('examples use Pydantic 2')
    for requirement in requirements:
        pytest.importorskip(requirement)
    return importlib.import_module(f'examples.{name}')


def test_minimal_sanic_example_serves_a_documented_response() -> None:
    example = _example('sanic_minimal', 'sanic', 'sanic_testing')
    document = example.spec.build().document
    validate(document)
    operation = document['paths']['/users/register']['post']
    assert sorted(operation['responses']) == ['201']
    assert operation['requestBody']['content']['application/json']['examples']

    async def exercise() -> None:
        _, created = await example.app.asgi_client.post(
            '/users/register',
            json={
                'email': 'user@example.com',
                'password': 'example-passphrase',
            },
        )
        assert created.status == 201
        assert created.json['id'] == 1
        assert created.json['email'] == 'user@example.com'
        assert created.json['created_at']

        _, docs = await example.app.asgi_client.get('/docs')
        assert docs.status == 200

    asyncio.run(exercise())


def test_modular_sanic_example_exercises_errors_and_authentication() -> None:
    example = _example('sanic_service.app', 'sanic', 'sanic_testing', 'yaml')
    document = example.spec.build().document
    validate(document)
    assert sorted(document['paths']) == ['/profile', '/users/register']
    assert sorted(document['paths']['/users/register']['post']['responses']) == [
        '201',
        '409',
    ]
    assert document['paths']['/profile']['get']['security'] == [
        {'UserSession': []},
    ]
    assert list(document['webhooks']) == ['user.registered']

    async def exercise() -> None:
        _, created = await example.app.asgi_client.post(
            '/users/register',
            json={
                'email': 'user@example.com',
                'password': 'example-passphrase',
            },
        )
        assert created.status == 201
        assert created.json['email'] == 'user@example.com'

        _, conflict = await example.app.asgi_client.post(
            '/users/register',
            json={
                'email': 'existing@example.com',
                'password': 'example-passphrase',
            },
        )
        assert conflict.status == 409
        assert conflict.json == {
            'code': 1001,
            'error': 'UserAlreadyExistsError',
            'message': 'User already exists',
            'email': 'existing@example.com',
        }

        _, unauthorized = await example.app.asgi_client.get('/profile')
        assert unauthorized.status == 401

        _, profile = await example.app.asgi_client.get(
            '/profile',
            headers={'X-Session': 'demo'},
        )
        assert profile.status == 200
        assert profile.json['display_name'] == 'Example User'

        _, yaml_document = await example.app.asgi_client.get('/openapi.yaml')
        assert yaml_document.status == 200

    asyncio.run(exercise())


def test_fastapi_example_serves_merged_document_and_responses() -> None:
    example = _example('fastapi_augment.app', 'fastapi')
    document = example.app.openapi()
    validate(document)
    responses = document['paths']['/users/register']['post']['responses']
    assert sorted(responses) == ['201', '409', '422']
    assert document['paths']['/users/me']['get']['security'] == [
        {'UserSession': []},
    ]

    from fastapi.testclient import TestClient

    client: Any = TestClient(example.app)
    created = client.post(
        '/users/register',
        json={
            'email': 'user@example.com',
            'password': 'example-passphrase',
        },
    )
    assert created.status_code == 201
    assert created.json() == {'id': 1, 'email': 'user@example.com'}

    conflict = client.post(
        '/users/register',
        json={
            'email': 'existing@example.com',
            'password': 'example-passphrase',
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()['error'] == 'UserAlreadyExistsError'


def test_aggregation_example_reads_service_documents() -> None:
    example = importlib.import_module('examples.aggregation.build')
    document = example.build_gateway().build().document
    validate(document)
    assert sorted(document['paths']) == [
        '/profiles/{user_id}',
        '/registration/register',
    ]
    assert sorted(document['components']['schemas']) == [
        'profiles.User',
        'registration.User',
    ]

    legacy = example.build_gateway(openapi_30=True).build().document
    validate(legacy)
    assert legacy['openapi'] == '3.0.3'
