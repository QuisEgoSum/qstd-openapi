"""Build a gateway document from two service-owned YAML files."""

from __future__ import annotations

import argparse

from pathlib import Path
from typing import Optional

from qstd_openapi import Document, OpenAPI, dumps_yaml
from qstd_openapi.dialects import OpenAPI30

HERE = Path(__file__).parent


def build_gateway(*, openapi_30: bool = False) -> OpenAPI:
    spec = OpenAPI(
        info={'title': 'User Gateway', 'version': '1.0.0'},
        dialect=OpenAPI30() if openapi_30 else None,
    )
    spec.include(
        Document.from_file(
            HERE / 'registration.openapi.yaml',
            path_prefix='/registration',
            component_namespace='registration',
        ),
        Document.from_file(
            HERE / 'profiles.openapi.yaml',
            path_prefix='/profiles',
            component_namespace='profiles',
        ),
        check=True,
    )
    return spec


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--openapi-30', action='store_true')
    args = parser.parse_args(argv)
    document = build_gateway(openapi_30=args.openapi_30).build().document
    print(dumps_yaml(document))  # noqa: T201
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
