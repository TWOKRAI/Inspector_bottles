# -*- coding: utf-8 -*-
"""Негодное ``plate_*`` одного экрана не отменяет загрузку рецепта (H2).

Поле берёт своё умолчание, на каждое поле одна строка WARNING без значения из файла.
Ошибка вне ``plate_*`` отклоняет рецепт, как раньше. ``DisplayDefinition`` остаётся строгим.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import pytest
from pydantic import ValidationError

from multiprocess_prototype.domain.entities.display import DisplayDefinition
from multiprocess_prototype.domain.entities.recipe import Recipe


def _recipe(*displays: Any) -> dict[str, Any]:
    return {"name": "r", "version": 3, "displays": list(displays)}


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Строки WARNING только от загрузки рецепта."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name.endswith("domain.entities.recipe")
    ]


def _load(caplog: pytest.LogCaptureFixture, *displays: Any) -> Recipe:
    # DEBUG: проверки «значения из файла в логе нет» должны видеть все уровни.
    with caplog.at_level(logging.DEBUG):
        return Recipe.from_dict(_recipe(*displays))


def test_bad_plate_mode_recipe_loads_with_default(caplog: pytest.LogCaptureFixture) -> None:
    recipe = _load(caplog, {"id": "a", "plate_mode": "holdd", "plate_text": "нет кадра"})

    assert recipe.displays[0].plate_mode == "hold"
    assert recipe.displays[0].plate_text == "нет кадра"
    assert _warnings(caplog) == ["дисплей 'a': негодный plate_mode, взят hold"]


def test_negative_plate_after_s_recipe_loads_with_default(caplog: pytest.LogCaptureFixture) -> None:
    recipe = _load(caplog, {"id": "a", "plate_mode": "silence", "plate_after_s": -7})

    assert recipe.displays[0].plate_after_s == 2
    assert recipe.displays[0].plate_mode == "silence"
    assert _warnings(caplog) == ["дисплей 'a': негодный plate_after_s, взят 2"]


def test_one_warning_per_bad_field(caplog: pytest.LogCaptureFixture) -> None:
    """Два плохих поля одного экрана — две строки, значения из файла в них нет."""
    recipe = _load(caplog, {"id": "a", "plate_mode": "holdd", "plate_after_s": 9999})

    assert (recipe.displays[0].plate_mode, recipe.displays[0].plate_after_s) == ("hold", 2)
    assert sorted(_warnings(caplog)) == [
        "дисплей 'a': негодный plate_after_s, взят 2",
        "дисплей 'a': негодный plate_mode, взят hold",
    ]
    assert "holdd" not in caplog.text
    assert "9999" not in caplog.text


def test_unknown_plate_key_is_dropped(caplog: pytest.LogCaptureFixture) -> None:
    recipe = _load(caplog, {"id": "a", "plate_mod": "sekret"})

    assert recipe.displays[0].plate_mode == "hold"
    assert _warnings(caplog) == ["дисплей 'a': неизвестный plate_mod убран"]
    assert "sekret" not in caplog.text


def test_wrong_type_in_string_plate_field(caplog: pytest.LogCaptureFixture) -> None:
    """Умолчание строкового поля пустое — после «взят » ничего нет (как в строке GUI)."""
    recipe = _load(caplog, {"id": "a", "plate_source": 41417})

    assert recipe.displays[0].plate_source == ""
    assert _warnings(caplog) == ["дисплей 'a': негодный plate_source, взят "]
    assert "41417" not in caplog.text


def test_other_display_keeps_its_plate(caplog: pytest.LogCaptureFixture) -> None:
    recipe = _load(
        caplog,
        {"id": "a", "plate_mode": "holdd"},
        {"id": "b", "plate_mode": "trigger", "plate_after_s": 30, "plate_text": "t", "plate_source": "p.q"},
    )

    a, b = recipe.displays
    assert a.plate_mode == "hold"
    assert (b.plate_mode, b.plate_after_s, b.plate_text, b.plate_source) == ("trigger", 30, "t", "p.q")
    assert _warnings(caplog) == ["дисплей 'a': негодный plate_mode, взят hold"]


def test_input_dict_is_not_mutated(caplog: pytest.LogCaptureFixture) -> None:
    data = _recipe({"id": "a", "plate_mode": "holdd", "plate_mod": 1})
    before = copy.deepcopy(data)

    with caplog.at_level(logging.WARNING):
        Recipe.from_dict(data)

    assert data == before


def test_non_plate_error_still_rejects_recipe(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ValidationError):
        _load(caplog, {"id": "a", "foo": 1})


def test_plate_and_non_plate_error_together_rejects_without_warning(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _load(caplog, {"id": "a", "plate_mode": "holdd", "scale": 1})

    assert "plate_mode" in str(exc_info.value)
    assert "scale" in str(exc_info.value)
    assert _warnings(caplog) == []


@pytest.mark.parametrize("item", ["a", 5, None, ["plate_mode"]])
def test_non_dict_item_still_rejects_recipe(item: Any, caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ValidationError):
        _load(caplog, item)
    assert _warnings(caplog) == []


@pytest.mark.parametrize("loc", [(), ("scale",)])
def test_error_without_plate_loc_rejects_recipe(
    loc: tuple[str, ...], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Ошибка проверки всей модели даёт пустой ``loc`` — это не ошибка по ``plate_*``.

    У ``DisplayDefinition`` проверки модели сейчас нет, поэтому ошибка подставлена.
    """

    def _raise(cls: type, data: dict[str, Any]) -> None:
        raise ValidationError.from_exception_data(
            "DisplayDefinition",
            [{"type": "value_error", "loc": loc, "input": data, "ctx": {"error": ValueError("модель")}}],
        )

    monkeypatch.setattr(DisplayDefinition, "from_dict", classmethod(_raise))

    with pytest.raises(ValidationError, match="модель"):
        _load(caplog, {"id": "a", "plate_mode": "hold"})
    assert _warnings(caplog) == []


@pytest.mark.parametrize("key", ["my_plate_x", "platex"])
def test_key_without_plate_prefix_rejects_recipe(key: str, caplog: pytest.LogCaptureFixture) -> None:
    """Префикс — ровно ``plate_`` в начале ключа."""
    with pytest.raises(ValidationError):
        _load(caplog, {"id": "a", key: 1})
    assert _warnings(caplog) == []


def test_newline_in_unknown_key_stays_on_one_line(caplog: pytest.LogCaptureFixture) -> None:
    _load(caplog, {"id": "a", "plate_x\n2026-01-01 ERROR forged": 1})

    assert _warnings(caplog) == ["дисплей 'a': неизвестный 'plate_x\\n2026-01-01 ERROR forged' убран"]


def test_control_chars_in_id_are_escaped_in_both_lines(caplog: pytest.LogCaptureFixture) -> None:
    recipe = _load(caplog, {"id": "a\n\x1b[2K\rforged", "plate_mode": "holdd", "plate_mod": 1})

    assert recipe.displays[0].id == "a\n\x1b[2K\rforged"
    assert sorted(_warnings(caplog)) == [
        "дисплей ''a\\n\\x1b[2K\\rforged'': негодный plate_mode, взят hold",
        "дисплей ''a\\n\\x1b[2K\\rforged'': неизвестный plate_mod убран",
    ]


def test_display_definition_stays_strict() -> None:
    with pytest.raises(ValidationError):
        DisplayDefinition.from_dict({"id": "a", "plate_mode": "holdd"})
