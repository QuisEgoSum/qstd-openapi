"""Snapshots of the document and ``python -m qstd_openapi dump``."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

from pathlib import Path

import pytest

from qstd_openapi import OpenAPI, Routes, openapi
from qstd_openapi.__main__ import main
from qstd_openapi.testing import UPDATE_ENV, assert_matches_snapshot, render

MODULE = '''
from qstd_openapi import OpenAPI, Routes, openapi


@openapi.response(int)
async def count_users():
    pass


spec = OpenAPI(info={'title': 'Users API', 'version': '1.0.0'}, schemas=())
spec.include(Routes(('/users/count', 'get', count_users)))


def make_spec():
    return spec


broken = OpenAPI(info={'title': 'Users API', 'version': '1.0.0'}, schemas=())
broken.include(Routes(('/a', 'get', count_users), ('/a', 'get', make_spec)))
'''


def make_spec(summary: str = 'Count users') -> OpenAPI:
    @openapi.summary(summary)
    @openapi.response(int)
    async def count_users() -> None:
        pass

    spec = OpenAPI(info={'title': 'Users API', 'version': '1.0.0'}, schemas=())
    spec.include(Routes(('/users/count', 'get', count_users)))
    return spec


@pytest.fixture
def module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    name = f'users_api_{tmp_path.name}'.replace('-', '_')
    (tmp_path / f'{name}.py').write_text(textwrap.dedent(MODULE), 'utf-8')
    monkeypatch.setattr(sys, 'path', [str(tmp_path), *sys.path])
    monkeypatch.chdir(tmp_path)
    return name


def test_snapshot_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = tmp_path / 'openapi' / 'users_api.json'
    with pytest.raises(AssertionError, match=f'does not exist.*{UPDATE_ENV}'):
        assert_matches_snapshot(make_spec(), snapshot)

    monkeypatch.setenv(UPDATE_ENV, '1')
    assert_matches_snapshot(make_spec(), snapshot)
    monkeypatch.delenv(UPDATE_ENV)
    assert json.loads(snapshot.read_text('utf-8'))['info']['title'] == 'Users API'
    assert_matches_snapshot(make_spec(), snapshot)

    with pytest.raises(
        AssertionError,
        match=r'(?s)differs.*-.*"Count users".*\+.*"How many"',
    ):
        assert_matches_snapshot(make_spec('How many'), snapshot)


def test_render_is_stable_and_readable() -> None:
    text = render(make_spec())
    assert text == render(make_spec())
    assert text.endswith('}\n')
    assert '\n  "info": {' in text


def test_cli_dump_to_stdout_and_file(
    module: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(['dump', f'{module}:spec']) == 0
    document = json.loads(capsys.readouterr().out)
    assert document['openapi'] == '3.1.0'

    assert (
        main(['dump', f'{module}:make_spec', '--dialect', '3.0', '-o', 'out.json']) == 0
    )
    assert json.loads((tmp_path / 'out.json').read_text('utf-8'))['openapi'] == '3.0.3'


def test_cli_check(
    module: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(['dump', f'{module}:spec', '-o', 'openapi.json']) == 0
    assert main(['dump', f'{module}:spec', '-o', 'openapi.json', '--check']) == 0
    (tmp_path / 'openapi.json').write_text('{}\n', 'utf-8')
    assert main(['dump', f'{module}:spec', '-o', 'openapi.json', '--check']) == 1
    assert 'out of date' in capsys.readouterr().err


def test_cli_errors(module: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(['dump', f'{module}:broken']) == 2
    assert 'served by both' in capsys.readouterr().err
    assert main(['dump', f'{module}:missing']) == 2
    assert main(['dump', module]) == 2
    assert main(['dump', f'{module}:spec', '--check']) == 2


def test_python_dash_m(module: str, tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, '-m', 'qstd_openapi', 'dump', f'{module}:spec'],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
        env={'PYTHONPATH': ':'.join(sys.path)},
    )
    assert json.loads(result.stdout)['paths']
