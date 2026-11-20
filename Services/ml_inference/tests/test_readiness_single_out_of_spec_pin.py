"""Пин Task 2.9b: у узла ``ml_inference`` ровно одна причина ``out_of_spec`` в исходнике.

Ключ ``readiness: {severity: {out_of_spec: check_function}}`` боевого рецепта
``hikvision_letter_robot`` переназначает ВСЕ причины ``out_of_spec`` узла (ADR-PM-061). Пока причина
одна («модель не загружена»), это верно; вторая причина ``out_of_spec`` молча заблокировала бы START.

Поведение «модель не загружена -> эта причина» здесь не проверяется: его держит
``test_readiness_not_loaded.py``. Проверка по тексту исходника: степень, собранная не строковой
константой (импорт, ``READINESS_SEVERITIES[2]``), её обходит.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parents[1]
_SEVERITY = "out_of_spec"


def test_plugin_has_exactly_one_out_of_spec_constant() -> None:
    hits: list[str] = []
    for path in sorted(_PACKAGE_DIR.rglob("*.py")):
        if "tests" in path.relative_to(_PACKAGE_DIR).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == _SEVERITY:
                hits.append(f"{path.relative_to(_PACKAGE_DIR)}:{node.lineno}")

    assert len(hits) == 1, (
        "ключ readiness боевого рецепта hikvision_letter_robot переназначает ВСЕ out_of_spec узла "
        "ml_inference (ADR-PM-061): вторая причина out_of_spec требует code у причины, не ключ severity. "
        f"Найдено констант '{_SEVERITY}' вне tests/: {len(hits)} {hits}"
    )
