"""Tag descriptions from Markdown files."""

from __future__ import annotations

from pathlib import Path

import pytest

from openapi_spec_validator import validate

from qstd_openapi import OpenAPI, Routes, openapi, tags_from_markdown


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    directory = tmp_path / 'users_api'
    directory.mkdir()
    (directory / 'Users.md').write_text('Registration and **login**.\n', 'utf-8')
    (directory / 'User profile.md').write_text('\nThe current user.\n', 'utf-8')
    (directory / '.draft.md').write_text('hidden', 'utf-8')
    (directory / 'notes.txt').write_text('ignored', 'utf-8')
    (directory / 'nested').mkdir()
    return directory


def test_files_become_tags_sorted_by_name(docs: Path) -> None:
    assert tags_from_markdown(docs) == [
        {'name': 'User profile', 'description': 'The current user.'},
        {'name': 'Users', 'description': 'Registration and **login**.'},
    ]


def test_explicit_tags_keep_order_fields_and_descriptions(docs: Path) -> None:
    explicit = [
        {'name': 'Users', 'x-displayName': 'Users'},
        {'name': 'User profile', 'description': 'Written in code'},
        {'name': 'Admin'},
    ]
    assert tags_from_markdown(docs, explicit) == [
        {
            'name': 'Users',
            'x-displayName': 'Users',
            'description': 'Registration and **login**.',
        },
        {'name': 'User profile', 'description': 'Written in code'},
        {'name': 'Admin'},
    ]
    assert explicit[0] == {'name': 'Users', 'x-displayName': 'Users'}


def test_missing_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        tags_from_markdown(tmp_path / 'missing')


def test_document_with_tags_from_files(docs: Path) -> None:
    @openapi.tag('Users')
    async def register_user() -> None:
        pass

    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1.0.0'},
        tags=tags_from_markdown(docs),
    )
    spec.include(Routes(('/users', 'post', register_user)))
    document = spec.build().document
    validate(document)
    assert [tag['name'] for tag in document['tags']] == ['User profile', 'Users']
