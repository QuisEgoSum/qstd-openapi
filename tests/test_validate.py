"""``OpenAPI(validate=True)``: the built document is checked by openapi-spec-validator."""

from __future__ import annotations

import sys

from typing import Any

import pytest

from qstd_openapi import BuildError, OpenAPI, Routes, openapi
from qstd_openapi.dialects import OpenAPI30
from qstd_openapi.errors import InvalidDocumentError


def make_spec(**kwargs: Any) -> OpenAPI:
    @openapi.extra({'responses': {'200': {'content': 'not a mapping'}}})
    async def get_user() -> None:
        pass

    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1.0.0'},
        schemas=(),
        **kwargs,
    )
    spec.include(Routes(('/users/me', 'get', get_user)))
    return spec


@pytest.mark.no_shadow
def test_invalid_document_is_reported() -> None:
    with pytest.raises(
        InvalidDocumentError,
        match="at paths > /users/me > get > responses > 200 > content: 'not a mapping'",
    ) as info:
        make_spec(validate=True).build()
    assert isinstance(info.value, BuildError)
    assert info.value.code == 'invalid-document'


@pytest.mark.no_shadow
def test_without_validation_the_document_is_built() -> None:
    assert make_spec().build().document['openapi'] == '3.1.0'


@pytest.mark.no_shadow
def test_failed_validation_is_not_cached() -> None:
    spec = make_spec(validate=True)
    for _ in range(2):
        with pytest.raises(InvalidDocumentError):
            spec.build()


def test_valid_document_in_both_dialects() -> None:
    @openapi.response(int)
    async def count_users() -> None:
        pass

    for dialect in (None, OpenAPI30()):
        spec = OpenAPI(
            info={'title': 'Users API', 'version': '1.0.0'},
            validate=True,
            dialect=dialect,
        )
        spec.include(Routes(('/users/count', 'get', count_users)))
        assert spec.build().document['paths']


@pytest.mark.no_shadow
def test_missing_validator_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, 'openapi_spec_validator', None)
    with pytest.raises(ImportError, match=r'qstd-openapi\[validate\]'):
        make_spec(validate=True).build()
