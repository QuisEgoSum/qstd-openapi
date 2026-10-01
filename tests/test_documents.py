"""Including ready documents: the aggregation acceptance criteria."""

from __future__ import annotations

import copy
import json

from pathlib import Path
from typing import Any

import pytest

from openapi_spec_validator import validate

from qstd_openapi import Conflict, Document, OpenAPI, Routes, dumps, openapi
from qstd_openapi.errors import (
    ComponentConflictError,
    DocumentConflictError,
    DuplicateOperationIdError,
    OperationConflictError,
    UnsupportedDocumentError,
)


def users_document() -> dict[str, Any]:
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Users', 'version': '1'},
        'servers': [{'url': 'https://users.internal'}],
        'security': [{'UserSession': []}],
        'x-team': 'users',
        'x-unknown-root': {'kept': True},
        'tags': [{'name': 'Users', 'description': 'Accounts'}],
        'paths': {
            '/': {
                'get': {
                    'operationId': 'listUsers',
                    'x-rate-limit': 10,
                    'responses': {
                        '200': {
                            'description': 'OK',
                            'content': {
                                'application/json': {
                                    'schema': {
                                        'type': 'array',
                                        'items': {'$ref': '#/components/schemas/User'},
                                    },
                                },
                            },
                        },
                    },
                },
            },
            '/{id}': {
                'parameters': [{'$ref': '#/components/parameters/UserId'}],
                'get': {
                    'security': [],
                    'responses': {
                        '200': {'$ref': '#/components/responses/UserResponse'},
                    },
                },
            },
        },
        'components': {
            'schemas': {
                'User': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'pet': {'$ref': '#/components/schemas/Pet'},
                    },
                    'x-entity': True,
                },
                'Pet': {
                    'oneOf': [
                        {'$ref': '#/components/schemas/Cat'},
                        {'$ref': '#/components/schemas/Dog'},
                    ],
                    'discriminator': {
                        'propertyName': 'kind',
                        'mapping': {
                            'cat': '#/components/schemas/Cat',
                            'dog': '#/components/schemas/Dog',
                        },
                    },
                },
                'Cat': {'type': 'object', 'properties': {'kind': {'const': 'cat'}}},
                'Dog': {'type': 'object', 'properties': {'kind': {'const': 'dog'}}},
            },
            'parameters': {
                'UserId': {
                    'name': 'id',
                    'in': 'path',
                    'required': True,
                    'schema': {'type': 'integer'},
                },
            },
            'responses': {
                'UserResponse': {
                    'description': 'A user',
                    'content': {
                        'application/json': {
                            'schema': {'$ref': '#/components/schemas/User'},
                        },
                    },
                },
            },
            'securitySchemes': {
                'UserSession': {'type': 'apiKey', 'in': 'cookie', 'name': 'sid'},
            },
        },
    }


def billing_document() -> dict[str, Any]:
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Billing', 'version': '1'},
        'paths': {
            '/invoices': {
                'get': {
                    'responses': {
                        '200': {
                            'description': 'OK',
                            'content': {
                                'application/json': {
                                    'schema': {'$ref': '#/components/schemas/Invoice'},
                                },
                            },
                        },
                    },
                },
            },
        },
        'components': {
            'schemas': {'Invoice': {'type': 'object'}, 'User': {'type': 'string'}},
        },
        'webhooks': {
            'invoice.paid': {
                'post': {'responses': {'200': {'description': 'OK'}}},
            },
        },
    }


def make_spec(**kwargs: Any) -> OpenAPI:
    return OpenAPI(info={'title': 'Gateway', 'version': '1'}, schemas=(), **kwargs)


def build(*sources: Any, **kwargs: Any) -> dict[str, Any]:
    spec = make_spec(**kwargs)
    spec.include(*sources)
    document = spec.build().document
    validate(document)
    return document


