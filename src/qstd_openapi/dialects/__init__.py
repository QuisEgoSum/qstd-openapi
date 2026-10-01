from __future__ import annotations

from qstd_openapi.dialects.base import OpenAPIDialect
from qstd_openapi.dialects.openapi30 import OpenAPI30
from qstd_openapi.dialects.openapi31 import OpenAPI31

__all__ = ('VERSIONS', 'OpenAPI30', 'OpenAPI31', 'OpenAPIDialect', 'dialect_for')

VERSIONS = ('3.0', '3.1')
"""Versions :func:`dialect_for` accepts."""


def dialect_for(version: str) -> OpenAPIDialect:
    """The dialect for ``'3.0'`` or ``'3.1'`` (command line, configuration)."""
    if version == '3.0':
        return OpenAPI30()
    if version == '3.1':
        return OpenAPI31()
    raise ValueError(f'Unsupported OpenAPI version {version!r}: use 3.0 or 3.1')
