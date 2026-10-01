"""Including ready OpenAPI documents (``aggregate`` mode).

``Document`` turns a raw document into a contribution: components are
renamed into a namespace, every local ``$ref`` is rewritten, paths get a
prefix and the document's root ``security`` moves into its operations.
The builder then merges contributions in include order; collisions go
through the inclusion's conflict policy.
"""

from __future__ import annotations

import copy
import importlib
import json

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Protocol, Union, cast

from qstd_openapi.core.sources import HTTP_METHODS
from qstd_openapi.errors import UnsupportedDocumentError

JsonObject = dict[str, Any]
ConflictAction = Literal['error', 'keep', 'replace']

_IGNORED_ROOT = ('info', 'servers', 'externalDocs', 'jsonSchemaDialect')
_HANDLED_ROOT = ('openapi', 'paths', 'components', 'tags', 'security', *_IGNORED_ROOT)
_UNNAMESPACED_SECTIONS = frozenset({'securitySchemes'})


@dataclass(frozen=True)
class Conflict:
    """Two sources define the same thing differently."""

    kind: str
    """``operation``, ``webhook``, ``path-item``, ``component``, ``tag`` or ``root``."""
    key: str
    existing: Any
    incoming: Any
    existing_origin: str
    incoming_origin: str

    def describe(self) -> str:
        return (
            f'{self.kind} {self.key} is defined by both {self.existing_origin} '
            f'and {self.incoming_origin}'
        )


class ConflictPolicy(Protocol):
    """Decides each conflict of an included document.

    **Provisional:** the signature may change before 1.0; the string policies
    (``'error'``, ``'keep'``, ``'replace'``) are stable.
    """

    def __call__(self, conflict: Conflict) -> ConflictAction:
        """``'keep'`` the existing value, ``'replace'`` it or ``'error'``."""
        ...


@dataclass
class DocumentContribution:
    origin: str
    policy: Union[ConflictAction, ConflictPolicy]
    paths: JsonObject = field(default_factory=lambda: JsonObject())
    webhooks: JsonObject = field(default_factory=lambda: JsonObject())
    components: dict[str, JsonObject] = field(
        default_factory=lambda: dict[str, JsonObject](),
    )
    tags: list[JsonObject] = field(default_factory=lambda: list[JsonObject]())
    extensions: JsonObject = field(default_factory=lambda: JsonObject())
    notes: list[tuple[str, str, str]] = field(
        default_factory=lambda: list[tuple[str, str, str]](),
    )
    """``(code, level, message)`` diagnostics."""

    def decide(self, conflict: Conflict) -> ConflictAction:
        action = self.policy if isinstance(self.policy, str) else self.policy(conflict)
        if action not in ('error', 'keep', 'replace'):
            raise ValueError(f'Conflict policy returned {action!r}')
        return action


class DocumentChecker(Protocol):
    """The part of :class:`OpenAPIDialect` needed to read a foreign document."""

    def check_document(self, document: Mapping[str, Any]) -> None: ...

    def extract_webhooks(self, document: JsonObject) -> JsonObject: ...


def _decode(token: str) -> str:
    return token.replace('~1', '/').replace('~0', '~')


def _encode(token: str) -> str:
    return token.replace('~', '~0').replace('/', '~1')


