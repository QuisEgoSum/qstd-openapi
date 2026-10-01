# Document aggregation

`Document` includes an existing OpenAPI document in a document built by
`OpenAPI`. Typical uses are a gateway specification and a combined developer
portal.

An input may be:

- a Python mapping;
- a zero-argument loader function;
- a JSON file;
- a YAML file when the `yaml` extra is installed.

## Combine service files

```python
from qstd_openapi import Document, OpenAPI

gateway = OpenAPI(info={'title': 'Gateway API', 'version': '1.0.0'})
gateway.include(
    Document.from_file(
        'registration.openapi.yaml',
        path_prefix='/registration',
        component_namespace='registration',
    ),
    Document.from_file(
        'profiles.openapi.yaml',
        path_prefix='/profiles',
        component_namespace='profiles',
    ),
    check=True,
)
```

`check=True` builds immediately. If an included source fails, it is rolled
back and the `OpenAPI` instance remains usable.

## Prefixes and namespaces

`path_prefix` is prepended to every path. It must start with `/` and must not
end with `/`.

`component_namespace` renames components and rewrites local `$ref` values and
discriminator mappings. For example, `User` becomes `profiles.User` by
default. Change the format with `namespace_format`.

`securitySchemes` are not renamed because services commonly share their
scheme names. A conflict is still reported when the definitions differ.

The input mapping is never modified.

## What is merged

- paths and webhooks;
- components;
- tags;
- root security, copied to operations that do not override it;
- extension and otherwise unknown root fields.

The included document's `info`, `servers` and `externalDocs` are not merged.
An informational diagnostic is added for each skipped root field.

External `$ref` values are kept unchanged and produce a warning diagnostic.
qstd-openapi does not download or resolve remote references.

## Conflict handling

Different definitions of the same operation, component, tag or root field
raise an error by default. Identical definitions are accepted.

Set `on_conflict='keep'` to preserve the value already present, or
`on_conflict='replace'` to use the included value:

```python
Document.from_file('profiles.openapi.yaml', on_conflict='keep')
```

A callable conflict policy is also supported, but it is provisional and may
change before 1.0. It receives a `Conflict` and returns `keep`, `replace` or
`error`:

```python
from typing import Literal

from qstd_openapi import Conflict, Document


def prefer_existing_tags(conflict: Conflict) -> Literal['keep', 'error']:
    return 'keep' if conflict.kind == 'tag' else 'error'


Document.from_file('profiles.openapi.yaml', on_conflict=prefer_existing_tags)
```

`Conflict` has `kind` (`operation`, `webhook`, `path-item`, `component`, `tag`
or `root`), `key`, the `existing` and `incoming` values, and their
`existing_origin` and `incoming_origin`.

See [`examples/aggregation/`](../examples/aggregation/) for a runnable build
using two YAML documents with colliding component names.
