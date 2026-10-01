"""Framework-agnostic, declarative OpenAPI documentation."""

from qstd_openapi import markers, openapi
from qstd_openapi.core import (
    BuildResult,
    Conflict,
    Diagnostic,
    Document,
    ErrorProvider,
    ErrorResponse,
    OpenAPI,
    PathTag,
    RouteEntry,
    Routes,
    ScopeFilter,
    TypeOverride,
    WebhookSet,
    validate_document,
)
from qstd_openapi.errors import (
    AttachError,
    BuildError,
    QstdOpenAPIError,
    ScalarConflictError,
)
from qstd_openapi.meta import OperationMeta, read_operation
from qstd_openapi.serialization import dumps, dumps_yaml
from qstd_openapi.tags import tags_from_markdown

__all__ = (
    'AttachError',
    'BuildError',
    'BuildResult',
    'Conflict',
    'Diagnostic',
    'Document',
    'ErrorProvider',
    'ErrorResponse',
    'OpenAPI',
    'OperationMeta',
    'PathTag',
    'QstdOpenAPIError',
    'RouteEntry',
    'Routes',
    'ScalarConflictError',
    'ScopeFilter',
    'TypeOverride',
    'WebhookSet',
    'dumps',
    'dumps_yaml',
    'markers',
    'openapi',
    'read_operation',
    'tags_from_markdown',
    'validate_document',
)
