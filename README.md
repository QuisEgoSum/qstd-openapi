# qstd-openapi

Build OpenAPI 3.1 or 3.0 documents from Python code without tying the
description to one web framework.

`qstd-openapi` lets handlers, validators, authentication decorators and other
layers describe the part of an operation they own. It combines those pieces,
turns Python types into schemas, reports conflicting descriptions and can
publish or snapshot the resulting document.

The primary integration is Sanic. FastAPI support is experimental.

## Why qstd-openapi

- Keep API documentation next to the code that implements each concern.
- Describe application exceptions as reusable error responses.
- Use Pydantic models, dataclasses, Python types or raw JSON Schema.
- Build several documents from the same application with scope filters.
- Generate stable JSON or YAML for review and CI.
- Combine existing service documents with path prefixes and component
  namespaces.
- Produce OpenAPI 3.1 and 3.0.3 from the same description.

Metadata is stored on the decorated functions, not in a global registry.
Creating two `OpenAPI` instances in one process does not mix their state.

## Installation

Choose the extras needed by your application:

```bash
# Sanic with Pydantic schemas and YAML output
pip install "qstd-openapi[pydantic,sanic,yaml]"

# FastAPI integration (experimental)
pip install "qstd-openapi[pydantic,fastapi]"

# Framework-independent document builder
pip install "qstd-openapi[pydantic]"
```

Other extras:

| Extra | Enables |
|---|---|
| `pydantic` | Pydantic 2 models, dataclasses and annotated types |
| `pydantic-v1` | Pydantic 1.10 support; experimental and incompatible with `pydantic` |
| `validate` | Validation through `openapi-spec-validator` |
| `sanic` | Sanic route discovery and documentation endpoints |
| `fastapi` | FastAPI document augmentation; experimental |
| `yaml` | YAML input and output |
| `all` | Every extra except `pydantic-v1` |

Python 3.9–3.13 is supported. The base package depends only on
`typing_extensions`.

## Quick start with Sanic

Save this as `app.py`:

```python
from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sanic import Blueprint, Request, Sanic, response

from qstd_openapi import OpenAPI
from qstd_openapi.sanic import OpenAPIBlueprint, SanicRoutes, mount
from qstd_openapi.ui import Redoc


class UserRegisterInput(BaseModel):
    email: str
    password: str = Field(min_length=8)


class UserDTO(BaseModel):
    id: int
    email: str
    created_at: datetime


users = OpenAPIBlueprint(Blueprint('Users', url_prefix='/users'))


@users.post(
    '/register',
    tags=['Users'],
    body=UserRegisterInput,
    responses={201: UserDTO},
)
async def register_user(request: Request):
    """Register a user."""
    payload = UserRegisterInput.model_validate(request.json)
    user = UserDTO(
        id=1,
        email=payload.email,
        created_at=datetime.now(timezone.utc),
    )
    return response.json(user.model_dump(mode='json'), status=201)


app = Sanic('users_api')
app.blueprint(users.blueprint)

spec = OpenAPI(info={'title': 'Users API', 'version': '1.0.0'})
spec.include(SanicRoutes(app))
mount(
    app,
    spec,
    json_path='/openapi.json',
    ui={'/docs': Redoc()},
)
```

Run it:

```bash
sanic app:app --dev
```

Open `http://127.0.0.1:8000/docs`. The document contains the request and
response schemas, the docstring summary and an automatically generated
`operationId`.

`OpenAPIBlueprint` accepts Sanic route options and documentation options in
the same call. If you prefer ordinary framework decorators, the equivalent
description can be written separately:

```python
from sanic import Blueprint

from qstd_openapi import openapi

users_blueprint = Blueprint('Users', url_prefix='/users')


@users_blueprint.post('/register')
@openapi.describe(
    tags=['Users'],
    body=UserRegisterInput,
    responses={201: UserDTO},
)
async def register_user(request):
    ...
```

## Documentation can come from any layer

A project decorator can declare the security and errors it adds. The handler
does not need to repeat them:

```python
import functools

from qstd_openapi import openapi


def require_session(func):
    @functools.wraps(func)
    async def wrapper(request, *args, **kwargs):
        # Authenticate the request or raise UnauthorizedError.
        return await func(request, *args, **kwargs)

    return openapi.attach(
        wrapper,
        security='UserSession',
        errors=[UnauthorizedError],
    )
```

Metadata is collected through `functools.wraps` chains. Conflicting scalar
values, duplicate operations, schemas or `operationId` values fail the build
with both sources named in the error.

## Keep the document in CI

Export a stable, reviewable snapshot:

```bash
python -m qstd_openapi dump users_api.openapi:build_spec \
  -o docs/openapi.json

python -m qstd_openapi dump users_api.openapi:build_spec \
  -o docs/openapi.json --check
```

The target may be an `OpenAPI` instance or a zero-argument factory. A pytest
helper is also available:

```python
from qstd_openapi.testing import assert_matches_snapshot


def test_openapi_document() -> None:
    assert_matches_snapshot(build_spec(), 'docs/openapi.json')
```

Set `QSTD_OPENAPI_UPDATE_SNAPSHOTS=1` to accept an intentional change.

## Documentation

- [Getting started][getting-started] — how descriptions become a
  document and which integration to choose.
- [Describing operations][describing-operations] — decorators,
  `describe()`, parameters, responses, examples and `operationId`.
- [Schemas and errors][schemas-and-errors] — Pydantic, raw schemas,
  serializer overrides and application error classes.
- [Sanic integration][sanic] — route discovery, router wrapper and
  documentation endpoints.
- [FastAPI integration][fastapi] — experimental augment mode and its
  merge rules.
- [Webhooks and scopes][webhooks-and-scopes] — outbound operations and
  several documents from one application.
- [Document aggregation][aggregation] — combining existing OpenAPI
  files and rewriting references.
- [Output and CI][output-and-ci] — JSON/YAML, validation, snapshots and
  OpenAPI 3.0 output.

## Examples

The [examples index][examples] contains commands and expected
results for:

- a minimal, single-file Sanic application;
- a small Sanic service with errors, authentication and a webhook;
- FastAPI document augmentation;
- a gateway document assembled from two YAML service documents.

Examples return payloads that match their documented schemas and are exercised
through HTTP clients by the test suite.

## Support status

| Area | Status |
|---|---|
| OpenAPI 3.1 and 3.0.3 | Supported |
| Sanic ≥ 23.12 | Supported |
| Pydantic ≥ 2.6 | Supported |
| FastAPI ≥ 0.110 | Experimental |
| Pydantic 1.10 | Experimental; planned for removal |

Experimental integrations are covered by automated tests but have not yet
been verified in a production application. Their behavior may change in a
minor release before 1.0.

## License

MIT, see [LICENSE][license].

[aggregation]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/docs/aggregation.md
[describing-operations]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/docs/describing-operations.md
[examples]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/examples/README.md
[fastapi]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/docs/fastapi.md
[getting-started]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/docs/getting-started.md
[license]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/LICENSE
[output-and-ci]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/docs/output-and-ci.md
[sanic]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/docs/sanic.md
[schemas-and-errors]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/docs/schemas-and-errors.md
[webhooks-and-scopes]: https://github.com/QuisEgoSum/qstd-openapi/blob/main/docs/webhooks-and-scopes.md
