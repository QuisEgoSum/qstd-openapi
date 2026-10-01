# Sanic integration

Install the integration with its schema dependencies:

```bash
pip install "qstd-openapi[pydantic,sanic]"
```

The integration has three independent pieces:

- `SanicRoutes` reads operations from an application;
- `OpenAPIBlueprint` combines Sanic route registration with typed
  documentation options;
- `mount()` publishes the document and documentation pages.

## Document existing routes

Ordinary Sanic decorators work without a wrapper:

```python
from sanic import Blueprint, Sanic

from qstd_openapi import OpenAPI, openapi
from qstd_openapi.sanic import SanicRoutes

users = Blueprint('Users', url_prefix='/users')


@users.post('/register')
@openapi.body(UserRegisterInput)
@openapi.response(UserDTO, status=201)
async def register_user(request):
    """Register a user."""
    ...


app = Sanic('users_api')
app.blueprint(users)

spec = OpenAPI(info={'title': 'Users API', 'version': '1.0.0'})
spec.include(SanicRoutes(app))
```

Routes are read when the document is built. If routes are registered after a
previous build, call `spec.invalidate()` before building again.

`SanicRoutes`:

- derives path parameters and common types from `<id:int>`, `<value:float>`,
  `<id:uuid>` and `<day:ymd>`;
- documents class-based views per method;
- skips static files, websockets, `HEAD` and `OPTIONS`;
- uses the blueprint name as the default tag unless `blueprint_tags=False`.

## Register and document in one call

Wrap a blueprint or the application with `OpenAPIBlueprint`:

```python
from sanic import Blueprint

from qstd_openapi.sanic import OpenAPIBlueprint

profiles = OpenAPIBlueprint(Blueprint('Profiles', url_prefix='/profiles'))


@profiles.get(
    '/<user_id:int>',
    name='get_profile',
    tags=['Profiles'],
    response=UserDTO,
)
async def get_profile(request, user_id):
    ...
```

Sanic options (`name`, `strict_slashes`, `version`, and others) and
`DescribeOptions` are accepted by the same typed decorator. The underlying
object is available as `profiles.blueprint`:

```python
app.blueprint(profiles.blueprint)
```

Sanic's `ctx_*` arguments are passed as a mapping:

```python
@profiles.get('/me', ctx={'auth': False}, response=UserDTO)
async def get_own_profile(request):
    ...
```

Attributes not implemented by the wrapper, such as `middleware()` and
`exception()`, are delegated to the wrapped blueprint.

## Publish JSON, YAML and UI pages

```python
from qstd_openapi.sanic import mount
from qstd_openapi.ui import Redoc, SwaggerUI

mount(
    app,
    spec,
    json_path='/openapi.json',
    yaml_path='/openapi.yaml',
    ui={
        '/docs': Redoc(),
        '/swagger': SwaggerUI(),
    },
)
```

YAML output requires the `yaml` extra. Documentation endpoints exclude
themselves from the document.

By default, `mount()` builds the document before the server starts. A broken
description therefore prevents startup instead of failing the first request.
Set `build_on_start=False` only when the application deliberately builds its
routes later.

When the service is mounted below a prefix or the public document URL differs
from its internal route, set `spec_url` for UI pages:

```python
mount(
    app,
    spec,
    json_path='/openapi.json',
    spec_url='/users/openapi.json',
    ui={'/docs': Redoc()},
)
```

Protect every generated endpoint with the same project decorator by passing
`decorators=[docs_auth()]`.

See [`examples/sanic_minimal.py`](../examples/sanic_minimal.py) for a
single-file application and [`examples/sanic_service/`](../examples/sanic_service/)
for a modular service.
