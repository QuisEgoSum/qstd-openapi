"""The protocol implemented by OpenAPI version dialects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Protocol, Union

from qstd_openapi.markers import File, FileList

JsonSchema = dict[str, Any]


class OpenAPIDialect(Protocol):
    """Everything that depends on the OpenAPI version.

    The rest of the library works with JSON Schema 2020-12 and
    version-neutral markers; a dialect turns them into a concrete document.
    """

    @property
    def version(self) -> str:
        """Value of the root ``openapi`` field."""
        ...

    def file_schema(
        self,
        marker: Union[File, FileList],
        media_type: Optional[str],
    ) -> JsonSchema:
        """Schema for binary content; ``media_type`` is set for whole bodies."""
        ...

    def check_document(self, document: Mapping[str, Any]) -> None:
        """Raise ``ValueError`` if an included document is not of this version."""
        ...

    def extract_webhooks(self, document: dict[str, Any]) -> dict[str, Any]:
        """Remove webhooks from an included document and return them."""
        ...

    def finalize(
        self,
        document: Mapping[str, Any],
        webhooks: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Add version-specific root fields and return the final document."""
        ...
