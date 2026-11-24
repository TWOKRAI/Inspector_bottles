"""scripts/letters_baseline.py: метрики замера сети букв, парсер имён, прогон dir с фейк-движком, плагины рецепта.

Ожидаемые значения — литералы, посчитанные руками (не из кода под тестом). Кадры dir-теста однотонные:
цвет пикселя кодирует ответ фейка (B = номер буквы ответа, G = уверенность в %, R = угол ответа), PNG без потерь.
"""

from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path

import cv2
import numpy as np
import pytest

from scripts import letters_baseline as lb

REPO_ROOT = Path(__file__).resolve().parents[2]
LETTERS = ["А", "Б", "В"]


# --------------------------------------------------------------------------- #
# Чистые функции                                                               #
# --------------------------------------------------------------------------- #


def test_wrap_deg():
    assert lb.wrap_deg(190.0) == -170.0
    assert lb.wrap_deg(-190.0) == 170.0
    assert lb.wrap_deg(180.0) == -180.0  # полуинтервал [-180, 180)
    assert lb.wrap_deg(359.0) == -1.0
    assert lb.wrap_deg(100.0, 180.0) == -80.0
    assert lb.wrap_deg(90.0, 180.0) == -90.0


def test_angle_error_cases():
    # переход через 0: сеть 359, истина 1 -> -2, а не +358
    assert lb.angle_error(359.0, 1.0, "none") == -2.0
    # симметрия 180: сеть 179, истина 1 -> -2 по модулю 180; без симметрии wrap360 -> +178
    assert lb.angle_error(179.0, 1.0, "180") == -2.0
    assert lb.angle_error(179.0, 1.0, "180", use_symmetry=False) == 178.0
    # full: угол не определён
    assert lb.angle_error(10.0, 10.0, "full") is None
    assert lb.angle_error(10.0, 10.0, "full", use_symmetry=False) == 0.0
    # инвертированная истина: 100 - (-30) = 130
    assert lb.angle_error(100.0, 30.0, "none", invert_truth=True) == 130.0
    assert lb.angle_error(100.0, 30.0, "none") == 70.0


def test_is_below():
    assert lb.is_below(0.5, 0.5) is False  # граница == порога — не ниже (как в плагине)
    assert lb.is_below(0.4999, 0.5) is True
    assert lb.is_below(0.9, 0.5) is False
    assert lb.is_below(float("nan"), 0.5) is True  # NaN — ниже


def test_angle_stats():
    s = lb.angle_stats([1.0, -2.0, 6.0, 12.0, -20.0])
    assert s["n"] == 5
    assert s["median"] == 1.0
    assert s["p90_abs"] == pytest.approx(16.8)  # |Δ| = 1,2,6,12,20; индекс 3.6 -> 12 + 0.6*8
    assert s["max_abs"] == 20.0
    assert (s["out_5"], s["out_10"], s["out_15"]) == (pytest.approx(0.6), pytest.approx(0.4), pytest.approx(0.2))
    empty = lb.angle_stats([])
    assert empty["n"] == 0 and empty["median"] is None and empty["out_5"] is None


def _fr(letter, truth, pred, conf=0.0, angle=None, valid=True, sym="none", grid=None):
    return lb.FrameResult(letter, truth, truth if grid is None else grid, pred, conf, angle, valid, sym)


def test_compute_metrics():
    results = [
        _fr("П", 0.0, "П", 0.9, angle=358.0),  # верно, Δ = -2
        _fr("П", 0.0, "П", 0.5, angle=4.0),  # верно, conf == порога -> ответил, Δ = +4
        _fr("П", 90.0, "И", 0.3),  # неверно, ниже порога
        _fr("И", 0.0, "И", 0.45, angle=179.0, sym="180"),  # верно, ниже порога; Δsym = -1, Δбез_сим = +179
        _fr("М", 45.0, None),  # диск не найден
        _fr("О", 10.0, "О", 0.8, angle=0.0, valid=False, sym="full"),  # верно, угол не определён
    ]
    m = lb.compute_metrics(results, 0.5)
    assert (m["total"], m["no_disc"]) == (6, 1)
    assert m["top1_correct"] == 4
    assert m["top1_correct_pct"] == pytest.approx(100 * 4 / 6)
    assert m["below_threshold"] == 2
    assert m["below_threshold_pct"] == pytest.approx(100 * 2 / 6)
    assert (m["answered"], m["correct_answered"]) == (3, 3)
    assert m["correct_answered_pct_of_all"] == 50.0
    assert m["correct_among_answered_pct"] == 100.0
    by = m["recall_by_letter"]
    assert (by["П"]["n"], by["П"]["top1"], by["П"]["correct_answered"]) == (3, 2, 2)
    assert (by["И"]["top1"], by["И"]["correct_answered"]) == (1, 0)
    assert by["М"]["top1"] == 0 and by["М"]["recall_top1_pct"] == 0.0
    assert m["confusion_top5"] == [{"truth": "П", "pred": "И", "count": 1}]
    a = m["angle"]
    assert (a["frames_correct_letter"], a["frames_angle_undefined_full"]) == (4, 1)
    assert a["sym"]["n"] == 3 and a["sym"]["median"] == -1.0 and a["sym"]["max_abs"] == 4.0  # Δ = -2, +4, -1
    assert a["sym_answered_only"]["n"] == 2 and a["sym_answered_only"]["max_abs"] == 4.0
    assert a["no_sym"]["max_abs"] == 179.0  # И без учёта симметрии
    assert a["median_by_grid_angle_sym"] == {"0": {"n": 3, "median": -1.0}}


