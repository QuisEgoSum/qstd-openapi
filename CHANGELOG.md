# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Before 1.0 a minor release may change the public API; such changes are
listed here.

---

## [0.1.0] - 2026-10-01

First public release.

### Added

- Declarative description of operations: decorators, a single `describe()`
  call and `attach()` for your own decorators, middlewares and validators;
  descriptions survive `functools.wraps` and are stored on the function, not
  in a global registry.
- `OpenAPI` document builder: OpenAPI 3.1 and 3.0.3 from the same
  description, strict by default (conflicting descriptions, operations,
  components and `operationId`s fail the build naming both sources),
  `scope` filters for several documents from one code base, tag rules by
  path.
- Schemas from Pydantic 2 models, dataclasses, `typing` constructs, a
  `TypeAdapter` or raw JSON Schema; models become components; validation
  schemas for requests and serialization schemas for responses;
  `type_overrides` to match the project's own serializer.
- Error classes as responses through error providers; `AppErrors` for
  "static error classes" with a code, a message and payload fields.
- `operationId` for every operation, from the route name or the function
  name, unless set explicitly.
- Named `examples` for request bodies, responses and parameters.
- Sanic integration: routes read from the application, path parameters from
  the URL template, a typed router wrapper, document and Redoc / Swagger UI
  endpoints.
- Webhooks collected per module (`WebhookSet`).
- Aggregation of ready OpenAPI documents with path prefixes, component
  namespaces, `$ref` rewriting and configurable conflict policies; callable
  policies receive a public `Conflict` value.
- JSON and YAML output, `tags_from_markdown()` for tag descriptions,
  `OpenAPI(validate=True)`, `python -m qstd_openapi dump` and
  `qstd_openapi.testing.assert_matches_snapshot()` for CI.
- Typed public API (`py.typed`): option names and values are checked by
  mypy and pyright.

### Experimental

- FastAPI integration (`augment` mode): covered by tests, not yet checked on
  a production project; merging rules may change in a minor release.
- Pydantic 1 support (`pydantic-v1` extra): expected to be removed in a
  future release.
