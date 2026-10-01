"""Building an OpenAPI document from operation sources."""

from __future__ import annotations

import copy
import http
import importlib.util
import inspect
import re

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Literal, Optional, Union, cast

from qstd_openapi.core.documents import Conflict, DocumentContribution
from qstd_openapi.core.error_responses import ErrorProvider, ErrorSchemas
from qstd_openapi.core.filters import ScopeFilter, TagRule
from qstd_openapi.core.schemas import (
    BuiltinSchemas,
    Components,
    JsonSchema,
    SchemaMode,
    SchemaProvider,
    SchemaResolver,
    TypeOverrides,
    TypeOverrideValue,
)
from qstd_openapi.core.sources import (
    HTTP_METHODS,
    OperationSource,
    RouteEntry,
    SourceEntry,
    WebhookEntry,
)
from qstd_openapi.dialects.base import OpenAPIDialect
from qstd_openapi.dialects.openapi31 import OpenAPI31
from qstd_openapi.errors import (
    BuildError,
    ComponentConflictError,
    DocumentConflictError,
    DuplicateOperationIdError,
    InvalidDocumentError,
    OperationConflictError,
    UnknownSecuritySchemeError,
)
from qstd_openapi.markers import File, FileList
from qstd_openapi.meta.merge import (
    ScalarConflicts,
    get_scalar_strategy,
    merge_contributions,
)
from qstd_openapi.meta.model import (
    Examples,
    OperationMeta,
    Parameter,
    StatusCode,
)
from qstd_openapi.meta.storage import describe_owner, read_contributions

_PATH_PARAMETER = re.compile(r'{([^{}]+)}')


@dataclass(frozen=True)
class Diagnostic:
    code: str
    level: str
    """``'info'`` or ``'warning'``; errors are raised as :class:`BuildError`."""
    message: str
    path: tuple[str, ...] = ()
    origins: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildResult:
    document: dict[str, Any]
    """The built document; treat it as read-only, it is cached by :class:`OpenAPI`."""
    diagnostics: tuple[Diagnostic, ...] = field(default=())


OperationIdStrategy = Callable[[SourceEntry, OperationMeta], Optional[str]]
"""``(entry, merged metadata) -> operationId`` or ``None`` to leave it out."""

OperationIds = Union[Literal['route_name', 'function'], OperationIdStrategy, None]
"""How operations without an explicit ``operation_id`` are named:

- ``'route_name'`` (default): the route's name when the source knows it
  (Sanic: ``<blueprint>_<handler>``), otherwise the function name;
- ``'function'``: the function name;
- a callable ``(entry, meta) -> str | None``;
- ``None``: no generated ``operationId``.
"""


def _function_name(entry: SourceEntry, _meta: OperationMeta) -> Optional[str]:
    name = getattr(entry.handler, '__name__', None)
    return name if isinstance(name, str) else None


def _route_name(entry: SourceEntry, meta: OperationMeta) -> Optional[str]:
    if isinstance(entry, RouteEntry) and entry.name:
        return entry.name
    return _function_name(entry, meta)


_OPERATION_ID_STRATEGIES: Mapping[str, OperationIdStrategy] = MappingProxyType(
    {'route_name': _route_name, 'function': _function_name},
)


def _operation_id_strategy(value: OperationIds) -> Optional[OperationIdStrategy]:
    if value is None or callable(value):
        return value
    try:
        return _OPERATION_ID_STRATEGIES[value]
    except KeyError:
        raise ValueError(
            f'Unknown operation_ids {value!r}: use '
            f'{", ".join(map(repr, _OPERATION_ID_STRATEGIES))}, a function or None',
        ) from None


def _default_schema_providers() -> tuple[SchemaProvider, ...]:
    if importlib.util.find_spec('pydantic') is None:
        return ()
    from qstd_openapi.pydantic import PydanticSchemas

    return (PydanticSchemas(),)


