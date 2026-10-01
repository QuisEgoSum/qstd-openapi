"""Declarative API: decorators, ``describe`` and ``attach``.

Every decorator here is ``describe`` with a single option, so all of them
follow the same rules. Decorators return the decorated object unchanged;
metadata is stored on the object itself (see :mod:`qstd_openapi.meta.storage`)
and is only interpreted when a document is built.

Usage::

    from qstd_openapi import openapi

    @openapi.tag('Users')
    @openapi.errors(UserAlreadyExistsError)
    @openapi.response(UserDTO, status=201)
    async def register_user(request, body): ...
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping, Sequence
from enum import Enum
from typing import Any, Callable, Optional, TypeVar, Union, cast

from typing_extensions import TypeAlias, TypedDict, Unpack

from qstd_openapi.markers import File, FileList, FormFields
from qstd_openapi.meta.model import (
    BodyPart,
    ErrorRef,
    Example,
    Examples,
    OperationPatch,
    Parameter,
    ParameterLocation,
    ParameterModel,
    ResponseHeader,
    ResponsePart,
    Security,
    StatusCode,
    Webhook,
)
from qstd_openapi.meta.storage import attach_patch

__all__ = (
    'DescribeOptions',
    'DocumentationOptions',
    'ErrorLike',
    'Example',
    'ExampleValue',
    'OperationOptions',
    'Parameter',
    'ParameterModel',
    'ResponseHeader',
    'ResponsePart',
    'SchemaLike',
    'Security',
    'SecurityValue',
    'Webhook',
    'attach',
    'body',
    'body_binary',
    'body_form_data_file',
    'body_form_data_files',
    'body_one_of',
    'cookie',
    'cookies',
    'deprecated',
    'describe',
    'description',
    'errors',
    'exclude',
    'extra',
    'header',
    'headers',
    'no_content',
    'operation_id',
    'params',
    'path',
    'query',
    'response',
    'response_file',
    'response_header',
    'responses',
    'scope',
    'security',
    'summary',
    'tag',
    'webhook',
)

F = TypeVar('F', bound=Callable[..., Any])

JSON = 'application/json'

SecurityValue: TypeAlias = Union[str, Mapping[str, Sequence[str]], Security]
"""A scheme name, ``{scheme: [scopes]}`` (all required together) or ``Security``."""

SchemaLike: TypeAlias = object
"""Anything a schema provider understands: a Pydantic model, a dataclass, a
type such as ``list[UserDTO]`` or ``Optional[int]``, a ``TypeAdapter``, a raw
JSON Schema dict (with ``markers.Ref`` inside) or a marker (``File``...)."""

ErrorLike: TypeAlias = type
"""An error class (usually an exception) for the document's error providers.