def test_two_documents_with_prefixes_and_namespaces() -> None:
    document = build(
        Document(
            users_document(),
            origin='users',
            path_prefix='/users',
            component_namespace='users',
        ),
        Document(
            billing_document(),
            origin='billing',
            path_prefix='/billing',
            component_namespace='billing',
        ),
    )
    assert sorted(document['paths']) == ['/billing/invoices', '/users/', '/users/{id}']
    schemas = document['components']['schemas']
    assert sorted(schemas) == [
        'billing.Invoice',
        'billing.User',
        'users.Cat',
        'users.Dog',
        'users.Pet',
        'users.User',
    ]
    # Every local reference is rewritten, including discriminator mappings.
    assert schemas['users.User']['properties']['pet'] == {
        '$ref': '#/components/schemas/users.Pet',
    }
    assert schemas['users.Pet']['discriminator']['mapping'] == {
        'cat': '#/components/schemas/users.Cat',
        'dog': '#/components/schemas/users.Dog',
    }
    users_item = document['paths']['/users/{id}']
    assert users_item['parameters'] == [
        {'$ref': '#/components/parameters/users.UserId'},
    ]
    assert users_item['get']['responses']['200'] == {
        '$ref': '#/components/responses/users.UserResponse',
    }
    # securitySchemes are shared, not namespaced.
    assert list(document['components']['securitySchemes']) == ['UserSession']
    assert list(document['webhooks']) == ['invoice.paid']


def test_unknown_fields_and_extensions_are_kept() -> None:
    document = build(Document(users_document(), origin='users', path_prefix='/users'))
    assert document['x-team'] == 'users'
    assert document['x-unknown-root'] == {'kept': True}
    assert document['paths']['/users/']['get']['x-rate-limit'] == 10
    assert document['components']['schemas']['User']['x-entity'] is True
    assert document['tags'] == [{'name': 'Users', 'description': 'Accounts'}]


def test_root_security_moves_into_operations_and_root_fields_are_ignored() -> None:
    spec = make_spec()
    spec.include(Document(users_document(), origin='users', path_prefix='/users'))
    result = spec.build()
    paths = result.document['paths']
    assert paths['/users/']['get']['security'] == [{'UserSession': []}]
    assert paths['/users/{id}']['get']['security'] == []  # explicit override kept
    assert 'security' not in result.document
    assert result.document['info'] == {'title': 'Gateway', 'version': '1'}
    ignored = [d.message for d in result.diagnostics if d.code == 'ignored-root-field']
    assert any("'servers'" in message for message in ignored)


def test_operation_conflict_names_both_origins() -> None:
    with pytest.raises(OperationConflictError, match=r'GET /invoices.*first.*second'):
        build(
            Document(billing_document(), origin='first'),
            Document(billing_document(), origin='second', component_namespace='b2'),
        )


def test_conflict_with_described_operations() -> None:
    @openapi.response({'type': 'object'})
    async def list_invoices() -> None:
        pass

    with pytest.raises(OperationConflictError, match=r'list_invoices.*billing'):
        build(
            Routes(('/invoices', 'get', list_invoices)),
            Document(billing_document(), origin='billing'),
        )


@pytest.mark.no_shadow
def test_component_conflict_and_policies() -> None:
    first = Document(billing_document(), origin='billing', path_prefix='/billing')
    users = users_document()
    del users['paths']

    def users_doc(policy: Any) -> Document:
        return Document(copy.deepcopy(users), origin='users', on_conflict=policy)

    with pytest.raises(ComponentConflictError, match='components/schemas/User'):
        build(first, users_doc('error'))

    kept = build(first, users_doc('keep'))
    assert kept['components']['schemas']['User'] == {'type': 'string'}

    replaced = build(first, users_doc('replace'))
    assert replaced['components']['schemas']['User']['type'] == 'object'

    seen: list[Conflict] = []

    def custom(conflict: Conflict) -> Any:
        seen.append(conflict)
        return 'keep'

    build(first, users_doc(custom))
    assert [(c.kind, c.key, c.existing_origin, c.incoming_origin) for c in seen] == [
        ('component', 'components/schemas/User', 'billing', 'users'),
    ]


def test_identical_components_are_not_conflicts() -> None:
    document = build(
        Document(billing_document(), origin='a', path_prefix='/a'),
        Document(billing_document(), origin='b', path_prefix='/b', on_conflict='keep'),
    )
    assert sorted(document['paths']) == ['/a/invoices', '/b/invoices']


