# FastAPI integration

> FastAPI support is experimental. It is covered by automated tests but has
> not yet been verified in a production application. Merge behavior may change
> in a minor release before 1.0.

FastAPI already builds an OpenAPI document from function signatures,
`response_model` and dependencies. qstd-openapi keeps that document and adds
metadata owned by other layers: application errors, security requirements,
webhooks, scopes and raw operation fields.

Install the integration:

```bash
pip install "qstd-openapi[pydantic,fastapi]"
```

## Augment an application

```python
from fastapi import APIRouter, FastAPI

from qstd_openapi import OpenAPI
from qstd_openapi.contrib.app_errors import AppErrors
from qstd_openapi.fastapi import OpenAPIRouter, augment

users = OpenAPIRouter(APIRouter(prefix='/users', tags=['Users']))


@users.post(
    '/register',
    response_model=UserDTO,
    status_code=201,
    errors=[UserAlreadyExistsError],
)
async def register_user(body: UserRegisterInput) -> UserDTO:
    ...


app = FastAPI(title='Users API', version='1.0.0')
app.include_router(users.router)

spec = OpenAPI(
    info={'title': 'Users API', 'version': '1.0.0'},
    errors=[AppErrors(ApplicationError)],
)
augment(app, spec)
```

`app.openapi()`, `/docs` and `/redoc` now use the merged document. Do not add
the application's routes to `spec`; `augment()` does that internally. Other
sources, such as a `WebhookSet`, should still be included explicitly.

## Router wrapper

`OpenAPIRouter` accepts FastAPI path operation options and qstd-openapi
description options together. The path is positional. The underlying router
is available as `.router`.

Five option names (`tags`, `summary`, `description`, `deprecated` and
`operation_id`) belong to FastAPI and are passed through. `responses=` is the
qstd-openapi mapping from status to schema. Use `fastapi_responses=` for
FastAPI's native response dictionary.

```python
@users.get(
    '/me',
    response_model=UserDTO,
    errors=[UnauthorizedError],
    security='UserSession',
    fastapi_responses={404: {'description': 'Not found'}},
)
async def get_profile() -> UserDTO:
    ...
```

Ordinary FastAPI decorators can also be combined with
`qstd_openapi.openapi` decorators.

## Merge rules

For each operation, the FastAPI document is the base:

- operations hidden with `include_in_schema=False` remain hidden;
- `openapi.exclude()` and scope filters also remove operations;
- a summary, description, `operationId`, deprecation flag or request body
  described with qstd-openapi replaces FastAPI's value;
- tags, security requirements and parameters are combined;
- a response status described with qstd-openapi replaces FastAPI's response
  for that status; unrelated responses such as FastAPI's `422` remain;
- components with the same name must match apart from annotations such as
  `title`, `description`, `default` and examples.

FastAPI generates schemas before qstd-openapi merges the document, so
`type_overrides` does not modify FastAPI-generated schemas.

## Rebuilding

FastAPI caches the result in `app.openapi_schema`. After changing routes or
descriptions at runtime, clear both caches:

```python
app.openapi_schema = None
spec.invalidate()
```

See [`examples/fastapi_augment/`](../examples/fastapi_augment/) for a runnable
application.