class OpenAPI:
    """One OpenAPI document: configuration, included sources and a cached result.

    Instances are independent; several documents (for example one per API
    audience, filtered by ``scopes``) can be built from the same handlers.
    """

    def __init__(
        self,
        *,
        info: Mapping[str, Any],
        servers: Sequence[Mapping[str, Any]] = (),
        security_schemes: Optional[Mapping[str, Mapping[str, Any]]] = None,
        tags: Sequence[Mapping[str, Any]] = (),
        extensions: Optional[Mapping[str, Any]] = None,
        schemas: Optional[Sequence[SchemaProvider]] = None,
        errors: Sequence[ErrorProvider] = (),
        dialect: Optional[OpenAPIDialect] = None,
        scalar_conflicts: ScalarConflicts = 'error',
        scopes: Optional[ScopeFilter] = None,
        tag_rules: Sequence[TagRule] = (),
        docstrings: bool = True,
        default_response: bool = True,
        type_overrides: Optional[Mapping[Any, TypeOverrideValue]] = None,
        validate: bool = False,
        operation_ids: OperationIds = 'route_name',
    ) -> None:
        missing = [key for key in ('title', 'version') if not info.get(key)]
        if missing:
            raise ValueError(f'info must contain {" and ".join(missing)}')
        extensions = dict(extensions or {})
        bad = [key for key in extensions if not key.startswith('x-')]
        if bad:
            raise ValueError(f'Extension keys must start with "x-": {", ".join(bad)}')
        self.info = copy.deepcopy(dict(info))
        self.servers = copy.deepcopy([dict(server) for server in servers])
        self.security_schemes = copy.deepcopy(dict(security_schemes or {}))
        self.tags = copy.deepcopy([dict(tag) for tag in tags])
        self.extensions = copy.deepcopy(extensions)
        self.schema_providers = (
            tuple(schemas) if schemas is not None else _default_schema_providers()
        )
        self.error_providers = tuple(errors)
        self.dialect: OpenAPIDialect = dialect or OpenAPI31()
        get_scalar_strategy(scalar_conflicts)  # fail early on an unknown mode
        self.scalar_conflicts: ScalarConflicts = scalar_conflicts
        self.scopes = scopes or ScopeFilter()
        self.tag_rules = tuple(tag_rules)
        self.docstrings = docstrings
        self.default_response = default_response
        self.type_overrides = TypeOverrides(type_overrides)
        self.validate = validate
        self.operation_ids: OperationIds = operation_ids
        _operation_id_strategy(operation_ids)  # fail early on an unknown name
        self._sources: list[OperationSource] = []
        self._cache: Optional[BuildResult] = None

    def include(self, *sources: OperationSource, check: bool = False) -> None:
        """Add sources (routes, webhook sets, documents); invalidates the cache.

        With ``check=True`` the document is built right away; if that fails the
        sources are not added and the error is raised, so a bad inclusion
        never leaves the instance half-changed.
        """
        previous = list(self._sources)
        self._sources.extend(sources)
        self._cache = None
        if check:
            try:
                self.build()
            except Exception:
                self._sources = previous
                self._cache = None
                raise

    @property
    def sources(self) -> tuple[OperationSource, ...]:
        return tuple(self._sources)

    def derive(self, **changes: Any) -> OpenAPI:
        """A copy with some settings changed; sources are copied, the cache is not.

        ``changes`` are attribute names of this class (``default_response``,
        ``docstrings``, ``security_schemes``, ...). Used by framework
        integrations that build a variant of the user's document.
        """
        unknown = [
            name for name in changes if name.startswith('_') or not hasattr(self, name)
        ]
        if unknown:
            raise TypeError(f'Unknown OpenAPI settings: {", ".join(unknown)}')
        clone = copy.copy(self)
        for name, value in changes.items():
            setattr(clone, name, value)
        clone._sources = list(self._sources)
        clone._cache = None
        return clone

    def invalidate(self) -> None:
        """Drop the cached document (sources may have changed underneath)."""
        self._cache = None

    def build(self) -> BuildResult:
        """Build (or return the cached) document.

        With ``validate=True`` the document is checked by
        ``openapi-spec-validator`` (the ``validate`` extra) before it is
        cached; an invalid one raises :class:`InvalidDocumentError`.
        """
        if self._cache is None:
            result = _Builder(self, tuple(self._sources)).build()
            if self.validate:
                validate_document(result.document)
            self._cache = result
        return self._cache

    def build_dict(self) -> dict[str, Any]:
        """A copy of the built document that may be modified freely."""
        return copy.deepcopy(self.build().document)


