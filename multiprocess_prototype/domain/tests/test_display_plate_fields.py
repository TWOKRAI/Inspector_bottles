# -*- coding: utf-8 -*-
"""Поля плашки ``plate_*`` в схеме дисплея (W2-c2c, П6): приём, отказ, ``minimize``."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from multiprocess_prototype.adapters.recipe_canonical import minimize
from multiprocess_prototype.domain.entities.display import DisplayDefinition


def _plate(defn: DisplayDefinition) -> tuple[Any, ...]:
    return (defn.plate_mode, defn.plate_after_s, defn.plate_text, defn.plate_source)


def test_accepts_plate_fields() -> None:
    defn = DisplayDefinition.from_dict(
        {
            "id": "d",
            "plate_mode": "silence",
            "plate_after_s": 5,
            "plate_text": "{title}",
            "plate_source": "cam_0.camera_device",
        }
    )

    assert _plate(defn) == ("silence", 5, "{title}", "cam_0.camera_device")
    assert _plate(DisplayDefinition.from_dict({"id": "d"})) == ("hold", 2, "", "")


def test_rejects_bad_mode_and_range() -> None:
    cases: list[tuple[str, Any]] = [
        ("plate_mode", "blink"),
        ("plate_after_s", 0),
        ("plate_after_s", 601),
        ("plate_after_s", True),
        ("plate_after_s", "5"),
        ("plate_after_s", 5.0),
    ]
    for field, value in cases:
        with pytest.raises(ValidationError) as caught:
            DisplayDefinition.from_dict({"id": "d", field: value})
        msg = caught.value.errors()[0]["msg"]
        assert field in msg, (field, value, msg)
        if field == "plate_mode":
            assert "blink" not in msg


def test_minimize_drops_defaults() -> None:
    defaults = {"id": "d", "plate_mode": "hold", "plate_after_s": 2, "plate_text": "", "plate_source": ""}
    changed = {**defaults, "plate_mode": "silence", "plate_after_s": 5}

    assert minimize(("displays", 0), defaults) == {"id": "d"}
    assert minimize(("displays", 0), changed) == {"id": "d", "plate_mode": "silence", "plate_after_s": 5}
