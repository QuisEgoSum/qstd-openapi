"""Building documents without Pydantic: built-in types and raw schemas only."""

from __future__ import annotations

import enum

from typing import Any, Literal, Optional

import pytest

from openapi_spec_validator import validate

from qstd_openapi import (
    BuildError,
    OpenAPI,
    PathTag,
    Routes,
    ScalarConflictError,
    ScopeFilter,
    WebhookSet,
    dumps,
    openapi,
)
from qstd_openapi.errors import (
    ComponentConflictError,
    DuplicateOperationIdError,
    OperationConflictError,
    UnknownSecuritySchemeError,
    UnsupportedErrorObjectError,
    UnsupportedSchemaError,
)
from qstd_openapi.markers import Ref

USER_SCHEMA = {
    'type': 'object',
    'properties': {'id': {'type': 'integer'}, 'email': {'type': 'string'}},
    'required': ['id', 'email'],
}


class ApiScope(str, enum.Enum):
    CLIENT_API = 'client_api'
    USER_API = 'user_api'


class Role(enum.Enum):
    USER = 'user'
    ADMIN = 'admin'


def make_spec(**kwargs: Any) -> OpenAPI:
    kwargs.setdefault('info', {'title': 'Users API', 'version': '1.0.0'})
    kwargs.setdefault('schemas', ())
    return OpenAPI(**kwargs)


def build(*routes: Any, **kwargs: Any) -> dict[str, Any]:
    spec = make_spec(**kwargs)
    spec.include(Routes(*routes))
    document = spec.build().document
    validate(document)
    return document


def test_minimal_document() -> None:
    @openapi.response(USER_SCHEMA, status=201)
    async def register_user() -> None:
        """Register a user."""

    document = build(('/users', 'post', register_user))
    assert document['openapi'] == '3.1.0'
    operation = document['paths']['/users']['post']
    assert operation['summary'] == 'Register a user.'
    assert operation['responses'] == {
        '201': {
            'description': 'Created',
            'content': {'application/json': {'schema': USER_SCHEMA}},
        },
    }


def test_builtin_types_without_pydantic() -> None:
    @openapi.query('role', Role)
    @openapi.query('ids', list[int])
    @openapi.query('name', Optional[str])
    @openapi.query('kind', Literal['person'])
    @openapi.response({'type': 'object', 'additionalProperties': Ref(dict[str, int])})
    async def list_users() -> None:
        pass

    document = build(('/users', 'get', list_users))
    parameters = {
        p['name']: p['schema'] for p in document['paths']['/users']['get']['parameters']
    }
    assert parameters == {
        'role': {'$ref': '#/components/schemas/Role'},
        'ids': {'type': 'array', 'items': {'type': 'integer'}},
        'name': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
        'kind': {'const': 'person', 'type': 'string'},
    }
    assert document['components']['schemas']['Role'] == {
        'enum': ['user', 'admin'],
        'title': 'Role',
        'type': 'string',
    }


def test_path_parameters_inferred_from_template() -> None:
    @openapi.path('user_id', int, description='User id')
    async def get_email(user_id: int, email_id: str) -> None:
        pass

    document = build(('/users/{user_id}/emails/{email_id}', 'get', get_email))
    parameters = document['paths']['/users/{user_id}/emails/{email_id}']['get'][
        'parameters'
    ]
    assert parameters == [
        {
            'name': 'user_id',
            'in': 'path',
            'required': True,
            'description': 'User id',
            'schema': {'type': 'integer'},
        },
        {
            'name': 'email_id',
            'in': 'path',
            'required': True,
            'schema': {'type': 'string'},
        },
    ]


def test_parameter_model_expansion_and_explicit_override() -> None:
    query_model = {
        'type': 'object',
        'properties': {
            'page': {'type': 'integer', 'title': 'Page', 'description': 'Page number'},
            'size': {'type': 'integer'},
        },
        'required': ['page'],
    }

    @openapi.query(query_model)
    @openapi.query('size', int, description='Explicit wins')
    async def list_users() -> None:
        pass

    document = build(('/users', 'get', list_users))
    assert document['paths']['/users']['get']['parameters'] == [
        {
            'name': 'size',
            'in': 'query',
            'description': 'Explicit wins',
            'schema': {'type': 'integer'},
        },
        {
            'name': 'page',
            'in': 'query',
            'required': True,
            'description': 'Page number',
            'schema': {'type': 'integer'},
        },
    ]


def test_docstring_does_not_override_explicit_texts() -> None:
    @openapi.summary('Explicit')
    async def handler() -> None:
        """Docstring summary.

        Details.
        """

    operation = build(('/x', 'get', handler))['paths']['/x']['get']
    assert operation['summary'] == 'Explicit'
    assert operation['description'] == 'Docstring summary.\n\nDetails.'


def test_markdown_docstring_keeps_nested_indentation() -> None:
    async def handler() -> None:
        """Summary.

        - item
            - nested item
        """

    operation = build(('/x', 'get', handler))['paths']['/x']['get']
    assert operation['description'] == '- item\n    - nested item'