class Document:
    """An existing OpenAPI document included into another one.

    ``document`` is a mapping, or a callable returning one (loaded at build
    time). Use :meth:`from_file` for JSON/YAML files. The input is never
    modified.

    - ``path_prefix`` is prepended to every path;
    - ``component_namespace`` renames components to ``namespace_format``
      (``'{namespace}.{name}'``: ``User`` → ``profiles.User``) in every section
      except ``securitySchemes``, which are usually shared between services;
    - ``on_conflict``: ``'error'`` (default), ``'keep'`` the earlier
      definition, ``'replace'`` it, or a :class:`ConflictPolicy` (provisional).

    The document's ``info``, ``servers``, ``externalDocs`` and
    ``jsonSchemaDialect`` are ignored (the including document has its own);
    its root ``security`` is copied into operations without their own.
    """

    def __init__(
        self,
        document: Union[Mapping[str, Any], Callable[[], Mapping[str, Any]]],
        *,
        origin: str,
        path_prefix: str = '',
        component_namespace: Optional[str] = None,
        namespace_format: str = '{namespace}.{name}',
        on_conflict: Union[ConflictAction, ConflictPolicy] = 'error',
    ) -> None:
        if path_prefix and (
            not path_prefix.startswith('/') or path_prefix.endswith('/')
        ):
            raise ValueError(
                f'path_prefix must start and not end with "/": {path_prefix!r}',
            )
        self.origin = origin
        self.path_prefix = path_prefix
        self.component_namespace = component_namespace
        self.namespace_format = namespace_format
        self.on_conflict: Union[ConflictAction, ConflictPolicy] = on_conflict
        if callable(document):
            self._load: Callable[[], Mapping[str, Any]] = document
        else:
            snapshot = copy.deepcopy(dict(document))
            self._check_structure(snapshot)
            self._load = lambda: snapshot

    @classmethod
    def from_file(cls, path: Union[str, Path], **options: Any) -> Document:
        """Load a ``.json`` or ``.yaml``/``.yml`` file (YAML needs PyYAML)."""
        file = Path(path)
        text = file.read_text(encoding='utf-8')
        if file.suffix in ('.yaml', '.yml'):
            yaml: Any = importlib.import_module('yaml')
            loaded: Any = yaml.safe_load(text)
        else:
            loaded = json.loads(text)
        options.setdefault('origin', str(file))
        return cls(cast('Mapping[str, Any]', loaded), **options)

    def collect(self) -> tuple[()]:
        """A document contributes no operations of its own (see :meth:`contribution`)."""
        return ()

    # --- contribution ---------------------------------------------------

    def contribution(self, checker: DocumentChecker) -> DocumentContribution:
        document = copy.deepcopy(dict(self._load()))
        self._check_structure(document)
        try:
            checker.check_document(document)
        except ValueError as exc:
            raise UnsupportedDocumentError(f'{self.origin}: {exc}') from exc

        result = DocumentContribution(self.origin, self.on_conflict)
        renames = self._renames(
            cast('Mapping[str, Any]', document.get('components', {})),
        )
        self._rewrite(document, renames, result)
        root_security = document.get('security')

        for path, item in cast(
            'Mapping[str, JsonObject]',
            document.get('paths', {}),
        ).items():
            if root_security is not None:
                self._push_security(item, root_security)
            result.paths[self._prefixed(path)] = item
        for name, item in checker.extract_webhooks(document).items():
            if root_security is not None:
                self._push_security(cast('JsonObject', item), root_security)
            result.webhooks[name] = item

        for section, entries in cast(
            'Mapping[str, JsonObject]',
            document.get('components', {}),
        ).items():
            result.components[section] = {
                renames.get((section, name), name): value
                for name, value in entries.items()
            }
        result.tags = list(cast('list[JsonObject]', document.get('tags', [])))
        for key, value in document.items():
            if key in _HANDLED_ROOT:
                continue
            result.extensions[key] = value
        for key in _IGNORED_ROOT:
            if key in document:
                result.notes.append(
                    (
                        'ignored-root-field',
                        'info',
                        f'{self.origin}: root {key!r} is not merged',
                    ),
                )
        return result

    @staticmethod
    def _check_structure(document: Mapping[str, Any]) -> None:
        if not isinstance(document.get('openapi'), str):
            raise UnsupportedDocumentError(
                'an OpenAPI document needs a string "openapi" field',
            )
        for key in ('paths', 'components'):
            if key in document and not isinstance(document[key], Mapping):
                raise UnsupportedDocumentError(f'"{key}" must be an object')

    def _renames(self, components: Mapping[str, Any]) -> dict[tuple[str, str], str]:
        if not self.component_namespace:
            return {}
        return {
            (section, name): self.namespace_format.format(
                namespace=self.component_namespace,
                name=name,
            )
            for section, entries in components.items()
            if section not in _UNNAMESPACED_SECTIONS
            for name in cast('Mapping[str, Any]', entries)
        }

    def _prefixed(self, path: str) -> str:
        return f'{self.path_prefix}{path}' if self.path_prefix else path

    def _rewrite_ref(self, ref: str, renames: Mapping[tuple[str, str], str]) -> str:
        tokens = [_decode(token) for token in ref[2:].split('/')]
        if len(tokens) >= 3 and tokens[0] == 'components':
            tokens[2] = renames.get((tokens[1], tokens[2]), tokens[2])
        elif len(tokens) >= 2 and tokens[0] == 'paths':
            tokens[1] = self._prefixed(tokens[1])
        return '#/' + '/'.join(_encode(token) for token in tokens)

    def _rewrite(
        self,
        value: Any,
        renames: Mapping[tuple[str, str], str],
        result: DocumentContribution,
    ) -> None:
        if isinstance(value, list):
            for item in cast('list[object]', value):
                self._rewrite(item, renames, result)
            return
        if not isinstance(value, dict):
            return
        mapping = cast('JsonObject', value)
        ref = mapping.get('$ref')
        if isinstance(ref, str):
            if ref.startswith('#/'):
                mapping['$ref'] = self._rewrite_ref(ref, renames)
            else:
                result.notes.append(
                    (
                        'external-ref',
                        'warning',
                        f'{self.origin}: external $ref {ref!r} is kept as is',
                    ),
                )
        discriminator = mapping.get('discriminator')
        if isinstance(discriminator, dict):
            targets = cast('JsonObject', discriminator).get('mapping')
            if isinstance(targets, dict):
                for key, target in cast('JsonObject', targets).items():
                    if isinstance(target, str) and target.startswith('#/'):
                        cast('JsonObject', targets)[key] = self._rewrite_ref(
                            target,
                            renames,
                        )
        for item in mapping.values():
            self._rewrite(item, renames, result)

    @staticmethod
    def _push_security(item: JsonObject, security: Any) -> None:
        for method in HTTP_METHODS:
            operation = item.get(method)
            if isinstance(operation, dict) and 'security' not in operation:
                cast('JsonObject', operation)['security'] = copy.deepcopy(security)