def test_replacing_an_operation_frees_its_operation_id() -> None:
    first = users_document()
    second = users_document()
    second['paths']['/']['get']['summary'] = 'Replaced'
    document = build(
        Document(first, origin='first'),
        Document(second, origin='second', on_conflict='replace'),
    )
    assert document['paths']['/']['get']['summary'] == 'Replaced'


def test_duplicate_operation_ids() -> None:
    other = users_document()
    del other['paths']['/{id}']
    with pytest.raises(DuplicateOperationIdError, match='listUsers'):
        build(
            Document(users_document(), origin='users', path_prefix='/users'),
            Document(other, origin='copy', path_prefix='/copy', on_conflict='keep'),
        )


def test_tag_and_root_field_conflicts() -> None:
    other = billing_document()
    other['tags'] = [{'name': 'Users', 'description': 'Different'}]
    with pytest.raises(DocumentConflictError, match='tag Users'):
        build(
            Document(users_document(), origin='users', path_prefix='/users'),
            Document(
                other,
                origin='billing',
                path_prefix='/billing',
                component_namespace='billing',
            ),
        )
    with pytest.raises(DocumentConflictError, match='root x-team'):
        build(
            Document(users_document(), origin='users', path_prefix='/users'),
            extensions={'x-team': 'gateway'},
        )


def test_failed_include_leaves_the_instance_unchanged() -> None:
    spec = make_spec()
    spec.include(Document(billing_document(), origin='billing'))
    before = dumps(spec.build().document, canonical=True)
    with pytest.raises(OperationConflictError):
        spec.include(Document(billing_document(), origin='again'), check=True)
    assert len(spec.sources) == 1
    assert dumps(spec.build().document, canonical=True) == before


def test_input_is_not_modified_and_output_is_stable() -> None:
    raw = users_document()
    snapshot = copy.deepcopy(raw)
    first = build(
        Document(raw, origin='users', path_prefix='/u', component_namespace='u'),
    )
    second = build(
        Document(raw, origin='users', path_prefix='/u', component_namespace='u'),
    )
    assert raw == snapshot
    assert dumps(first, canonical=True) == dumps(second, canonical=True)


@pytest.mark.no_shadow
def test_external_refs_are_kept_with_a_warning() -> None:
    raw = billing_document()
    raw['components']['schemas']['Invoice'] = {
        '$ref': 'https://example.com/invoice.json',
    }
    spec = make_spec()
    spec.include(Document(raw, origin='billing'))
    result = spec.build()
    assert result.document['components']['schemas']['Invoice'] == {
        '$ref': 'https://example.com/invoice.json',
    }
    assert [d.level for d in result.diagnostics if d.code == 'external-ref'] == [
        'warning',
    ]


def test_unsupported_documents() -> None:
    with pytest.raises(UnsupportedDocumentError, match='openapi'):
        Document({'paths': {}}, origin='bad')
    old = billing_document()
    old['openapi'] = '3.0.3'
    spec = make_spec()
    spec.include(Document(old, origin='legacy'))
    with pytest.raises(UnsupportedDocumentError, match=r'legacy.*3\.0\.3'):
        spec.build()
    with pytest.raises(ValueError, match='path_prefix'):
        Document(billing_document(), origin='x', path_prefix='billing/')


def test_lazy_loader_and_files(tmp_path: Path) -> None:
    calls: list[int] = []

    def load() -> dict[str, Any]:
        calls.append(1)
        return billing_document()

    spec = make_spec()
    spec.include(Document(load, origin='lazy', path_prefix='/lazy'))
    assert calls == []
    assert '/lazy/invoices' in spec.build().document['paths']

    json_file = tmp_path / 'billing.json'
    json_file.write_text(json.dumps(billing_document()))
    document = build(Document.from_file(json_file, path_prefix='/file'))
    assert '/file/invoices' in document['paths']

    yaml = pytest.importorskip('yaml')
    yaml_file = tmp_path / 'billing.yaml'
    yaml_file.write_text(yaml.safe_dump(billing_document()))
    document = build(Document.from_file(yaml_file, path_prefix='/yaml'))
    assert '/yaml/invoices' in document['paths']