@dataclass(frozen=True)
class _GeneratedId:
    base: str
    location: str
    """Path, or the webhook name."""
    method: str
    origin: object
    """The route name if the source knows it, else the handler's identity."""
    operation: JsonSchema
    owner: str


@dataclass
class _ModelParameters:
    parameters: list[JsonSchema]
    location: str
    slot: JsonSchema
    taken: set[tuple[str, str]]
    owner: str


@dataclass
class _ResponseDraft:
    description: Optional[str] = None
    error_description: Optional[str] = None
    content: dict[str, list[tuple[Any, bool]]] = field(
        default_factory=lambda: dict[str, list[tuple[Any, bool]]](),
    )
    headers: JsonSchema = field(default_factory=lambda: JsonSchema())
    examples: dict[str, Examples] = field(
        default_factory=lambda: dict[str, Examples](),
    )


def _render_examples(examples: Examples) -> JsonSchema:
    rendered: JsonSchema = {}
    for name, example in examples:
        item: JsonSchema = {}
        if example.summary:
            item['summary'] = example.summary
        if example.description:
            item['description'] = example.description
        item['value'] = copy.deepcopy(example.value)
        rendered[name] = item
    return rendered


def _status_key(status: StatusCode) -> str:
    return str(status)


def _status_order(key: str) -> tuple[int, str]:
    return (0, key.zfill(3)) if key.isdigit() else (1, key)


def _default_description(key: str) -> str:
    if key.isdigit():
        try:
            return http.HTTPStatus(int(key)).phrase
        except ValueError:
            pass
    if key == 'default':
        return 'Default response'
    return f'{key} response'


def _parameter_key(location: str, name: str) -> tuple[str, str]:
    return (location, name.lower() if location == 'header' else name)


def _deep_merge(target: JsonSchema, patch: Mapping[str, Any]) -> None:
    for key, value in patch.items():
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _deep_merge(cast('JsonSchema', current), cast('Mapping[str, Any]', value))
        else:
            target[key] = copy.deepcopy(value)


