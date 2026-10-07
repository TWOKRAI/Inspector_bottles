"""Приёмочные тесты выноса contract_gaps из scripts/s2_gate.py (Task 1.5a, RED до кода).

Purpose: contract_gaps(text) — публичные функции без Pre:/Post: (RED 14-15) и характеризация CLI
    `python scripts/s2_gate.py --interface <файл>` (C1-C4, зелёные до кода: вывод CLI не меняется).
Public API: тесты test_*; публичных имён нет.
Stability: lite

Импорт contract_gaps внутри тестов: отсутствие функции даёт красный на RED 14-15, а не ошибку сбора,
которая спрятала бы характеризационные тесты.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.atlas.tests.conftest import run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]

# Номера строк в тексте ниже пишутся литералами в ожидании; текст не двигать без пересчёта.
_GAPS_TEXT = '''def f():
    pass


def g():
    """Pre: a
    Post: b
    """


class A:
    def m(self):
        """Pre: x"""

    def n(self):
        """Pre: x
        Post: y
        """

    @property
    @abstractmethod
    def o(self):
        ...

    def _p(self):
        pass

    async def q(self):
        """Post: z"""


class _B:
    def meth(self):
        pass
'''

_COMPLETE_TEXT = '''def g():
    """Pre: a
    Post: b
    """


class A:
    def n(self):
        """Pre: x
        Post: y
        """

    async def q(self):
        """Pre: x
        Post: y
        """

    def _p(self):
        pass
'''


def test_contract_gaps_lists_public_functions_without_markers() -> None:
    from scripts.s2_gate import contract_gaps

    assert contract_gaps(_GAPS_TEXT) == [
        ("f", 1, 2, ("Pre:", "Post:")),
        ("A.m", 12, 13, ("Post:",)),
        ("A.o", 20, 23, ("Pre:", "Post:")),
        ("A.q", 28, 29, ("Pre:",)),
    ]
    assert contract_gaps(_COMPLETE_TEXT) == []


def test_contract_gaps_syntax_error_propagates() -> None:
    from scripts.s2_gate import contract_gaps

    with pytest.raises(SyntaxError):
        contract_gaps("def (:")


def _gate(path: Path) -> tuple[int, list[str]]:
    """Запуск CLI подпроцессом из корня checkout; (код выхода, строки stdout)."""

    def call() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, "scripts/s2_gate.py", "--interface", str(path)],
            cwd=_ROOT,
            capture_output=True,
            check=False,
        )

    proc = run_with_deadline(call)
    return proc.returncode, proc.stdout.decode("utf-8").splitlines()


def test_cli_pass(tmp_path: Path) -> None:
    file = tmp_path / "interface.py"
    file.write_text(_COMPLETE_TEXT, encoding="utf-8")
    code, lines = _gate(file)
    assert code == 0
    assert lines == ["VERDICT: PASS"]


def test_cli_block_lists_offenders(tmp_path: Path) -> None:
    file = tmp_path / "interface.py"
    file.write_text(
        'class A:\n    def m(self):\n        """Pre: x"""\n\n\ndef f():\n    pass\n',
        encoding="utf-8",
    )
    code, lines = _gate(file)
    assert code == 1
    assert lines == [
        "VERDICT: BLOCK",
        "Reason: public functions without complete contract: A.m (missing Post:); f (missing Pre:, Post:)",
    ]


def test_cli_missing_file(tmp_path: Path) -> None:
    code, lines = _gate(tmp_path / "absent.py")
    assert code == 1
    assert lines[0] == "VERDICT: BLOCK"
    assert lines[1].startswith("Reason: interface file not found: ")


def test_cli_syntax_error(tmp_path: Path) -> None:
    file = tmp_path / "interface.py"
    file.write_text("def (:\n", encoding="utf-8")
    code, lines = _gate(file)
    assert code == 1
    assert lines[0] == "VERDICT: BLOCK"
    assert lines[1].startswith("Reason: interface has a syntax error: ")
