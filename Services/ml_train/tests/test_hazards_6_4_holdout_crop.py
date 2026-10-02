# -*- coding: utf-8 -*-
"""Hazard-тесты автора Task 6.4: внутренние места `holdout_eval` / CLI `eval`, видимые только изнутри.

Что здесь может сломаться (дополнение к слепому набору `test_acceptance_6_4_holdout_crop.py`, не замена):
  * CLI: фильтр «передавать только заданные флаги» написан через `is not None`; написанный через truthiness он молча
    отбросит `--margin-px 0` / `--output-size 0` (допустимые значения) и подставит дефолт;
  * CLI: ошибка `--pad-color-bgr` не повторяет введённое (ввод может быть чем угодно) и называет формат;
  * лог: промах ПЕРВОГО же образца (до единого попадания `ang_errors` пуст) не должен падать IndexError;
  * цвет заливки доходит от `evaluate_holdout` до байтов кадра в движке (сквозной путь, не шпион на имя функции);
  * `summary["crop"]["pad_color_bgr"]` — список-копия: сводка JSON-совместима и не алиасит аргумент вызывающего.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from Services.ml_train import __main__ as cli
from Services.ml_train import holdout_eval

_CROP_KEYS = ("radius_scale", "margin_px", "output_size", "pad_color_bgr")


def _frame() -> np.ndarray:
    rng = np.random.default_rng(5)
    return rng.integers(1, 255, size=(480, 640, 3), dtype=np.uint8)


def _stub_engine(monkeypatch, labels, seen: list) -> None:
    seq = list(labels)
    calls = {"n": 0}

    class _Stub:
        def __init__(self, *args, **kwargs):
            self._spec = SimpleNamespace(symmetry={})

        def load_model(self, *args, **kwargs):
            return None

        def predict(self, frame, top_k=1):
            seen.append(frame.copy())
            label = seq[min(calls["n"], len(seq) - 1)]
            calls["n"] += 1
            return [{"label": label, "confidence": 0.9, "angle_deg": 0.0, "angle_valid": True}]

    monkeypatch.setattr(holdout_eval, "InferenceEngine", _Stub)


def _holdout(tmp_path: Path, names) -> Path:
    root = tmp_path / "holdout"
    (root / "A").mkdir(parents=True)
    ok, buf = cv2.imencode(".png", _frame())
    assert ok
    for name in names:
        (root / "A" / name).write_bytes(buf.tobytes())
    return root


def _log_recorder(monkeypatch) -> list[str]:
    records: list[str] = []

    class _Rec:
        def _put(self, msg, *args, **kwargs):
            records.append(msg % args if args else msg)

        info = warning = error = debug = _put

    monkeypatch.setattr(holdout_eval, "logger", _Rec())
    return records


def _spy_eval(monkeypatch) -> dict:
    """Шпион на `evaluate_holdout`, возвращающий то, что читает `_cmd_eval` (accuracy, angle_mae_deg)."""
    got: dict = {}

    def _spy(*args, **kwargs):
        got["args"], got["kwargs"] = args, kwargs
        return {"accuracy": 0.0, "angle_mae_deg": None}

    monkeypatch.setattr(holdout_eval, "evaluate_holdout", _spy)
    return got


# --- CLI ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (["--margin-px", "0"], {"margin_px": 0}),
        (["--output-size", "0"], {"output_size": 0}),
        (["--radius-scale", "0"], {"radius_scale": 0.0}),
        (["--pad-color-bgr", "0,0,0"], {"pad_color_bgr": (0, 0, 0)}),
        (["--margin-px", "3", "--output-size", "64"], {"margin_px": 3, "output_size": 64}),
    ],
)
def test_cli_forwards_falsy_values_and_only_the_given_flags(monkeypatch, tmp_path, flags, expected):
    """Нулевые значения доходят до `evaluate_holdout`; незаданные из четырёх ключей в kwargs не появляются."""
    got = _spy_eval(monkeypatch)
    assert cli.main(["eval", "m", str(tmp_path), *flags]) == 0
    forwarded = {k: v for k, v in got["kwargs"].items() if k in _CROP_KEYS}
    assert forwarded == expected
    assert type(forwarded.get("pad_color_bgr", ())) is tuple


@pytest.mark.parametrize("bad", ["7,8", "7,8,300", "7,8,-1", "a,b,c", "7.5,8,9", "7,8,9,10", ""])
def test_cli_bad_pad_color_names_the_format_and_does_not_echo_the_input(monkeypatch, tmp_path, capsys, bad):
    got = _spy_eval(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["eval", "m", str(tmp_path), f"--pad-color-bgr={bad}"])
    assert exc.value.code == 2
    assert "kwargs" not in got, "evaluate_holdout не должен вызываться при ошибке разбора"
    err = capsys.readouterr().err
    assert "B,G,R" in err
    if bad:
        assert f"'{bad}'" not in err and f"{bad}" not in err.split("B,G,R")[-1]


# --- лог --------------------------------------------------------------------------------------------------------------


def test_first_sample_miss_does_not_raise_and_second_sample_hit_logs_its_own_error(tmp_path, monkeypatch):
    """Промах первого образца (`ang_errors` пуст) -> без IndexError; следующее попадание логирует СВОЮ err."""
    seen: list = []
    _stub_engine(monkeypatch, ["Z", "A"], seen)  # 0.png -> промах, 1.png -> попадание
    monkeypatch.setattr(holdout_eval, "detect_disk", lambda bgr: (320, 240, 150))
    records = _log_recorder(monkeypatch)
    root = _holdout(tmp_path, ("0.png", "1.png"))
    summary = holdout_eval.evaluate_holdout("m", root, models_dir=str(tmp_path / "models"))
    assert summary["samples"] == 2 and summary["accuracy"] == 0.5
    miss = next(r for r in records if "A/0.png" in r)
    hit = next(r for r in records if "A/1.png" in r)
    assert "angle=" not in miss and "err=" not in miss
    # истинный угол образца 1.png = 1°, предсказание 0° -> ошибка 1.0°, а не мусор из чужого образца
    assert "err=1.0°" in hit


# --- цвет заливки и сводка -------------------------------------------------------------------------------------------


def test_pad_colour_reaches_the_frame_given_to_the_engine_in_bgr_order(tmp_path, monkeypatch):
    """Диск у левого края, output_size=0: левые 144 столбца кадра в движке = (7, 8, 9) именно в порядке B,G,R."""
    seen: list = []
    _stub_engine(monkeypatch, ["A"], seen)
    monkeypatch.setattr(holdout_eval, "detect_disk", lambda bgr: (20, 240, 150))
    root = _holdout(tmp_path, ("0.png",))
    holdout_eval.evaluate_holdout(
        "m", root, models_dir=str(tmp_path / "models"), output_size=0, pad_color_bgr=(7, 8, 9)
    )
    frame = seen[0]
    assert frame.shape == (328, 328, 3)
    assert (frame[:, :144] == np.array([7, 8, 9], dtype=np.uint8)).all()


def test_summary_crop_pad_colour_is_a_json_list_copy(tmp_path, monkeypatch):
    seen: list = []
    _stub_engine(monkeypatch, ["A"], seen)
    monkeypatch.setattr(holdout_eval, "detect_disk", lambda bgr: (320, 240, 150))
    root = _holdout(tmp_path, ("0.png",))
    colour = [1, 2, 3]
    summary = holdout_eval.evaluate_holdout("m", root, models_dir=str(tmp_path / "models"), pad_color_bgr=colour)
    assert json.loads(json.dumps(summary))["crop"]["pad_color_bgr"] == [1, 2, 3]
    assert summary["crop"]["pad_color_bgr"] is not colour
