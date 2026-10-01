"""Tag descriptions kept as Markdown files next to the code.

A common layout keeps one file per tag, one directory per service or
document::

    docs/openapi/users_api/Users.md
    docs/openapi/users_api/Profile.md

Usage::

    from qstd_openapi import OpenAPI, tags_from_markdown

    spec = OpenAPI(
        info={'title': 'Users API', 'version': '1.0.0'},
        tags=tags_from_markdown('docs/openapi/users_api'),
    )
"""

from __future__ import annotations

import copy
import os

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Union

__all__ = ('tags_from_markdown',)


def tags_from_markdown(
    directory: Union[str, os.PathLike[str]],
    tags: Sequence[Mapping[str, Any]] = (),
    *,
    encoding: str = 'utf-8',
) -> list[dict[str, Any]]:
    """Tag objects whose descriptions come from ``<directory>/<tag name>.md``.

    ``tags`` are explicit tag objects: they keep their order and fields, and
    a tag without a ``description`` gets the one from its file. Files for
    other tags are appended, sorted by name. Hidden files and files with
    other extensions are ignored; a missing directory is an error.
    """
    root = Path(directory)
    texts = {
        path.stem: path.read_text(encoding=encoding).strip()
        for path in sorted(root.iterdir())
        if path.is_file() and path.suffix == '.md' and not path.name.startswith('.')
    }
    result: list[dict[str, Any]] = []
    for tag in tags:
        item = copy.deepcopy(dict(tag))
        text = texts.pop(str(item.get('name')), None)
        if text and not item.get('description'):
            item['description'] = text
        result.append(item)
    result.extend({'name': name, 'description': text} for name, text in texts.items())
    return result
