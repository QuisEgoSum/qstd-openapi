# Output and CI

Treat the generated OpenAPI document as a versioned build artifact. A checked
snapshot makes API changes visible in review and allows CI to reject accidental
changes.

## Build and serialize

`OpenAPI.build()` returns a cached `BuildResult`:

```python
result = spec.build()
document = result.document
diagnostics = result.diagnostics
```

Treat `result.document` as read-only. Use `spec.build_dict()` when the caller
needs a private mutable copy.

Stable serializers sort keys when `canonical=True`:

```python
from qstd_openapi import dumps, dumps_yaml

json_text = dumps(document, canonical=True)
yaml_text = dumps_yaml(document, canonical=True)
```

YAML requires the `yaml` extra.

## Validate the finished document

Install the validator integration:

```bash
pip install "qstd-openapi[validate]"
```

Validate every build by configuration:

```python
spec = OpenAPI(
    info={'title': 'Users API', 'version': '1.0.0'},
    validate=True,
)
```

Or validate any existing mapping:

```python
from qstd_openapi import validate_document

validate_document(document)
```

An invalid document raises `InvalidDocumentError` with the location reported
by `openapi-spec-validator`.

## Command-line snapshots

The `dump` command imports an `OpenAPI` instance or a zero-argument factory:

```bash
python -m qstd_openapi dump users_api.openapi:build_spec \
  -o docs/openapi.json
```

Use a `.yaml` output name or `--yaml` for YAML. Use `--dialect 3.0` to render
OpenAPI 3.0.3.

CI should compare instead of writing:

```bash
python -m qstd_openapi dump users_api.openapi:build_spec \
  -o docs/openapi.json --check
```

Exit code `1` means the snapshot differs. Loading and build errors use exit
code `2`.

## Pytest snapshots

```python
from qstd_openapi.testing import assert_matches_snapshot


def test_openapi_document() -> None:
    assert_matches_snapshot(build_spec(), 'docs/openapi.json')
```

The assertion includes a bounded unified diff. Update an intentional change
locally with:

```bash
QSTD_OPENAPI_UPDATE_SNAPSHOTS=1 pytest tests/test_openapi.py
```

Commit the updated document together with the code that changed the contract.

Snapshot equality detects every change but does not classify compatibility.
Use a dedicated tool such as [oasdiff](https://github.com/oasdiff/oasdiff) when
CI must distinguish breaking changes:

```bash
oasdiff breaking main/openapi.json docs/openapi.json --fail-on ERR
```

## OpenAPI 3.0.3

OpenAPI 3.1 is the default. Select 3.0.3 explicitly:

```python
from qstd_openapi import OpenAPI
from qstd_openapi.dialects import OpenAPI30

spec = OpenAPI(
    info={'title': 'Users API', 'version': '1.0.0'},
    dialect=OpenAPI30(),
)
```

The dialect converts nullable types, `const`, schema examples and unsupported
JSON Schema keywords as needed. Webhooks are emitted as `x-webhooks`.

The same setting works with FastAPI augmentation and with included OpenAPI 3.0
or 3.1 documents.

## Build errors and diagnostics

Build failures inherit from `BuildError` and expose a stable `code`, including
`operation-conflict`, `component-conflict`, `scalar-conflict`,
`unsupported-schema`, `unknown-security-scheme` and `invalid-document`.

Non-fatal findings are returned in `BuildResult.diagnostics`. Each diagnostic
has a level, code and message. Current aggregation diagnostics include skipped
root fields and retained external references.
