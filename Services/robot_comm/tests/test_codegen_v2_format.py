"""Вывод кодогена устойчив к `ruff format` (pre-commit не переписывает сгенерированные модули).

До правки codegen выдавал строки в одинарных кавычках, а ruff-format в pre-commit переводил
их в двойные: файлы на диске расходились с `generate()`, хотя смысл тот же. Тест держит
договорённость «codegen выдаёт ровно то, что оставит форматтер».
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Services/robot_comm/tests/test_codegen_v2_format.py -> tests(0) / robot_comm(1) / Services(2) / root(3)
_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_generated_modules_are_ruff_format_stable():
    from Services.robot_comm import codegen

    outputs = codegen.generate(_REPO_ROOT)
    assert outputs  # пустой generate() не должен давать зелёный тест без проверки
    for path, text in outputs.items():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        proc = subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--check", "--stdin-filename", rel, "-"],
            input=text.encode("utf-8"),
            cwd=_REPO_ROOT,
            capture_output=True,
            timeout=60,
        )
        assert proc.returncode == 0, f"ruff format переписал бы {rel}: {proc.stdout!r} {proc.stderr!r}"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("CMD_FLAG", '"CMD_FLAG"'),
        ("dw_hi", '"dw_hi"'),
        ("it's", '"it\'s"'),
        ('say "hi"', "'say \"hi\"'"),
        ("", '""'),
        ("путь\\к", '"путь\\\\к"'),
        # обе кавычки: одинарные только при перевесе `"` (замер ревью р.1 на ruff 0.15.14)
        ("a'b\"c", '"a\'b\\"c"'),
        ('it\'s "x"', "'it\\'s \"x\"'"),
        ("'\"", '"\'\\""'),
    ],
)
def test_py_string_quotes_like_ruff(value, expected):
    from Services.robot_comm import codegen

    assert codegen._render_scalar(value) == expected
