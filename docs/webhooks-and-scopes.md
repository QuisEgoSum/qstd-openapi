# Webhooks and scopes

Webhooks describe requests sent by the application rather than routes served
by it. Scopes let the same handlers and webhooks contribute to several
audience-specific documents.

## Collect outbound webhooks

Create one `WebhookSet` per module or bounded area of the application:

```python
from qstd_openapi import WebhookSet, openapi

webhooks = WebhookSet()


@webhooks.register('user.registered')
@openapi.body(UserRegisteredEvent)
@openapi.response(WebhookAccepted, status=202)
async def send_user_registered(event):
    """Notify a client that registration has completed."""
```

The function is documentation input; qstd-openapi does not call it or send
the HTTP request. Include the set explicitly:

```python
spec.include(SanicRoutes(app), webhooks)
```

Use `webhooks.add(function)` when a function is already marked with
`openapi.webhook()`.

## Build documents for different audiences

Scopes are arbitrary hashable values. Enums make them easier to reuse:

```python
from enum import Enum

from qstd_openapi import OpenAPI, ScopeFilter, openapi


class ApiScope(str, Enum):
    PUBLIC = 'public'
    INTERNAL = 'internal'


@openapi.scope(ApiScope.PUBLIC)
async def register_user(request):
    ...


public_api = OpenAPI(
    info={'title': 'Public API', 'version': '1.0.0'},
    scopes=ScopeFilter(include={ApiScope.PUBLIC}),
)
public_api.include(SanicRoutes(app), webhooks)
```

`ScopeFilter` accepts:

- `include`: at least one operation scope must be in this set;
- `exclude`: any matching scope removes the operation;
- `unscoped`: whether operations without a scope are included.

The same handler may be included by several independent `OpenAPI` instances.
Metadata belongs to the handler, while filters and built documents belong to
the instances.

## Add tags by path

`PathTag` adds a tag based on a route path without coupling the handler to one
published document:

```python
from qstd_openapi import OpenAPI, PathTag

spec = OpenAPI(
    info={'title': 'Users API', 'version': '1.0.0'},
    tag_rules=[
        PathTag(
            'Profiles',
            includes='/profiles/',
            excludes='/profiles/public/',
        ),
    ],
)
```

Path rules do not apply to webhooks because webhooks have names rather than
route paths.

## Keep long tag descriptions in Markdown

Use one Markdown file per tag when descriptions no longer belong in code:

```text
docs/openapi/users/Users.md
docs/openapi/users/Profiles.md
```

```python
from qstd_openapi import OpenAPI, tags_from_markdown

spec = OpenAPI(
    info={'title': 'Users API', 'version': '1.0.0'},
    tags=tags_from_markdown(
        'docs/openapi/users',
        [{'name': 'Users', 'x-displayName': 'Accounts'}],
    ),
)
```

Explicit tags keep their order and custom fields. A Markdown file fills the
description unless one was supplied explicitly. Other files are appended in
name order.
