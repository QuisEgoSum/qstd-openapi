"""Error provider for "static error classes".

The convention: an application error class has a unique integer ``code``,
a ``message`` (usually constant) and public annotated payload fields, and is
serialized as ``{"code": ..., "error": <class name>, "message": ..., **payload}``.
The HTTP status comes from the project (a function, a class attribute or a
mapping of base classes). Nothing here imports project code.

Usage::

    from qstd_openapi.contrib.app_errors import AppErrors

    OpenAPI(..., errors=[AppErrors(base=ApplicationError, status=get_http_status)])
"""

from __future__ import annotations

import sys

from collections.abc import Mapping
from typing import (
    Any,
    Callable,
    ClassVar,
    Optional,
    cast,
    get_origin,
    get_type_hints,
)

from qstd_openapi._compat import is_class
from qstd_openapi.core.error_responses import ErrorResponse
from qstd_openapi.core.schemas import JsonSchema
from qstd_openapi.errors import ErrorAnnotationError
from qstd_openapi.markers import Ref

__all__ = ('AppErrors',)

MESSAGE_MODE_ATTR = '__openapi_message__'
"""Class attribute forcing the message schema: ``'const'`` or ``'dynamic'``."""


class AppErrors:
    """Describe application error classes derived from ``base``.

    Status resolution, first match wins:

    1. ``status`` — a callable ``(error_class) -> int`` (use the same function
       the exception handler uses, so the document cannot drift);
    2. the class attribute named ``status_attr`` (``status_code``), if set;
    3. ``status_by_class`` — the nearest base class in the MRO;
    4. ``default_status``.

    The message is a ``const`` when the class defines a constant one; it is a
    plain string when it is missing, contains ``{`` (a template filled in at
    runtime) or the class sets ``__openapi_message__ = 'dynamic'``.

    Payload fields are the public annotated attributes over the MRO; names
    starting with ``_`` and ``ClassVar`` annotations are skipped, so the
    schema follows a ``to_dict()`` built by the same rule.

    Every step is a public method a subclass may override: ``status_for``,
    ``schema_for`` (the whole schema), ``payload_fields`` (which fields and
    their types), ``code_schema`` and ``message_schema``. For a different
    convention altogether implement ``ErrorProvider`` instead.
    """

    def __init__(
        self,
        base: type,
        *,
        status: Optional[Callable[[type], int]] = None,
        status_attr: Optional[str] = 'status_code',
        status_by_class: Optional[Mapping[Any, int]] = None,
        default_status: int = 500,
        code_field: str = 'code',
        message_field: str = 'message',
        name_field: str = 'error',
    ) -> None:
        self.base = base
        self._status = status
        self._status_attr = status_attr
        self._status_by_class = dict(status_by_class or {})
        self._default_status = default_status
        self._code_field = code_field
        self._message_field = message_field
        self._name_field = name_field

    def supports(self, error: object) -> bool:
        return is_class(error) and issubclass(error, self.base)

    def describe(self, error: object) -> ErrorResponse:
        error_class = cast('type', error)
        return ErrorResponse(
            status=self.status_for(error_class),
            schema=self.schema_for(error_class),
            name=error_class.__name__,
        )

    def status_for(self, error: type) -> int:
        if self._status is not None:
            return self._status(error)
        if self._status_attr:
            value = getattr(error, self._status_attr, None)
            if isinstance(value, int):
                return value
        for klass in error.__mro__:
            if klass in self._status_by_class:
                return self._status_by_class[klass]
        return self._default_status

    def schema_for(self, error: type) -> JsonSchema:
        properties: dict[str, Any] = {
            self._code_field: self.code_schema(error),
            self._name_field: {'type': 'string', 'const': error.__name__},
            self._message_field: self.message_schema(error),
        }
        for name, annotation in self.payload_fields(error).items():
            properties[name] = Ref(annotation)
        schema: JsonSchema = {
            'title': error.__name__,
            'type': 'object',
            'properties': properties,
            'required': list(properties),
            'additionalProperties': False,
        }
        doc = vars(error).get('__doc__')
        if isinstance(doc, str) and doc.strip():
            schema['description'] = doc.strip()
        return schema

    def code_schema(self, error: type) -> JsonSchema:
        code = getattr(error, self._code_field, None)
        if isinstance(code, int) and not isinstance(code, bool):
            return {'type': 'integer', 'const': code}
        return {'type': 'integer'}

    def message_schema(self, error: type) -> JsonSchema:
        message = getattr(error, self._message_field, None)
        mode = getattr(error, MESSAGE_MODE_ATTR, None)
        if not isinstance(message, str):
            return {'type': 'string'}
        if mode == 'const' or (mode != 'dynamic' and '{' not in message):
            return {'type': 'string', 'const': message}
        return {'type': 'string', 'examples': [message]}

    def payload_fields(self, error: type) -> dict[str, Any]:
        """Payload field names and types: public annotated fields over the MRO.

        Base classes come first; ``code``, ``message``, the name field,
        ``status_code``, ``_``-prefixed names and ``ClassVar`` are skipped.
        """
        skip = {self._code_field, self._message_field, self._name_field, 'status_code'}
        names: list[str] = []
        for klass in reversed(error.__mro__):
            for name in vars(klass).get('__annotations__', {}):
                if not name.startswith('_') and name not in skip and name not in names:
                    names.append(name)
        if not names:
            return {}
        try:
            hints = get_type_hints(error, include_extras=True)
        except Exception as exc:
            raise ErrorAnnotationError(
                f'Cannot evaluate annotations of {error.__module__}.{error.__qualname__}: '
                f'{exc}. On Python {sys.version_info.major}.{sys.version_info.minor} '
                'use typing.Optional/Union instead of "X | Y" in annotations.',
            ) from exc
        return {
            name: hints[name]
            for name in names
            if name in hints and get_origin(hints[name]) is not ClassVar
        }
