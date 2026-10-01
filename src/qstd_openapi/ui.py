"""Documentation pages: Redoc and Swagger UI.

A renderer only knows the URL of the specification; framework integrations
decide where pages are served. Frontend bundles are loaded from a CDN by
default; pass your own URLs to self-host them.
"""

from __future__ import annotations

import html
import json

from collections.abc import Mapping
from typing import Any, Optional, Protocol

__all__ = ('DocsRenderer', 'Redoc', 'SwaggerUI')

REDOC_JS = 'https://cdn.jsdelivr.net/npm/redoc@2.5.4/bundles/redoc.standalone.js'
SWAGGER_UI_JS = (
    'https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.1/swagger-ui-bundle.js'
)
SWAGGER_UI_CSS = 'https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.1/swagger-ui.css'


class DocsRenderer(Protocol):
    def render(self, *, spec_url: str, title: str) -> str:
        """A complete HTML page showing the document at ``spec_url``."""
        ...


def _script_json(value: Any) -> str:
    """JSON safe to embed inside a ``<script>`` element."""
    return (
        json.dumps(value, ensure_ascii=False)
        .replace('<', '\\u003c')
        .replace('>', '\\u003e')
        .replace('&', '\\u0026')
    )


def _page(title: str, head: str, body: str) -> str:
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{html.escape(title)}</title>\n'
        f'{head}'
        '</head>\n'
        f'<body>\n{body}</body>\n'
        '</html>\n'
    )


class Redoc:
    """Redoc page; ``options`` are Redoc configuration options."""

    def __init__(
        self,
        *,
        js_url: str = REDOC_JS,
        options: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.js_url = js_url
        self.options = dict(options or {})

    def render(self, *, spec_url: str, title: str) -> str:
        body = (
            '<div id="redoc-container"></div>\n'
            f'<script src="{html.escape(self.js_url)}"></script>\n'
            '<script>\n'
            f'Redoc.init({_script_json(spec_url)}, {_script_json(self.options)}, '
            'document.getElementById("redoc-container"));\n'
            '</script>\n'
        )
        return _page(title, '<style>body { margin: 0; padding: 0; }</style>\n', body)


class SwaggerUI:
    """Swagger UI page; ``options`` are passed to ``SwaggerUIBundle``."""

    def __init__(
        self,
        *,
        js_url: str = SWAGGER_UI_JS,
        css_url: str = SWAGGER_UI_CSS,
        options: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.js_url = js_url
        self.css_url = css_url
        self.options = dict(options or {})

    def render(self, *, spec_url: str, title: str) -> str:
        options = {
            'dom_id': '#swagger-ui',
            'deepLinking': True,
            **self.options,
            'url': spec_url,
        }
        head = f'<link rel="stylesheet" href="{html.escape(self.css_url)}">\n'
        body = (
            '<div id="swagger-ui"></div>\n'
            f'<script src="{html.escape(self.js_url)}"></script>\n'
            '<script>\n'
            f'window.ui = SwaggerUIBundle({_script_json(options)});\n'
            '</script>\n'
        )
        return _page(title, head, body)