class _Builder:
    def __init__(self, config: OpenAPI, sources: tuple[OperationSource, ...]) -> None:
        self.config = config
        self.sources = sources
        self.errors = ErrorSchemas(config.error_providers)
        self.components = Components()
        self.resolver = SchemaResolver(
            [*config.schema_providers, self.errors, BuiltinSchemas()],
            config.dialect,
            self.components,
            type_overrides=config.type_overrides,
        )
        self.paths: dict[str, dict[str, JsonSchema]] = {}
        self.webhooks: dict[str, dict[str, JsonSchema]] = {}
        self.owners: dict[tuple[str, str, str], str] = {}
        self.operation_ids: dict[str, str] = {}
        self.generated_ids: list[_GeneratedId] = []
        self.used_tags: list[str] = []
        self.expansions: list[_ModelParameters] = []
        self.diagnostics: list[Diagnostic] = []
        self.raw_components: dict[str, dict[str, tuple[JsonSchema, str]]] = {}
        self.raw_tags: dict[str, tuple[JsonSchema, str]] = {}
        self.raw_extensions: dict[str, tuple[Any, str]] = {}

    # --- entry points ---------------------------------------------------

    def build(self) -> BuildResult:
        contributions: list[DocumentContribution] = []
        for source in self.sources:
            for entry in source.collect():
                self._add(entry)
            contribute = getattr(source, 'contribution', None)
            if callable(contribute):
                contributions.append(
                    cast('DocumentContribution', contribute(self.config.dialect)),
                )
        self._assign_operation_ids()
        self.resolver.finish()
        self.resolver.fill(self.paths)
        self.resolver.fill(self.webhooks)
        for expansion in self.expansions:
            self.resolver.fill(expansion.slot)
            self._expand(expansion)
        self._prune_components()
        for contribution in contributions:
            self._merge_document(contribution)
        document = self.config.dialect.finalize(self._document(), self._webhooks())
        return BuildResult(document, tuple(self.diagnostics))

    def _add(self, entry: SourceEntry) -> None:
        owner = describe_owner(entry.handler)
        meta = merge_contributions(
            read_contributions(entry.handler),
            self.config.scalar_conflicts,
        )
        if meta.exclude or not self.config.scopes.allows(meta.scopes):
            return
        if isinstance(entry, WebhookEntry):
            if meta.webhook is None:
                raise BuildError(
                    f'{owner} is included as a webhook but has no openapi.webhook(...)',
                )
            method = meta.webhook.method
            operation = self._operation(entry.handler, meta, None, method, (), ())
            self._generate_operation_id(
                entry,
                meta,
                meta.webhook.name,
                method,
                operation,
                owner,
            )
            self._place(
                self.webhooks,
                'webhook',
                meta.webhook.name,
                method,
                operation,
                owner,
            )
            return
        assert isinstance(entry, RouteEntry)
        operation = self._operation(
            entry.handler,
            meta,
            entry.path,
            entry.method,
            entry.tags,
            entry.parameters,
        )
        self._generate_operation_id(
            entry,
            meta,
            entry.path,
            entry.method,
            operation,
            owner,
        )
        self._place(self.paths, 'path', entry.path, entry.method, operation, owner)

    def _generate_operation_id(
        self,
        entry: SourceEntry,
        meta: OperationMeta,
        location: str,
        method: str,
        operation: JsonSchema,
        owner: str,
    ) -> None:
        strategy = _operation_id_strategy(self.config.operation_ids)
        if strategy is None or 'operationId' in operation:
            return
        base = strategy(entry, meta)
        if base:
            origin: object = (
                entry.name
                if isinstance(entry, RouteEntry) and entry.name
                else id(entry.handler)
            )
            self.generated_ids.append(
                _GeneratedId(base, location, method, origin, operation, owner),
            )

    def _assign_operation_ids(self) -> None:
        """Name operations after explicit ids are known, so those always win.

        A name shared by several operations of one route (or one handler when
        the source has no route names) gets a ``_<method>`` suffix, and
        ``_<method>_<path>`` when one handler serves a method on several paths.
        Different routes or handlers with one name are an error: only the
        project knows which name each should get.
        """
        groups: dict[str, list[_GeneratedId]] = {}
        for item in self.generated_ids:
            groups.setdefault(item.base, []).append(item)
        for base, items in groups.items():
            if len({item.origin for item in items}) > 1:
                first, second = items[0], items[1]
                raise DuplicateOperationIdError(
                    f'Generated operationId {base!r} is used by {first.owner} and '
                    f'{second.owner}; set operation_id(...) on one of them or change '
                    'OpenAPI(operation_ids=...)',
                )
            methods = [item.method for item in items]
            distinct = len(set(methods)) == len(methods)
            for item in items:
                if len(items) == 1:
                    operation_id = base
                elif distinct:
                    operation_id = f'{base}_{item.method}'
                else:
                    slug = re.sub(r'[^0-9A-Za-z]+', '_', item.location).strip('_')
                    operation_id = f'{base}_{item.method}_{slug}'
                previous = self.operation_ids.get(operation_id)
                if previous is not None:
                    raise DuplicateOperationIdError(
                        f'Generated operationId {operation_id!r} is used by '
                        f'{previous} and {item.owner}; set operation_id(...) on one '
                        'of them or change OpenAPI(operation_ids=...)',
                    )
                self.operation_ids[operation_id] = item.owner
                item.operation['operationId'] = operation_id

    def _place(
        self,
        target: dict[str, dict[str, JsonSchema]],
        kind: str,
        name: str,
        method: str,
        operation: JsonSchema,
        owner: str,
    ) -> None:
        key = (kind, name, method)
        if key in self.owners:
            raise OperationConflictError(
                f'{method.upper()} {kind} {name!r} is served by both '
                f'{self.owners[key]} and {owner}',
            )
        self.owners[key] = owner
        target.setdefault(name, {})[method] = operation

    # --- operation ------------------------------------------------------

    def _operation(
        self,
        handler: Any,
        meta: OperationMeta,
        path: Optional[str],
        method: str,
        default_tags: tuple[str, ...],
        default_parameters: tuple[Parameter, ...],
    ) -> JsonSchema:
        owner = describe_owner(handler)
        operation: JsonSchema = {}

        tags = list(meta.tags or default_tags)
        for rule in self.config.tag_rules:
            tags.extend(tag for tag in rule(path, method, meta) if tag not in tags)
        if tags:
            operation['tags'] = tags
            self.used_tags.extend(tag for tag in tags if tag not in self.used_tags)

        summary, description = self._texts(handler, meta)
        if summary:
            operation['summary'] = summary
        if description:
            operation['description'] = description

        if meta.operation_id:
            previous = self.operation_ids.get(meta.operation_id)
            if previous is not None:
                raise DuplicateOperationIdError(
                    f'operationId {meta.operation_id!r} is used by {previous} and {owner}',
                )
            self.operation_ids[meta.operation_id] = owner
            operation['operationId'] = meta.operation_id

        parameters = self._parameters(meta, path, default_parameters, owner)
        if parameters is not None:
            operation['parameters'] = parameters

        if meta.body:
            # A webhook body is sent by us, so it is described as serialized.
            mode: SchemaMode = 'serialization' if path is None else 'validation'
            body_content: JsonSchema = {}
            for content in meta.body:
                media: JsonSchema = {}
                if content.schemas:
                    media['schema'] = self.resolver.content_schema(
                        content.schemas,
                        content.media_type,
                        mode,
                    )
                if content.examples:
                    media['examples'] = _render_examples(content.examples)
                body_content[content.media_type] = media
            operation['requestBody'] = {'content': body_content, 'required': True}

        responses = self._responses(meta, owner)
        if responses:
            operation['responses'] = responses

        security = self._security(meta, owner)
        if security:
            operation['security'] = security
        if meta.deprecated:
            operation['deprecated'] = True
        for extra in meta.extra:
            _deep_merge(operation, extra)
        return operation

    def _texts(
        self,
        handler: Any,
        meta: OperationMeta,
    ) -> tuple[Optional[str], Optional[str]]:
        summary, description = meta.summary, meta.description
        if not self.config.docstrings or (summary and description):
            return summary, description
        doc = inspect.getdoc(handler)
        if not doc:
            return summary, description
        if summary is None:
            first, _, rest = doc.partition('\n')
            return first.strip(), description or (rest.strip() or None)
        return summary, description or doc

    def _parameters(
        self,
        meta: OperationMeta,
        path: Optional[str],
        defaults: tuple[Parameter, ...],
        owner: str,
    ) -> Optional[list[JsonSchema]]:
        explicit: dict[tuple[str, str], Parameter] = {}
        for parameter in (*defaults, *meta.parameters):
            explicit[_parameter_key(parameter.location, parameter.name)] = parameter
        if path is not None:
            for name in _PATH_PARAMETER.findall(path):
                explicit.setdefault(('path', name), Parameter('path', name))
        rendered = [self._parameter(parameter) for parameter in explicit.values()]
        for model in meta.parameter_models:
            self.expansions.append(
                _ModelParameters(
                    rendered,
                    model.location,
                    {'schema': self.resolver.resolve(model.model, 'validation')},
                    set(explicit),
                    owner,
                ),
            )
        return rendered if rendered or meta.parameter_models else None

    def _parameter(self, parameter: Parameter) -> JsonSchema:
        rendered: JsonSchema = {'name': parameter.name, 'in': parameter.location}
        if parameter.location == 'path' or parameter.required:
            rendered['required'] = True
        if parameter.description:
            rendered['description'] = parameter.description
        if parameter.deprecated:
            rendered['deprecated'] = True
        rendered['schema'] = self.resolver.resolve(parameter.schema, 'validation')
        if parameter.examples:
            rendered['examples'] = _render_examples(parameter.examples)
        return rendered

    def _expand(self, expansion: _ModelParameters) -> None:
        schema = expansion.slot['schema']
        ref = schema.get('$ref')
        if isinstance(ref, str):
            name = self.resolver.component_name(ref)
            schema = (self.components.get(name) if name else None) or {}
        properties = schema.get('properties')
        if not isinstance(properties, Mapping):
            raise BuildError(
                f'{expansion.owner}: {expansion.location} model must describe an '
                'object with properties',
            )
        required = set(cast('Iterable[str]', schema.get('required', ())))
        for name, prop in cast('Mapping[str, JsonSchema]', properties).items():
            if _parameter_key(expansion.location, name) in expansion.taken:
                continue
            prop_schema = copy.deepcopy(prop)
            prop_schema.pop('title', None)
            description = prop_schema.pop('description', None)
            deprecated = prop_schema.pop('deprecated', False)
            parameter: JsonSchema = {'name': name, 'in': expansion.location}
            if expansion.location == 'path' or name in required:
                parameter['required'] = True
            if description:
                parameter['description'] = description
            if deprecated:
                parameter['deprecated'] = True
            parameter['schema'] = prop_schema
            expansion.parameters.append(parameter)

    def _responses(self, meta: OperationMeta, owner: str) -> JsonSchema:
        drafts: dict[str, _ResponseDraft] = {}
        for response in meta.responses:
            draft = drafts.setdefault(_status_key(response.status), _ResponseDraft())
            draft.description = response.description or draft.description
            for content in response.content:
                draft.content.setdefault(content.media_type, []).extend(
                    (schema, False) for schema in content.schemas
                )
                if content.examples:
                    draft.examples[content.media_type] = content.examples
            for header in response.headers:
                rendered: JsonSchema = {
                    'schema': self.resolver.resolve(header.schema, 'serialization'),
                }
                if header.description:
                    rendered['description'] = header.description
                if header.required:
                    rendered['required'] = True
                draft.headers[header.name] = rendered
        for error in meta.errors:
            described = self.errors.describe(error.error)
            draft = drafts.setdefault(_status_key(described.status), _ResponseDraft())
            draft.error_description = draft.error_description or described.description
            draft.content.setdefault(error.media_type, []).append((error.error, True))

        if not drafts:
            if not self.config.default_response:
                return {}
            self.diagnostics.append(
                Diagnostic(
                    'default-response',
                    'info',
                    'No responses described; added "200 OK"',
                    origins=(owner,),
                ),
            )
            return {'200': {'description': 'OK'}}

        responses: JsonSchema = {}
        for key in sorted(drafts, key=_status_order):
            draft = drafts[key]
            rendered = {
                'description': draft.description
                or draft.error_description
                or _default_description(key),
            }
            if draft.headers:
                rendered['headers'] = draft.headers
            if draft.content:
                content_map: JsonSchema = {}
                for media_type, targets in draft.content.items():
                    media: JsonSchema = {}
                    if targets:
                        media['schema'] = self._content(targets, media_type)
                    if media_type in draft.examples:
                        media['examples'] = _render_examples(draft.examples[media_type])
                    content_map[media_type] = media
                rendered['content'] = content_map
            responses[key] = rendered
        return responses

    def _content(
        self,
        targets: Sequence[tuple[Any, bool]],
        media_type: str,
    ) -> JsonSchema:
        schemas: list[JsonSchema] = []
        for target, is_error in targets:
            if isinstance(target, (File, FileList)):
                schemas.append(self.config.dialect.file_schema(target, media_type))
            else:
                provider = self.errors if is_error else None
                schemas.append(self.resolver.resolve(target, 'serialization', provider))
        unique: list[JsonSchema] = []
        for schema in schemas:
            if not any(schema is seen for seen in unique):
                unique.append(schema)
        return unique[0] if len(unique) == 1 else {'oneOf': unique}

    def _security(self, meta: OperationMeta, owner: str) -> list[JsonSchema]:
        requirements: list[JsonSchema] = []
        for requirement in meta.security:
            for name, _ in requirement.schemes:
                if name not in self.config.security_schemes:
                    raise UnknownSecuritySchemeError(
                        f'{owner} requires security scheme {name!r}, which is not in '
                        'OpenAPI(security_schemes=...)',
                    )
            requirements.append(
                {name: list(scopes) for name, scopes in requirement.schemes},
            )
        return requirements

    def _prune_components(self) -> None:
        """Drop schemas nobody references (e.g. models only expanded into parameters)."""
        reachable: set[str] = set()
        queue: list[Any] = [self.paths, self.webhooks]
        while queue:
            value = queue.pop()
            if isinstance(value, dict):
                mapping = cast('JsonSchema', value)
                ref = mapping.get('$ref')
                if isinstance(ref, str):
                    name = self.resolver.component_name(ref)
                    if name is not None and name not in reachable:
                        reachable.add(name)
                        queue.append(self.components.get(name))
                queue.extend(mapping.values())
            elif isinstance(value, list):
                queue.extend(cast('list[object]', value))
        self.components.keep(reachable)

    # --- included documents ---------------------------------------------

    def _merge_document(self, contribution: DocumentContribution) -> None:
        for code, level, message in contribution.notes:
            self.diagnostics.append(
                Diagnostic(code, level, message, origins=(contribution.origin,)),
            )
        self._merge_items(self.paths, 'path', contribution.paths, contribution)
        self._merge_items(self.webhooks, 'webhook', contribution.webhooks, contribution)
        for section, entries in contribution.components.items():
            for name, value in entries.items():
                self._merge_component(section, name, value, contribution)
        for tag in contribution.tags:
            self._merge_named(
                'tag',
                str(tag.get('name')),
                tag,
                self._existing_tag,
                self.raw_tags,
                contribution,
            )
        for key, value in contribution.extensions.items():
            self._merge_named(
                'root',
                key,
                value,
                self._existing_extension,
                self.raw_extensions,
                contribution,
            )

    def _resolve_conflict(
        self,
        conflict: Conflict,
        contribution: DocumentContribution,
        error: type[BuildError],
    ) -> bool:
        """``True`` to take the incoming value."""
        action = contribution.decide(conflict)
        if action == 'error':
            raise error(conflict.describe())
        return action == 'replace'

    def _merge_items(
        self,
        target: dict[str, dict[str, JsonSchema]],
        kind: str,
        items: Mapping[str, Any],
        contribution: DocumentContribution,
    ) -> None:
        for name, item in items.items():
            slot = target.setdefault(name, {})
            for key, value in cast('Mapping[str, Any]', item).items():
                if key not in HTTP_METHODS:
                    if key in slot and slot[key] != value:
                        conflict = Conflict(
                            'path-item',
                            f'{name} {key}',
                            slot[key],
                            value,
                            'an earlier source',
                            contribution.origin,
                        )
                        if not self._resolve_conflict(
                            conflict,
                            contribution,
                            DocumentConflictError,
                        ):
                            continue
                    slot[key] = value
                    continue
                owner_key = (kind, name, key)
                if owner_key in self.owners:
                    conflict = Conflict(
                        'operation' if kind == 'path' else 'webhook',
                        f'{key.upper()} {name}',
                        slot.get(key),
                        value,
                        self.owners[owner_key],
                        contribution.origin,
                    )
                    if not self._resolve_conflict(
                        conflict,
                        contribution,
                        OperationConflictError,
                    ):
                        continue
                    previous_id = (slot.get(key) or {}).get('operationId')
                    self.operation_ids.pop(str(previous_id), None)
                operation_id = cast('JsonSchema', value).get('operationId')
                if isinstance(operation_id, str):
                    if operation_id in self.operation_ids:
                        raise DuplicateOperationIdError(
                            f'operationId {operation_id!r} is used by '
                            f'{self.operation_ids[operation_id]} and {contribution.origin}',
                        )
                    self.operation_ids[operation_id] = contribution.origin
                self.owners[owner_key] = contribution.origin
                slot[key] = value

    def _merge_component(
        self,
        section: str,
        name: str,
        value: Any,
        contribution: DocumentContribution,
    ) -> None:
        raw = self.raw_components.setdefault(section, {})
        existing: Any = None
        existing_origin = 'the described operations'
        if section == 'schemas':
            existing = self.components.get(name)
        elif section == 'securitySchemes':
            existing = self.config.security_schemes.get(name)
            existing_origin = 'OpenAPI(security_schemes=...)'
        if name in raw:
            existing, existing_origin = raw[name]
        if existing is not None:
            if existing == value:
                return
            conflict = Conflict(
                'component',
                f'components/{section}/{name}',
                existing,
                value,
                existing_origin,
                contribution.origin,
            )
            if not self._resolve_conflict(
                conflict,
                contribution,
                ComponentConflictError,
            ):
                return
        raw[name] = (value, contribution.origin)

    def _existing_tag(self, name: str) -> Optional[tuple[Any, str]]:
        for tag in self.config.tags:
            if tag.get('name') == name:
                return tag, 'OpenAPI(tags=...)'
        return None

    def _existing_extension(self, key: str) -> Optional[tuple[Any, str]]:
        if key in self.config.extensions:
            return self.config.extensions[key], 'OpenAPI(extensions=...)'
        return None

    def _merge_named(
        self,
        kind: str,
        key: str,
        value: Any,
        configured: Any,
        raw: dict[str, tuple[Any, str]],
        contribution: DocumentContribution,
    ) -> None:
        existing = raw.get(key) or configured(key)
        if existing is not None and existing[0] != value:
            conflict = Conflict(
                kind,
                key,
                existing[0],
                value,
                existing[1],
                contribution.origin,
            )
            if not self._resolve_conflict(
                conflict,
                contribution,
                DocumentConflictError,
            ):
                return
        raw[key] = (value, contribution.origin)

    # --- document -------------------------------------------------------

    def _document(self) -> dict[str, Any]:
        config = self.config
        document: dict[str, Any] = {'info': copy.deepcopy(config.info)}
        if config.servers:
            document['servers'] = copy.deepcopy(config.servers)
        document['paths'] = {
            path: self._ordered_methods(self.paths[path]) for path in sorted(self.paths)
        }
        sections: dict[str, dict[str, Any]] = {}
        if self.components.as_dict():
            sections['schemas'] = self.components.as_dict()
        if config.security_schemes:
            sections['securitySchemes'] = copy.deepcopy(config.security_schemes)
        for section, entries in self.raw_components.items():
            target = sections.setdefault(section, {})
            target.update({name: value for name, (value, _) in entries.items()})
        components = {
            section: {name: entries[name] for name in sorted(entries)}
            for section, entries in sections.items()
            if entries
        }
        if components:
            document['components'] = components
        tags = copy.deepcopy(config.tags)
        tags = [self.raw_tags.pop(str(tag.get('name')), (tag, ''))[0] for tag in tags]
        tags.extend(value for value, _ in self.raw_tags.values())
        declared = {tag.get('name') for tag in tags}
        tags.extend({'name': name} for name in self.used_tags if name not in declared)
        if tags:
            document['tags'] = tags
        document.update(copy.deepcopy(config.extensions))
        document.update({key: value for key, (value, _) in self.raw_extensions.items()})
        return document

    def _webhooks(self) -> dict[str, dict[str, JsonSchema]]:
        return {name: self._ordered_methods(ops) for name, ops in self.webhooks.items()}

    @staticmethod
    def _ordered_methods(operations: Mapping[str, JsonSchema]) -> dict[str, JsonSchema]:
        """Path-item fields first (``parameters``, ``summary``...), then methods in order."""
        ordered = {
            key: value for key, value in operations.items() if key not in HTTP_METHODS
        }
        ordered.update(
            {
                method: operations[method]
                for method in HTTP_METHODS
                if method in operations
            },
        )
        return ordered


def validate_document(document: Mapping[str, Any]) -> None:
    """Check ``document`` with ``openapi-spec-validator``; 3.0 and 3.1 alike.

    Raises :class:`InvalidDocumentError`; needs the ``validate`` extra.
    """
    try:
        validator: Any = importlib.import_module('openapi_spec_validator')
    except ImportError as exc:
        raise ImportError(
            'validate=True needs openapi-spec-validator: '
            'install qstd-openapi[validate]',
        ) from exc
    try:
        validator.validate(document)
    except Exception as exc:
        message = getattr(exc, 'message', None) or str(exc).split('\n', 1)[0]
        path = [str(part) for part in getattr(exc, 'path', ())]
        where = f' at {" > ".join(path)}' if path else ''
        raise InvalidDocumentError(
            f'The built document is not valid{where}: {message}',
        ) from exc
