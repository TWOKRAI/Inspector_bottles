"""Тесты commit-msg валидатора — фокус на фолдинге перенесённых трейлеров.

Регресс: перенос значения `Why:`/`Layer:` на вторую строку раньше ронял весь
трейлер-абзац в body → ложное «Missing required trailers». Git-стиль детекции
(абзац = трейлер-блок, если начинается с трейлера; не-матчащие строки фолдятся)
терпит перенос. См. validate_commit.parse_message.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validate_commit import parse_message, validate  # noqa: E402

_BASE = "docs(memory): пример темы\n\n- буллет\n"


def _msg(trailer_block: str) -> str:
    return f"{_BASE}\n{trailer_block}"


def test_wrapped_why_value_still_parses() -> None:
    """Главный регресс: `Why:` перенесён на 2 строки — трейлеры всё равно найдены."""
    text = _msg("Why: длинная мотивация которая случайно\nперенеслась на вторую строку\nLayer: tests")
    _, _, trailers = parse_message(text)
    assert "Why" in trailers and "Layer" in trailers
    # continuation-строка сфолжена в значение Why (не потеряна, не отдельный трейлер).
    assert trailers["Why"][0] == "длинная мотивация которая случайно перенеслась на вторую строку"
    assert validate(text).ok


def test_single_line_trailers_ok() -> None:
    text = _msg("Why: коротко и по делу\nLayer: tests\nRefs: plans/x.md")
    assert validate(text).ok


def test_missing_required_still_fails() -> None:
    """Фолдинг не должен ослабить обязательность Why/Layer."""
    text = _msg("Refs: plans/x.md")
    res = validate(text)
    assert not res.ok
    assert any("Missing required trailers" in e for e in res.errors)


def test_multi_paragraph_trailers_preserved() -> None:
    """Бизнес-трейлеры + отдельный абзац Co-Authored-By — оба распознаны."""
    text = _msg("Why: мотивация\nLayer: framework\n\nCo-Authored-By: X <x@e.co>")
    _, _, trailers = parse_message(text)
    assert "Why" in trailers and "Layer" in trailers and "Co-Authored-By" in trailers


def test_body_paragraph_not_swallowed_as_trailers() -> None:
    """Абзац body, НЕ начинающийся с трейлера, не уезжает в трейлеры."""
    text = "feat(x): тема\n\nОбычный body-абзац без трейлеров.\nВторая строка body.\n\nWhy: мотивация\nLayer: tests"
    _, body, trailers = parse_message(text)
    assert "Обычный body-абзац без трейлеров." in body
    assert set(trailers) == {"Why", "Layer"}
    assert validate(text).ok


def test_wrapped_layer_value_parses() -> None:
    """Перенос значения Layer тоже терпится (значение сфолжено, валидация по первому токену)."""
    text = _msg("Why: мотивация\nLayer: tests\nдоп. пояснение к слою")
    _, _, trailers = parse_message(text)
    assert trailers["Layer"][0] == "tests доп. пояснение к слою"
    # Layer-валидация бьёт по запятым; 'tests доп...' — одно значение с пробелами → unknown.
    # Здесь важно, что Why/Layer НАЙДЕНЫ (не «missing»); значение-варн допустимо.
    assert "Why" in trailers and "Layer" in trailers