# --------------------------------------------------------------------------- #
# Источник dir                                                                 #
# --------------------------------------------------------------------------- #


def test_parse_frame_path(tmp_path):
    root = tmp_path
    assert lb.parse_frame_path(root, root / "Ж" / "a045_000001.png") == ("Ж", 45)
    nfd = unicodedata.normalize("NFD", "Й")
    assert nfd != "Й"
    assert lb.parse_frame_path(root, root / nfd / "a270_7.jpg") == ("Й", 270)  # имя буквы приводится к NFC
    assert lb.parse_frame_path(root, root / "Ж" / "img_001.png") is None  # имя не по схеме
    assert lb.parse_frame_path(root, root / "a045_000001.png") is None  # нет подкаталога буквы
    assert lb.parse_frame_path(root, root / "Ж" / "a045_000001.txt") is None  # не картинка


def _write_png(path: Path, bgr: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", np.full((16, 16, 3), bgr, dtype=np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())


class FakeEngine:
    """Ответ по цвету кадра: B = индекс буквы ответа в LETTERS, G = уверенность %, R = угол ответа."""

    def predict(self, frame, *, top_k=5, threshold=0.0):
        b, g, r = (int(v) for v in frame[0, 0])
        top = {"class_id": b, "label": LETTERS[b], "confidence": g / 100.0, "angle_deg": float(r), "angle_valid": True}
        top["angle_symmetry"] = "180" if LETTERS[b] == "Б" else "none"
        return [top]


def _make_dir(root: Path) -> None:
    """3 буквы x 3 угла. А: верно, 0.90, угол точный. Б: верно, 0.40 (ниже порога), симметрия 180,
    угол истина+2 mod 180.
    В: ответ «А», уверенность ровно 0.50 (на границе порога -> ответил)."""
    for letter, idx in zip(LETTERS, range(3)):
        for angle in (0, 90, 180):
            if letter == "А":
                color = (0, 90, angle)
            elif letter == "Б":
                color = (1, 40, (angle + 2) % 180)
            else:
                color = (0, 50, angle)
            _write_png(root / letter / f"a{angle:03d}_{idx + 1:06d}.png", color)


def test_dir_main_with_fake_engine(tmp_path, monkeypatch, capsys):
    root = tmp_path / "набор"
    _make_dir(root)
    out = tmp_path / "m.json"
    monkeypatch.setattr(lb, "load_engine", lambda *a, **k: FakeEngine())
    rc = lb.main(["dir", str(root), "--crop", "none", "--models-dir", str(tmp_path), "--json-out", str(out)])
    stdout = capsys.readouterr().out
    assert rc == 0
    assert "пороги PASS/FAIL не заданы" in stdout
    m = json.loads(out.read_text(encoding="utf-8"))
    assert m["total"] == 9
    assert m["top1_correct"] == 6 and m["top1_correct_pct"] == pytest.approx(100 * 6 / 9)
    assert m["below_threshold"] == 3  # только Б (0.40); В на границе 0.50 — не ниже
    assert m["answered"] == 6 and m["correct_answered"] == 3
    assert m["correct_among_answered_pct"] == 50.0
    assert m["recall_by_letter"]["В"]["top1"] == 0 and m["recall_by_letter"]["А"]["top1"] == 3
    assert m["confusion_top5"] == [{"truth": "В", "pred": "А", "count": 3}]
    a = m["angle"]
    assert a["sym"]["n"] == 6 and a["sym"]["median"] == 1.0 and a["sym"]["max_abs"] == 2.0  # А: 0, Б: +2 (mod 180)
    assert a["no_sym"]["max_abs"] == 178.0  # Б при истине 180: 2 - 180 = -178 без учёта симметрии
    assert a["median_by_grid_angle_sym"]["180"] == {"n": 2, "median": 1.0}


def test_main_call_errors(tmp_path, monkeypatch, capsys):
    # нет модели в каталоге -> 2
    assert lb.main(["dir", str(tmp_path), "--models-dir", str(tmp_path / "нет")]) == 2
    assert "не загружена" in capsys.readouterr().err
    # пустой набор -> 2
    monkeypatch.setattr(lb, "load_engine", lambda *a, **k: FakeEngine())
    empty = tmp_path / "пусто"
    empty.mkdir()
    assert lb.main(["dir", str(empty)]) == 2
    assert "нет кадров" in capsys.readouterr().err
    # нет каталога -> 2
    assert lb.main(["dir", str(tmp_path / "нет-такого")]) == 2


def test_help_shows_both_modes_and_all_flags():
    text = lb.build_parser().format_help()
    for token in (
        "режим sim",
        "режим dir",
        "--letters",
        "--all",
        "--angles",
        "--per-cell",
        "--seed",
        "--data-root",
        "--models-dir",
        "--crop",
        "--recipe",
        "--json-out",
        "--threshold",
        "--preset",
    ):
        assert token in text, token


# --------------------------------------------------------------------------- #
# Плагины рецепта (--crop pipeline), настоящий engine                          #
# --------------------------------------------------------------------------- #

RECIPE = REPO_ROOT / lb.DEFAULT_RECIPE


def _camera_frame(with_disc: bool) -> np.ndarray:
    """Кадр 1440x1080: чёрный; диск r=150 белый с серой буквой-пятном, центр (646, 537) = центр ROI рецепта."""
    frame = np.zeros((1080, 1440, 3), dtype=np.uint8)
    if with_disc:
        cv2.circle(frame, (646, 537), 150, (255, 255, 255), -1)
        cv2.rectangle(frame, (606, 497), (686, 577), (60, 60, 60), -1)
    return frame


def test_pipeline_crop_runs_recipe_plugins(tmp_path, monkeypatch, capsys):
    pipe = lb.RecipePipeline(RECIPE)
    crop = pipe.crop(_camera_frame(True))
    assert crop is not None and crop.shape == (128, 128, 3)
    assert crop[64, 16].min() > 200  # слева от центра, внутри диска (диск занимает ~91 % выреза) — белое
    assert crop[0, 0].max() < 50  # угол выреза вне диска — чёрный фон
    assert pipe.crop(_camera_frame(False)) is None  # круга нет -> None

    # через main: один кадр с диском и один без — «диск не найден» считается в total
    root = tmp_path / "кадры"
    for name, with_disc in (("a000_000001.png", True), ("a000_000002.png", False)):
        (root / "А").mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".png", _camera_frame(with_disc))
        assert ok
        (root / "А" / name).write_bytes(buf.tobytes())
    monkeypatch.setattr(lb, "load_engine", lambda *a, **k: FakeEngine())
    out = tmp_path / "p.json"
    assert lb.main(["dir", str(root), "--crop", "pipeline", "--json-out", str(out)]) == 0
    m = json.loads(out.read_text(encoding="utf-8"))
    assert (m["total"], m["no_disc"]) == (2, 1)
    capsys.readouterr()