def test_docstrings_can_be_disabled() -> None:
    async def handler() -> None:
        """Summary."""

    assert (
        'summary'
        not in build(('/x', 'get', handler), docstrings=False)['paths']['/x']['get']
    )


def test_default_response_and_diagnostic() -> None:
    async def handler() -> None:
        pass

    spec = make_spec()
    spec.include(Routes(('/x', 'get', handler)))
    result = spec.build()
    assert result.document['paths']['/x']['get']['responses'] == {
        '200': {'description': 'OK'},
    }
    assert [d.code for d in result.diagnostics] == ['default-response']


def test_security_requirements_and_unknown_scheme() -> None:
    @openapi.security('UserSession')
    async def handler() -> None:
        pass

    schemes = {'UserSession': {'type': 'apiKey', 'in': 'cookie', 'name': 'sid'}}
    document = build(('/x', 'get', handler), security_schemes=schemes)
    assert document['paths']['/x']['get']['security'] == [{'UserSession': []}]
    assert document['components']['securitySchemes'] == schemes

    with pytest.raises(UnknownSecuritySchemeError, match='UserSession'):
        build(('/x', 'get', handler))


def test_files() -> None:
    @openapi.body_form_data_files('documents', max_items=3)
    @openapi.response_file('application/pdf')
    async def upload() -> None:
        pass

    operation = build(('/upload', 'post', upload))['paths']['/upload']['post']
    assert operation['requestBody']['content']['multipart/form-data']['schema'] == {
        'type': 'object',
        'properties': {
            'documents': {
                'type': 'array',
                'items': {'type': 'string', 'format': 'binary', 'description': 'File'},
                'maxItems': 3,
            },
        },
        'required': ['documents'],
    }
    assert operation['responses']['200']['content']['application/pdf']['schema'] == {
        'type': 'string',
        'format': 'binary',
        'contentMediaType': 'application/pdf',
        'description': 'File',
    }


def test_extra_is_deep_merged() -> None:
    @openapi.extra({'responses': {'200': {'x-cache': True}}, 'x-internal': True})
    @openapi.response(USER_SCHEMA)
    async def handler() -> None:
        pass

    operation = build(('/x', 'get', handler))['paths']['/x']['get']
    assert operation['responses']['200']['x-cache'] is True
    assert operation['responses']['200']['content']
    assert operation['x-internal'] is True


def test_root_fields() -> None:
    async def handler() -> None:
        pass

    document = build(
        ('/x', 'get', openapi.tag('Users', 'Extra')(handler)),
        servers=[{'url': 'https://api.example.com'}],
        tags=[{'name': 'Users', 'description': 'User accounts'}],
        extensions={'x-tagGroups': [{'name': 'Main', 'tags': ['Users']}]},
    )
    assert list(document) == [
        'openapi',
        'info',
        'servers',
        'paths',
        'tags',
        'x-tagGroups',
    ]
    assert document['tags'] == [
        {'name': 'Users', 'description': 'User accounts'},
        {'name': 'Extra'},
    ]


def test_bad_configuration() -> None:
    with pytest.raises(ValueError, match='title'):
        OpenAPI(info={'version': '1'})
    with pytest.raises(ValueError, match='x-'):
        make_spec(extensions={'tagGroups': []})


def test_scopes_and_webhooks() -> None:
    webhooks = WebhookSet()

    @webhooks.register('user.registered', scope=ApiScope.CLIENT_API)
    @openapi.body(USER_SCHEMA)
    async def send_user_registered() -> None:
        pass

    @openapi.scope(ApiScope.USER_API)
    async def get_me() -> None:
        pass

    async def health() -> None:
        pass

    def document(scopes: ScopeFilter) -> dict[str, Any]:
        spec = make_spec(scopes=scopes)
        spec.include(
            Routes(('/me', 'get', get_me), ('/health', 'get', health)),
            webhooks,
        )
        result = spec.build().document
        validate(result)
        return result

    client = document(ScopeFilter(include={ApiScope.CLIENT_API}))
    assert list(client['paths']) == ['/health']
    assert list(client['webhooks']) == ['user.registered']
    assert client['webhooks']['user.registered']['post']['requestBody']['content']

    user = document(ScopeFilter(include={ApiScope.USER_API}, unscoped=False))
    assert list(user['paths']) == ['/me']
    assert 'webhooks' not in user


def test_webhook_set_requires_marked_functions() -> None:
    async def not_a_webhook() -> None:
        pass

    spec = make_spec()
    spec.include(WebhookSet(not_a_webhook))
    with pytest.raises(BuildError, match=r'openapi\.webhook'):
        spec.build()


def test_tag_rules() -> None:
    async def handler() -> None:
        pass

    document = build(
        ('/admin/users', 'get', handler),
        ('/admin/public/info', 'get', handler),
        tag_rules=[PathTag('Admin', includes='/admin/', excludes='/admin/public/')],
    )
    assert document['paths']['/admin/users']['get']['tags'] == ['Admin']
    assert 'tags' not in document['paths']['/admin/public/info']['get']