``ErrorProvider.supports`` takes any object at runtime; the annotation is a
class so that a string or an exception instance is a type error."""

ExampleValue: TypeAlias = object
"""An example value, or :class:`Example` with a summary and a description."""

ExamplesArg: TypeAlias = Optional[Mapping[str, ExampleValue]]

ResponseValue: TypeAlias = Union[SchemaLike, Sequence[SchemaLike], ResponsePart, None]
"""``responses={status: ...}`` value: a schema, alternatives (``oneOf``), ``None``
(no body) or a ``ResponsePart``."""


class OperationOptions(TypedDict, total=False):
    """Operation fields that framework route decorators may accept themselves."""

    summary: str
    description: str
    operation_id: str
    deprecated: bool
    tags: Union[str, Iterable[str]]


class DocumentationOptions(TypedDict, total=False):
    """Options only the library understands (never passed to a framework)."""

    exclude: bool
    webhook: Union[str, Webhook]
    scope: Union[Hashable, Iterable[Hashable]]
    security: Union[SecurityValue, Iterable[SecurityValue]]
    body: SchemaLike
    body_media_type: str
    body_examples: Mapping[str, ExampleValue]
    """Named examples of the request body: ``{'name': value | Example}``."""
    query: SchemaLike
    """A model whose fields become query parameters."""
    path: SchemaLike
    headers: SchemaLike
    cookies: SchemaLike
    parameters: Iterable[Union[Parameter, ParameterModel]]
    response: SchemaLike
    """Schema of the ``200`` response."""
    response_media_type: str
    response_examples: Mapping[StatusCode, Mapping[str, ExampleValue]]
    """Named examples per response status: ``{201: {'name': value | Example}}``."""
    responses: Mapping[StatusCode, ResponseValue]
    """``{status: schema | [schema, ...] | None | ResponsePart}``."""
    errors: Iterable[ErrorLike]
    errors_media_type: str
    extra: Mapping[str, Any]
    """Raw OpenAPI operation fields, written for the dialect being built."""


class DescribeOptions(OperationOptions, DocumentationOptions, total=False):
    """Options shared by :func:`describe`, :func:`attach` and router wrappers."""


def attach(target: F, /, **options: Unpack[DescribeOptions]) -> F:
    """Attach metadata to ``target`` and return it unchanged.

    Meant for project decorators, middlewares and validators that document
    what they add, e.g. ``openapi.attach(wrapper, errors=[...])``.
    """
    attach_patch(target, _build_patch(options), 'attach')
    return target


def describe(**options: Unpack[DescribeOptions]) -> Callable[[F], F]:
    """Attach several documentation options with one decorator."""
    return _decorator(_build_patch(options), 'describe')


# --- single-purpose decorators ---------------------------------------------


def tag(*names: str) -> Callable[[F], F]:
    """Add one or more tags to an operation."""
    return _decorator(OperationPatch(tags=names), 'tag')


def summary(text: str) -> Callable[[F], F]:
    """Set the operation summary."""
    return _decorator(OperationPatch(summary=text), 'summary')


def description(text: str) -> Callable[[F], F]:
    """Set the operation description."""
    return _decorator(OperationPatch(description=text), 'description')


def operation_id(value: str) -> Callable[[F], F]:
    """Set an explicit OpenAPI ``operationId``."""
    return _decorator(OperationPatch(operation_id=value), 'operation_id')


def deprecated(value: bool = True) -> Callable[[F], F]:
    """Mark an operation as deprecated (or clear the flag with ``False``)."""
    return _decorator(OperationPatch(deprecated=value), 'deprecated')


def exclude(value: bool = True) -> Callable[[F], F]:
    """Exclude an operation from documents (or restore it with ``False``)."""
    return _decorator(OperationPatch(exclude=value), 'exclude')


def scope(*scopes: Hashable) -> Callable[[F], F]:
    """Label an operation for selection by :class:`ScopeFilter`."""
    return _decorator(OperationPatch(scopes=scopes), 'scope')


def security(
    scheme: SecurityValue,
    scopes: Optional[Sequence[str]] = None,
) -> Callable[[F], F]:
    """Add one security requirement (several decorators mean alternatives)."""
    return _decorator(
        OperationPatch(security=(_security(scheme, scopes),)),
        'security',
    )


def webhook(
    name: str,
    method: str = 'post',
    *,
    scope: Union[Hashable, Iterable[Hashable], None] = None,
) -> Callable[[F], F]:
    """Mark a function that *sends* a webhook; it is documented, not routed."""
    return _decorator(
        OperationPatch(webhook=Webhook(name, method.lower()), scopes=_as_tuple(scope)),
        'webhook',
    )


def body(
    schema: SchemaLike,
    media_type: str = JSON,
    *,
    examples: ExamplesArg = None,
) -> Callable[[F], F]:
    """Describe one request body schema and optional named examples."""
    part = BodyPart(media_type, schema, _examples(examples))
    return _decorator(OperationPatch(body=(part,)), 'body')


def body_one_of(
    *schemas: SchemaLike,
    media_type: str = JSON,
    examples: ExamplesArg = None,
) -> Callable[[F], F]:
    """Describe alternative request body schemas combined with ``oneOf``."""
    parts = [BodyPart(media_type, s) for s in schemas]
    if examples:
        parts.append(BodyPart(media_type, None, _examples(examples)))
    return _decorator(OperationPatch(body=tuple(parts)), 'body_one_of')


def body_binary(media_type: str = '*/*') -> Callable[[F], F]:
    """Describe an arbitrary binary request body."""
    return _decorator(
        OperationPatch(body=(BodyPart(media_type, File()),)),
        'body_binary',
    )


def body_form_data_file(
    name: str = 'file',
    *,
    description: Optional[str] = None,
    required: bool = True,
    media_type: str = 'multipart/form-data',
) -> Callable[[F], F]:
    """Describe one file field in a multipart form body."""
    schema = FormFields.of({name: File()}, (name,) if required else (), description)
    return _decorator(
        OperationPatch(body=(BodyPart(media_type, schema),)),
        'body_form_data_file',
    )


def body_form_data_files(
    name: str = 'files',
    *,
    max_items: Optional[int] = None,
    description: Optional[str] = None,
    required: bool = True,
    media_type: str = 'multipart/form-data',
) -> Callable[[F], F]:
    """Describe a list of files in a multipart form body."""
    schema = FormFields.of(
        {name: FileList(max_items)},
        (name,) if required else (),
        description,
    )
    return _decorator(
        OperationPatch(body=(BodyPart(media_type, schema),)),
        'body_form_data_files',
    )


def query(
    model_or_name: Union[str, SchemaLike],
    schema: SchemaLike = str,
    *,
    required: Optional[bool] = None,
    description: Optional[str] = None,
    deprecated: bool = False,
    examples: ExamplesArg = None,
) -> Callable[[F], F]:
    """``query(Model)`` expands the model's fields; ``query('page', int)`` adds one."""
    return _parameter_decorator(
        'query',
        'query',
        model_or_name,
        schema,
        required,
        description,
        deprecated,
        examples,
    )


