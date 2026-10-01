# Examples

Every example can be run from the repository root after installing the
corresponding optional dependencies. The test suite also starts the
applications through their test clients and validates the generated documents.

## Minimal Sanic application

[`sanic_minimal.py`](sanic_minimal.py) is a single-file starting point with
one registration endpoint, Pydantic request/response models and Redoc.

```bash
pip install "qstd-openapi[pydantic,sanic]"
sanic examples.sanic_minimal:app
```

Open `http://127.0.0.1:8000/docs`, or register a user:

```bash
curl -X POST http://127.0.0.1:8000/users/register \
  -H 'content-type: application/json' \
  -d '{"email":"user@example.com","password":"example-passphrase"}'
```

## Modular Sanic service

[`sanic_service/`](sanic_service/) shows a small project split into models,
errors, authentication and application setup. It adds:

- application exceptions documented through `AppErrors`;
- a self-documenting authentication decorator;
- a webhook;
- JSON, YAML, Redoc and Swagger UI endpoints.

```bash
pip install "qstd-openapi[pydantic,sanic,yaml]"
sanic examples.sanic_service.app:app
```

Use `X-Session: demo` for `GET /profile`.

## FastAPI augmentation

[`fastapi_augment/`](fastapi_augment/) keeps FastAPI's native request and
response schemas and adds an application error and a security requirement
through qstd-openapi.

```bash
pip install "qstd-openapi[pydantic,fastapi]" uvicorn
uvicorn examples.fastapi_augment.app:app
```

FastAPI's `/docs` and `/redoc` display the merged document.

## Document aggregation

[`aggregation/`](aggregation/) builds one gateway document from two YAML
service documents. Both services define a component named `User`; namespaces
keep the definitions separate.

```bash
pip install "qstd-openapi[yaml]"
python -m examples.aggregation.build
```

The command prints the combined document as YAML. Pass `--openapi-30` to
render OpenAPI 3.0.3.
