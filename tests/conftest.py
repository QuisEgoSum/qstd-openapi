# pyright: reportPrivateUsage=false
# The shadow build hooks into the private builder on purpose.
"""Every document built by the test suite is also built for OpenAPI 3.0 and validated.

Assertions in the tests describe the 3.1 output; this shadow build checks that
the same scenarios produce a valid 3.0 document (the dialect layer contract).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest

from qstd_openapi.core import document as document_module
from qstd_openapi.dialects import OpenAPI30, OpenAPI31


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        'markers',
        'no_shadow: skip the shadow OpenAPI 3.0 build (side effects are counted, '
        'or the document is not meant to validate)',
    )


@pytest.fixture(autouse=True)
def shadow_openapi30_build(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    node: Any = cast(Any, request).node
    if node.get_closest_marker('no_shadow'):
        yield
        return
    validator: Any = pytest.importorskip('openapi_spec_validator')
    original = document_module._Builder.build

    def build(self: Any) -> Any:
        result = original(self)
        if isinstance(self.config.dialect, OpenAPI31):
            variant = self.config.derive(dialect=OpenAPI30())
            shadow = original(document_module._Builder(variant, self.sources))
            assert shadow.document['openapi'] == '3.0.3'
            validator.validate(shadow.document)
        return result

    monkeypatch.setattr(document_module._Builder, 'build', build)
    yield