def test_excluded_operations() -> None:
    @openapi.exclude()
    async def docs() -> None:
        pass

    assert build(('/docs', 'get', docs))['paths'] == {}


def test_operation_conflicts() -> None:
    async def first() -> None:
        pass

    async def second() -> None:
        pass

    with pytest.raises(OperationConflictError, match=r'first.*second'):
        build(('/x', 'get', first), ('/x', 'GET', second))


def test_duplicate_operation_id() -> None:
    @openapi.operation_id('register')
    async def first() -> None:
        pass

    @openapi.operation_id('register')
    async def second() -> None:
        pass

    with pytest.raises(DuplicateOperationIdError):
        build(('/a', 'post', first), ('/b', 'post', second))


def test_scalar_strategy_is_configurable() -> None:
    @openapi.summary('outer')
    @openapi.summary('inner')
    async def handler() -> None:
        pass

    with pytest.raises(ScalarConflictError):
        build(('/x', 'get', handler))
    document = build(('/x', 'get', handler), scalar_conflicts='last_wins')
    assert document['paths']['/x']['get']['summary'] == 'outer'


def test_unsupported_type_inside_raw_schema_reports_its_location() -> None:
    class Unknown:
        pass

    @openapi.response(
        {'type': 'object', 'properties': {'user': Ref(Optional[list[Unknown]])}},
    )
    async def handler() -> None:
        pass

    with pytest.raises(
        UnsupportedSchemaError,
        match=r'Unknown.*properties/user',
    ) as info:
        build(('/x', 'get', handler))
    assert info.value.target is Unknown
    assert info.value.location == ('properties', 'user')


@pytest.mark.parametrize('decorator', ['body_one_of', 'responses', 'response'])
def test_list_in_place_of_a_schema_explains_the_alternatives(decorator: str) -> None:
    """The old signatures took a list: ``body_one_of([A, B])``."""

    class UserDTO:
        pass

    class AdminDTO:
        pass

    schemas: Any = [UserDTO, AdminDTO] if decorator != 'response' else (UserDTO,)

    @getattr(openapi, decorator)(schemas)
    async def handler() -> None:
        pass

    with pytest.raises(UnsupportedSchemaError, match=r'body_one_of\(A, B\).*list\[A\]'):
        build(('/x', 'post', handler))


def test_unhashable_object_is_an_unsupported_schema() -> None:
    @openapi.response(bytearray(b'x'))
    async def handler() -> None:
        pass

    with pytest.raises(UnsupportedSchemaError, match='bytearray'):
        build(('/x', 'get', handler))


def test_unsupported_schema_and_error() -> None:
    class Unknown:
        pass

    @openapi.response(Unknown)
    async def handler() -> None:
        pass

    with pytest.raises(UnsupportedSchemaError, match='Unknown'):
        build(('/x', 'get', handler))

    @openapi.errors(ValueError)
    async def failing() -> None:
        pass

    with pytest.raises(UnsupportedErrorObjectError, match='ValueError'):
        build(('/x', 'get', failing))


def test_component_conflict() -> None:
    class First(enum.Enum):
        A = 'a'

    class Second(enum.Enum):
        B = 'b'

    Second.__name__ = 'First'

    @openapi.query('a', First)
    @openapi.query('b', Second)
    async def handler() -> None:
        pass

    with pytest.raises(ComponentConflictError, match="'First'"):
        build(('/x', 'get', handler))


def test_cache_and_invalidation() -> None:
    async def handler() -> None:
        pass

    spec = make_spec()
    spec.include(Routes(('/a', 'get', handler)))
    first = spec.build()
    assert spec.build() is first
    spec.include(Routes(('/b', 'get', handler)))
    second = spec.build()
    assert second is not first
    assert list(second.document['paths']) == ['/a', '/b']


def test_build_dict_is_a_copy() -> None:
    async def handler() -> None:
        pass

    spec = make_spec()
    spec.include(Routes(('/a', 'get', handler)))
    spec.build_dict()['paths'].clear()
    assert list(spec.build().document['paths']) == ['/a']


def test_canonical_json_is_stable_regardless_of_source_order() -> None:
    @openapi.response(USER_SCHEMA)
    async def a() -> None:
        pass

    @openapi.response(USER_SCHEMA)
    async def b() -> None:
        pass

    one = build(('/a', 'get', a), ('/b', 'post', b), ('/b', 'get', b))
    two = build(('/b', 'get', b), ('/b', 'post', b), ('/a', 'get', a))
    assert dumps(one, canonical=True) == dumps(two, canonical=True)
    assert list(one['paths']['/b']) == ['get', 'post']


def test_documents_do_not_share_state() -> None:
    @openapi.response(USER_SCHEMA)
    async def handler() -> None:
        pass

    first = build(('/a', 'get', handler))
    second = build(('/a', 'get', handler))
    first['paths']['/a']['get']['responses']['200']['content'].clear()
    assert second['paths']['/a']['get']['responses']['200']['content']