def path(
    model_or_name: Union[str, SchemaLike],
    schema: SchemaLike = str,
    *,
    description: Optional[str] = None,
    deprecated: bool = False,
    examples: ExamplesArg = None,
) -> Callable[[F], F]:
    """Add a required path parameter or expand the fields of a model."""
    return _parameter_decorator(
        'path',
        'path',
        model_or_name,
        schema,
        True,
        description,
        deprecated,
        examples,
    )


params = path


def header(
    name: str,
    schema: SchemaLike = str,
    *,
    required: Optional[bool] = None,
    description: Optional[str] = None,
    deprecated: bool = False,
    examples: ExamplesArg = None,
) -> Callable[[F], F]:
    """Add one header parameter."""
    return _parameter_decorator(
        'header',
        'header',
        name,
        schema,
        required,
        description,
        deprecated,
        examples,
    )


def headers(model: SchemaLike) -> Callable[[F], F]:
    """Expand a model's fields into header parameters."""
    return _decorator(
        OperationPatch(parameters=(ParameterModel('header', model),)),
        'headers',
    )


def cookie(
    name: str,
    schema: SchemaLike = str,
    *,
    required: Optional[bool] = None,
    description: Optional[str] = None,
    deprecated: bool = False,
    examples: ExamplesArg = None,
) -> Callable[[F], F]:
    """Add one cookie parameter."""
    return _parameter_decorator(
        'cookie',
        'cookie',
        name,
        schema,
        required,
        description,
        deprecated,
        examples,
    )


def cookies(model: SchemaLike) -> Callable[[F], F]:
    """Expand a model's fields into cookie parameters."""
    return _decorator(
        OperationPatch(parameters=(ParameterModel('cookie', model),)),
        'cookies',
    )


def response(
    schema: SchemaLike,
    status: StatusCode = 200,
    media_type: str = JSON,
    description: Optional[str] = None,
    *,
    examples: ExamplesArg = None,
) -> Callable[[F], F]:
    """Describe one response schema and optional named examples."""
    part = ResponsePart(
        status,
        media_type,
        schema,
        description,
        examples=_examples(examples),
    )
    return _decorator(OperationPatch(responses=(part,)), 'response')


def responses(
    *schemas: SchemaLike,
    status: StatusCode = 200,
    media_type: str = JSON,
    description: Optional[str] = None,
    examples: ExamplesArg = None,
) -> Callable[[F], F]:
    """Several alternative bodies (``oneOf``) for one status."""
    parts = [ResponsePart(status, media_type, s, description) for s in schemas]
    if examples:
        parts.append(ResponsePart(status, media_type, examples=_examples(examples)))
    return _decorator(OperationPatch(responses=tuple(parts)), 'responses')


def response_file(
    media_type: str = '*/*',
    status: StatusCode = 200,
    description: Optional[str] = None,
) -> Callable[[F], F]:
    """Describe a binary response."""
    return _decorator(
        OperationPatch(
            responses=(ResponsePart(status, media_type, File(), description),),
        ),
        'response_file',
    )


def response_header(
    name: str,
    schema: SchemaLike = str,
    *,
    status: StatusCode = 200,
    description: Optional[str] = None,
    required: bool = False,
) -> Callable[[F], F]:
    """Add a header to the response for one status."""
    part = ResponsePart(
        status,
        headers=(ResponseHeader(name, schema, description, required),),
    )
    return _decorator(OperationPatch(responses=(part,)), 'response_header')


def no_content(
    status: StatusCode = 204,
    description: Optional[str] = None,
) -> Callable[[F], F]:
    """Describe a response status without a body."""
    return _decorator(
        OperationPatch(responses=(ResponsePart(status, description=description),)),
        'no_content',
    )


def errors(*errors: ErrorLike, media_type: str = JSON) -> Callable[[F], F]:
    """Add error classes handled by the document's error providers."""
    return _decorator(
        OperationPatch(errors=tuple(ErrorRef(e, media_type) for e in errors)),
        'errors',
    )


def extra(fields: Mapping[str, Any]) -> Callable[[F], F]:
    """Raw OpenAPI operation fields, written for the dialect being built."""
    return _decorator(OperationPatch(extra=(fields,)), 'extra')


# --- helpers ----------------------------------------------------------------


def _decorator(patch: OperationPatch, api: str) -> Callable[[F], F]:
    def decorate(target: F) -> F:
        attach_patch(target, patch, api)
        return target

    return decorate


