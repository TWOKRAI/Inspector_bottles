"""Тесты разбора вызовов atlas в analyze_pilot.py (скрипт лежит в plans/, подключается по пути). Ожидания — литералы."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3] / "plans/2026-11-06_atlas-passport/reports/pilot-2026-11-11/analyze_pilot.py"
)
pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="analyze_pilot.py не в этой копии репозитория")


@pytest.fixture(scope="module")
def pilot():
    spec = importlib.util.spec_from_file_location("analyze_pilot_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SHELL = [
    "python /x/pilot_atlas.py ref Foo | head -20",
    "python /x/pilot_atlas.py ref Foo 2>/dev/null",
    "python /x/pilot_atlas.py ref Foo 2>&1",
    "python /x/pilot_atlas.py ref Foo > out.txt",
    "python /x/pilot_atlas.py ref Foo < in.txt",
    "python /x/pilot_atlas.py ref Foo && echo done",
    "python /x/pilot_atlas.py ref Foo; echo done",
    "python /x/pilot_atlas.py ref Foo &",
    "(python /x/pilot_atlas.py ref Foo)",
    "python /x/pilot_atlas.py ref $(echo Foo)",
    "python /x/pilot_atlas.py ref $HOME",
    "python /x/pilot_atlas.py ref `echo Foo`",
    "python /x/pilot_atlas.py ref Foo*",
    "python /x/pilot_atlas.py ref Foo?",
    "python /x/pilot_atlas.py ref [A-Z]oo",
    "python /x/pilot_atlas.py map ~/repo",
    "python /x/pilot_atlas.py ref Foo\npython /x/pilot_atlas.py ref Bar",
    "python /x/pilot_atlas.py ref Foo # заметка",
    "FOO=1 python /x/pilot_atlas.py ref Foo",
    'python /x/pilot_atlas.py ref "Foo',
]
PLAIN = [
    "python /x/pilot_atlas.py ref ProcessConfig TopologySession",
    "python /x/pilot_atlas.py map multiprocess_framework/modules/app_module",
    'python /x/pilot_atlas.py ref "Cls.method"',
    "python /x/pilot_atlas.py ref a-b_c.d",
    "python /x/pilot_atlas.py ref 'Foo Bar'",
    "python /x/pilot_atlas.py ref a=b",
    "python /x/pilot_atlas.py ref 'a|b'",
]


@pytest.mark.parametrize("command", SHELL)
def test_shell_syntax_detected(pilot, command):
    assert pilot._has_shell_syntax(command) is True


@pytest.mark.parametrize("command", PLAIN)
def test_plain_commands_not_flagged(pilot, command):
    assert pilot._has_shell_syntax(command) is False


def _fake_atlas(tmp_path):
    script = tmp_path / "pilot_atlas.py"
    script.write_text(
        "import sys\n"
        "if sys.argv[2] == 'ok':\n    print('pkg/mod.py:55 Foo')\n"
        "elif sys.argv[2] == 'partial':\n    print('pkg/part.py:7 Bar')\n    sys.exit(2)\n"
        "else:\n    sys.stderr.write('not found')\n    sys.exit(2)\n",
        encoding="utf-8",
    )
    return script


def _call(script, arg, denied=False, **extra):
    return {"name": "Bash", "target": f"{sys.executable} {script} ref {arg}", "denied": denied, **extra}


def test_atlas_texts_classification(pilot, tmp_path):
    script = _fake_atlas(tmp_path)
    repeat = {
        "tool_uses": [
            _call(script, "ok"),  # обычный вызов: воспроизведён
            _call(script, "ok", denied=True),  # denied без текста: неизвестный
            _call(script, "ok", denied=True, output="recorded text"),  # denied, но текст в записи: берём его
            {"name": "Bash", "target": f"{sys.executable} {script} ref ok | head -3", "denied": False},  # оболочка
            _call(script, "missing"),  # повтор: код 2 и пустой stdout
            _call(script, "partial"),  # повтор: код 2, но вывод есть - это текст
            {"name": "Bash", "target": "ls -la", "denied": False},  # не atlas: пропущен
            {"name": "Read", "target": str(script)},  # не Bash: пропущен
        ]
    }
    texts, unknown = pilot._atlas_texts(repeat)
    assert [t.strip() for t in texts] == ["pkg/mod.py:55 Foo", "recorded text", "pkg/part.py:7 Bar"]
    assert len(unknown) == 3
    assert unknown[0][1].startswith("denied")
    assert unknown[1][1].startswith("синтаксис оболочки") and "ref ok | head -3" in unknown[1][0]
    assert unknown[2][1] == "повтор дал код 2 и пустой вывод"