def test_sim_with_real_engine_three_frames():
    """Настоящий движок + настоящий генератор сима на 3 кадрах. Данные вне git: путь — LETTERS_BASELINE_DATA_ROOT
    (каталог data/ дерева с моделью и данными сима), иначе data/ этого дерева; нет — skip."""
    data_root = Path(os.environ.get("LETTERS_BASELINE_DATA_ROOT", REPO_ROOT / "data"))
    models_dir = data_root / "models"
    model_file = models_dir / f"{lb.DEFAULT_MODEL}.onnx"
    if not model_file.is_file() or not (data_root / "line_sim" / "letters_ink").is_dir():
        pytest.skip(f"нет модели/каталога букв сима под {data_root}: задайте LETTERS_BASELINE_DATA_ROOT=<дерево>/data")
    letters = ["П"]
    ink_dir = data_root / "line_sim" / "letters_ink"
    missing = [letter for letter in letters if not (ink_dir / letter).is_dir()]
    if missing:
        # Каталог есть, но устарел (ассеты до R1b 5b6ca25f7: А К Р Х) — генератор сима упал бы ValueError.
        present = sorted(p.name for p in ink_dir.iterdir() if p.is_dir())
        pytest.skip(
            f"в {ink_dir} нет букв {missing} (есть: {present}): ассеты сима устарели; "
            "пересоберите: python Services/line_sim/tools/build_stand_assets.py --force"
        )
    engine = lb.load_engine(models_dir, lb.DEFAULT_MODEL, "cpu")
    preset = lb.load_sim_preset(REPO_ROOT / lb.DEFAULT_PRESET, data_root)
    frames = list(lb.iter_sim_frames(preset, letters, [0.0, 90.0, 180.0], 1, 0))
    assert [f.grid_angle for f in frames] == [0.0, 90.0, 180.0]
    assert all(f.bgr.shape == (128, 128, 3) and f.bgr.dtype == np.uint8 for f in frames)
    assert all(abs(lb.wrap_deg(f.truth_angle - f.grid_angle)) < 1e-6 for f in frames)  # истина = заданный угол
    results = lb.run_sim(engine, iter(frames))
    m = lb.compute_metrics(results, 0.5)
    assert m["total"] == 3 and m["no_disc"] == 0
    assert m["top1_correct"] >= 2  # проводка букв/цвета: перепутанный индекс или RGB/BGR дал бы ~0
    assert m["angle"]["sym"]["n"] >= 1