def _parameter_decorator(
    api: str,
    location: ParameterLocation,
    model_or_name: Union[str, SchemaLike],
    schema: SchemaLike,
    required: Optional[bool],
    description: Optional[str],
    deprecated: bool,
    examples: ExamplesArg = None,
) -> Callable[[F], F]:
    parameter: Union[Parameter, ParameterModel]
    if isinstance(model_or_name, str):
        parameter = Parameter(
            location,
            model_or_name,
            schema,
            required,
            description,
            deprecated,
            _examples(examples),
        )
    elif examples:
        raise TypeError(
            f'{api}(Model, examples=...): examples belong to one parameter; '
            f'use {api}(name, schema, examples=...) or examples in the model',
        )
    else:
        parameter = ParameterModel(location, model_or_name)
    return _decorator(OperationPatch(parameters=(parameter,)), api)


def _examples(examples: ExamplesArg) -> Examples:
    if not examples:
        return ()
    return tuple(
        (name, value if isinstance(value, Example) else Example(value))
        for name, value in examples.items()
    )


def _as_tuple(value: Any) -> tuple[Any, ...]:
    """One value or an iterable of values; strings and enum members are single."""
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Enum)) or not isinstance(value, Iterable):
        return (value,)
    return tuple(cast('Iterable[Any]', value))


def _security(value: SecurityValue, scopes: Optional[Sequence[str]] = None) -> Security:
    if isinstance(value, Security):
        if scopes is not None:
            raise TypeError('scopes cannot be combined with a Security object')
        return value
    if isinstance(value, str):
        return Security(((value, tuple(scopes or ())),))
    if scopes is not None:
        raise TypeError('scopes can only be given together with a single scheme name')
    return Security(tuple((name, tuple(values)) for name, values in value.items()))


def _security_list(value: Any) -> tuple[Security, ...]:
    if isinstance(value, (str, Security, Mapping)):
        return (_security(cast('SecurityValue', value)),)
    return tuple(_security(item) for item in cast('Iterable[SecurityValue]', value))


def _responses(
    statuses: Mapping[StatusCode, ResponseValue],
    media_type: str,
) -> list[ResponsePart]:
    parts: list[ResponsePart] = []
    for status, value in statuses.items():
        if value is None:
            parts.append(ResponsePart(status))
        elif isinstance(value, ResponsePart):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            schemas = cast('Sequence[Any]', value)
            parts.extend(ResponsePart(status, media_type, s) for s in schemas)
        else:
            parts.append(ResponsePart(status, media_type, value))
    return parts


def _build_patch(options: DescribeOptions) -> OperationPatch:
    unknown = set(options) - set(DescribeOptions.__annotations__)
    if unknown:
        raise TypeError(f'Unknown describe options: {", ".join(sorted(unknown))}')

    parameters: list[Union[Parameter, ParameterModel]] = list(
        options.get('parameters', ()),
    )
    locations: tuple[tuple[str, ParameterLocation], ...] = (
        ('query', 'query'),
        ('path', 'path'),
        ('headers', 'header'),
        ('cookies', 'cookie'),
    )
    for key, location in locations:
        model = options.get(key)
        if model is not None:
            parameters.append(ParameterModel(location, model))

    body_parts: tuple[BodyPart, ...] = ()
    body_examples = _examples(options.get('body_examples'))
    if options.get('body') is not None or body_examples:
        body_parts = (
            BodyPart(
                options.get('body_media_type', JSON),
                options.get('body'),
                body_examples,
            ),
        )

    response_media = options.get('response_media_type', JSON)
    response_parts: list[ResponsePart] = []
    if options.get('response') is not None:
        response_parts.append(
            ResponsePart(200, response_media, options.get('response')),
        )
    response_parts.extend(_responses(options.get('responses', {}), response_media))
    for status, examples in options.get('response_examples', {}).items():
        response_parts.append(
            ResponsePart(status, response_media, examples=_examples(examples)),
        )

    hook = options.get('webhook')
    errors_media = options.get('errors_media_type', JSON)
    extra_fields = options.get('extra')

    return OperationPatch(
        summary=options.get('summary'),
        description=options.get('description'),
        operation_id=options.get('operation_id'),
        deprecated=options.get('deprecated'),
        exclude=options.get('exclude'),
        webhook=Webhook(hook) if isinstance(hook, str) else hook,
        tags=_as_tuple(options.get('tags')),
        scopes=_as_tuple(options.get('scope')),
        security=_security_list(options['security']) if 'security' in options else (),
        parameters=tuple(parameters),
        body=body_parts,
        responses=tuple(response_parts),
        errors=tuple(ErrorRef(e, errors_media) for e in options.get('errors', ())),
        extra=(extra_fields,) if extra_fields is not None else (),
    )
