from __future__ import annotations

import pytest

from qstd_openapi import dumps_yaml
from qstd_openapi.ui import Redoc, SwaggerUI


def test_redoc_page() -> None:
    page = Redoc(options={'hideDownloadButton': True}).render(
        spec_url='/openapi.json',
        title='Users API',
    )
    assert page.startswith('<!DOCTYPE html>')
    assert '<title>Users API</title>' in page
    assert 'redoc@2.5.4/bundles/redoc.standalone.js' in page
    assert 'Redoc.init("/openapi.json", {"hideDownloadButton": true}' in page


def test_swagger_ui_page_and_self_hosted_assets() -> None:
    page = SwaggerUI(
        js_url='/static/swagger-ui-bundle.js',
        css_url='/static/swagger-ui.css',
        options={'docExpansion': 'none'},
    ).render(spec_url='/api/openapi.json', title='Users API')
    assert '<script src="/static/swagger-ui-bundle.js"></script>' in page
    assert '<link rel="stylesheet" href="/static/swagger-ui.css">' in page
    assert '"url": "/api/openapi.json"' in page
    assert '"docExpansion": "none"' in page


def test_title_and_options_are_escaped() -> None:
    page = Redoc(options={'x': '</script><script>alert(1)</script>'}).render(
        spec_url='/openapi.json?a=1&b=2',
        title='<b>API</b>',
    )
    assert '<title>&lt;b&gt;API&lt;/b&gt;</title>' in page
    assert '</script><script>alert' not in page
    assert '\\u003c/script\\u003e' in page
    assert '/openapi.json?a=1\\u0026b=2' in page


def test_yaml_output() -> None:
    pytest.importorskip('yaml')
    document = {'openapi': '3.1.0', 'info': {'title': 'Пользователи', 'version': '1'}}
    assert dumps_yaml(document) == (
        'openapi: 3.1.0\ninfo:\n  title: Пользователи\n  version: \'1\'\n'
    )
    assert dumps_yaml(document, canonical=True).startswith('info:')
