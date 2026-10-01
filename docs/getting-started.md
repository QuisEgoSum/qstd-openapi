# Getting started

An OpenAPI document is built from three things:

1. metadata attached to handlers with `qstd_openapi.openapi`;
2. operation sources, such as Sanic routes or a manually listed `Routes`;
3. document settings held by an `OpenAPI` instance.

The result is an ordinary Python dictionary. Publishing it through a web
framework is optional.

## Choose an integration

Use the Sanic integration when the application is built with Sanic. It reads
registered routes, derives path parameters from route templates and can mount
JSON, YAML, Redoc and Swagger UI endpoints.

Use the FastAPI integration when FastAPI already generates the base document
and you need to add descriptions owned by other layers, such as application
errors or authentication decorators. This integration is experimental.

Use `Routes` directly for another framework, an offline generator or a unit
test:

```python
from pydantic import BaseModel

from qstd_openapi import OpenAPI, Routes, openapi


class UserDTO(BaseModel):
    id: int
    email: str


@openapi.response(UserDTO)
async def get_profile(request):
    """Return the current user's profile."""


spec = OpenAPI(info={'title': 'Profile API', 'version': '1.0.0'})
spec.include(Routes(('/profile', 'get', get_profile)))

document = spec.build().document
```

The first line of a handler docstring becomes the operation summary. The
remaining lines become its description. Set `docstrings=False` on `OpenAPI`
to disable this behavior.

## Describe only what a layer owns

A handler can describe its body and successful response:

```python
@openapi.body(UserRegisterInput)
@openapi.response(UserDTO, status=201)
async def register_user(request):
    """Register a user."""
```

An authentication decorator can contribute its own security requirement and
error response with `openapi.attach()`. The builder follows
`functools.wraps` chains and combines all contributions.

This keeps cross-cutting documentation in the same place as the behavior it
describes. See [Describing operations](describing-operations.md) for the
complete set of options.

## Build and publish

`OpenAPI.build()` returns `BuildResult(document, diagnostics)`. The result is
cached because framework integrations may request the document more than once.
Call `spec.invalidate()` after changing a source that the instance already
contains. Calling `include()` invalidates the cache automatically.

For Sanic, `mount()` publishes the document and UI. For FastAPI, `augment()`
replaces `app.openapi()` with the merged document. For any other environment,
serialize `spec.build().document` with `dumps()` or `dumps_yaml()`.

Enable `OpenAPI(validate=True)` when raw OpenAPI fields or external documents
are involved. This requires the `validate` extra and checks the finished
document before it is cached.

## A practical project layout

For a service with several modules, a useful starting point is:

```text
users_api/
  app.py
  openapi.py       # OpenAPI settings, error provider, mount/build function
  errors.py
  users/
    handlers.py
    models.py
    webhooks.py
tests/
  test_openapi.py  # snapshot of the complete document
docs/
  openapi.json
```

Keep the `OpenAPI` instance or its factory importable without starting a
server. This makes the command-line snapshot check usable in CI.

## Next steps

- [Sanic integration](sanic.md)
- [FastAPI integration](fastapi.md)
- [Schemas and errors](schemas-and-errors.md)
- [Output and CI](output-and-ci.md)
