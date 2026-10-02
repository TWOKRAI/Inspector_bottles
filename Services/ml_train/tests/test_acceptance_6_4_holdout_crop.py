"""Task 6.4 — слепые приёмочные тесты: `holdout_eval` режет кадр по формуле конвейера.

Источник: раздел «Task 6.4» плана `plans/layer-render/phase-6-train.md` (Acceptance A1-A5, A8; A6 — существующие
тесты, A7 — живой прогон лида). Кода реализации тестер не видел; тесты написаны от критериев приёмки.

Оракул «формулы конвейера» — НЕ `holdout_eval`, а `CenterCropPlugin` с рецептовым регистром
(`size_mode: radius, radius_scale 1.0, margin_px 14, output_size 128, pad_if_oob true, drop_partial false`).
Литералы ожидаемых значений (328, (128, 128, 3), (7, 8, 9), ...) выписаны руками, не посчитаны кодом задачи.

РАСКЛАДКА ДО РЕАЛИЗАЦИИ (дерево на коммите спеки 183e2c60c). Допущение тестера, не факт спеки: ЗЕЛЁНЫЕ тесты ниже
зелёные на старом коде по причине, указанной в докстринге каждого; остальные КРАСНЫЕ.

ЗЕЛЁНЫЕ сейчас (контроли харнесса и то, что реализация не должна сломать):
  * test_control_plugin_item_with_detections_uses_the_radius_formula — оракул берёт радиус из `detections`, а не
    `side_px`;
  * test_control_stub_engine_hit_gives_accuracy_one — стаб движка и PNG-харнесс работают на старом коде;
  * test_control_hit_log_line_keeps_the_angle_suffix — строка лога попадания сохраняет хвост `angle=… err=…`;
  * test_a5_cli_without_flags_passes_none_of_the_four_keys — без флагов ключей в kwargs нет (сейчас нет и самих флагов);
  * test_a5_cli_still_forwards_models_dir_and_device — регрессия: `models_dir`/`device` по-прежнему идут в вызов;
  * test_a5_cli_bad_pad_color_exits_with_code_2 — ЗЕЛЁНЫЙ ПО НЕВЕРНОЙ ПРИЧИНЕ: argparse сегодня отвергает неизвестный
    флаг тем же кодом 2. Содержательно контракт держат парные красные тесты: `..._accepts_...` и `..._message_...`;
  * test_a8_recipe_center_crop_is_radius_mode_with_pad — рецепт уже такой; тест ловит правку рецепта в обход
    `holdout_eval`.

КРАСНЫЕ сейчас: всё остальное (`_crop_disk` без новых аргументов -> TypeError; нет ключа `crop` в сводке; нет флагов
CLI;
`margin` ещё принимается; на промахе `IndexError` в строке лога; дефолтов нет в сигнатуре).
Тип красного: для `_crop_disk`/`evaluate_holdout` — `TypeError` (смена сигнатуры, иначе ей не быть), для
сводки/лога/рецепта —
`AssertionError`/`KeyError`/`IndexError`, для флагов CLI — `SystemExit(2)` от argparse.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
import yaml

from Plugins.processing.center_crop.plugin import CenterCropPlugin
from Plugins.processing.center_crop.registers import CenterCropRegisters
from Services.ml_train import holdout_eval

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RECIPE = _REPO_ROOT / "multiprocess_prototype" / "recipes" / "letter_robot_sim.yaml"

_FOUR_KEYS = ("radius_scale", "margin_px", "output_size", "pad_color_bgr")
_DEFAULT_CROP = {"radius_scale": 1.0, "margin_px": 14, "output_size": 128, "pad_color_bgr": [0, 0, 0]}


# --------------------------------------------------------------------------- харнесс


def _frame(seed: int = 7) -> np.ndarray:
    """Кадр 640x480x3 uint8: шум из seed + диск r=150 в центре (затемнён/сдвинут, чтобы отличаться от фона)."""
    rng = np.random.default_rng(seed)
    f = rng.integers(0, 256, size=(480, 640, 3), dtype=np.uint8)
    yy, xx = np.ogrid[:480, :640]
    mask = (xx - 320) ** 2 + (yy - 240) ** 2 <= 150**2
    f[mask] = f[mask] // 2 + 100
    return f


def _crop_disk_with(monkeypatch, frame, disk, **kwargs):
    """Вызвать `holdout_eval._crop_disk`, подменив `detect_disk` фиксированным (cx, cy, r)."""
    monkeypatch.setattr(holdout_eval, "detect_disk", lambda bgr: disk)
    return holdout_eval._crop_disk(frame, **kwargs)


def _pipeline_crop(frame, cx, cy, r, *, radius_scale=1.0, margin_px=14, output_size=128, pad=(0, 0, 0)):
    """Выход настоящего CenterCropPlugin с рецептовым регистром — оракул «формулы конвейера»."""
    ctx = MagicMock()
    ctx.config = {
        "size_mode": "radius",
        "radius_scale": radius_scale,
        "margin_px": margin_px,
        "output_size": output_size,
        "pad_if_oob": True,
        "drop_partial": False,
        "pad_color_bgr": list(pad),
    }
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    plugin = CenterCropPlugin()
    plugin.configure(ctx)
    item = {
        "frame": frame,
        "filtered": [{"xy": [cx, cy]}],
        "detections": [{"center": [cx, cy], "radius": r}],
    }
    out = plugin.process([item])
    assert len(out) == 1, "оракул не дал выреза — харнесс сломан, не код задачи"
    return out[0]["frame"], out[0]["sidecar"]


def _write_png(path: Path, frame: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", frame)
    assert ok
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.tobytes())


def _make_holdout(tmp_path: Path, letter: str, frame: np.ndarray, names=("0.png",)) -> Path:
    root = tmp_path / "holdout"
    for name in names:
        _write_png(root / letter / name, frame)
    return root


def _install_stub_engine(monkeypatch, labels, seen_frames: list) -> None:
    """Стаб `InferenceEngine`: label берётся из `labels` по порядку вызовов (str — один и тот же), angle_valid всегда
    True."""
    seq = [labels] if isinstance(labels, str) else list(labels)
    calls = {"n": 0}

    class _StubEngine:
        def __init__(self, *args, **kwargs):
            self._spec = SimpleNamespace(symmetry={})

        def load_model(self, *args, **kwargs):
            return None

        def predict(self, frame, top_k=1):
            seen_frames.append(frame.copy())
            label = seq[min(calls["n"], len(seq) - 1)]
            calls["n"] += 1
            return [{"label": label, "confidence": 0.9, "angle_deg": 0.0, "angle_valid": True}]

    monkeypatch.setattr(holdout_eval, "InferenceEngine", _StubEngine)


def _install_log_recorder(monkeypatch) -> list[str]:
    """Заменить `holdout_eval.logger` записывающей заглушкой; вернуть список уже отформатированных сообщений."""
    records: list[str] = []

    class _Rec:
        def _put(self, msg, *args, **kwargs):
            records.append(msg % args if args else msg)

        info = warning = error = debug = _put

    monkeypatch.setattr(holdout_eval, "logger", _Rec())
    return records


def _run_eval(tmp_path, monkeypatch, *, labels="A", disk=(320, 240, 150), names=("0.png",), **kwargs):
    """Прогнать `evaluate_holdout` на hold-out из одной папки-буквы «A»; вернуть (сводка, кадры, записи лога)."""
    seen: list = []
    _install_stub_engine(monkeypatch, labels, seen)
    monkeypatch.setattr(holdout_eval, "detect_disk", lambda bgr: disk)
    records = _install_log_recorder(monkeypatch)
    root = _make_holdout(tmp_path, "A", _frame(), names=names)
    summary = holdout_eval.evaluate_holdout("m", root, models_dir=str(tmp_path / "models"), **kwargs)
    return summary, seen, records


# --------------------------------------------------------------------------- A1


def test_control_plugin_item_with_detections_uses_the_radius_formula():
    """Контроль оракула A1: item со спековыми `filtered`/`detections` даёт сторону 328 (2·150 + 2·14), а не
    `side_px`=200.

    Ловит: харнесс, в котором плагин молча берёт fallback `side_px` -> A1 сравнивал бы «не те» байты.
    """
    _, sidecar = _pipeline_crop(_frame(), 320, 240, 150, output_size=0)
    assert sidecar["radius_px"] == 150
    assert sidecar["side_px"] == 328


def test_a1_crop_disk_is_byte_equal_to_pipeline_plugin_literal_case(monkeypatch):
    """A1: кадр 640x480, диск (320, 240, 150), дефолты рецепта -> (128, 128, 3) и побайтно равно выходу
    CenterCropPlugin.

    Ловит: старую формулу (сторона 2r·1.18 = 354, репликация) — другая форма/байты; resize не к 128; другой interp.
    """
    frame = _frame()
    out = _crop_disk_with(
        monkeypatch, frame, (320, 240, 150), radius_scale=1.0, margin_px=14, output_size=128, pad_color_bgr=(0, 0, 0)
    )
    expected, _ = _pipeline_crop(frame, 320, 240, 150)
    assert out.shape == (128, 128, 3)
    assert out.dtype == np.uint8
    assert out.tobytes() == expected.tobytes()


@pytest.mark.parametrize(
    ("disk", "kwargs"),
    [
        pytest.param((20, 240, 150), {"pad": (7, 8, 9)}, id="edge-pad-7-8-9-downscale"),
        pytest.param(
            (320, 240, 100), {"radius_scale": 0.5, "margin_px": 10, "output_size": 64}, id="scale-0.5-downscale-to-64"
        ),
        pytest.param((320, 240, 40), {}, id="small-disk-upscale-INTER_LINEAR"),
        pytest.param((320, 240, 150), {"output_size": 0}, id="no-resize"),
    ],
)
def test_a1_crop_disk_matches_pipeline_plugin_for_other_parameters(monkeypatch, disk, kwargs):
    """A1 (расширение): та же побайтная эквивалентность при недефолтных параметрах, у края кадра, в обе ветки interp.

    Ловит: жёстко зашитые дефолты, игнор одного из аргументов, неверный interp для увеличения (side 108 -> 128).
    """
    frame = _frame()
    plugin_kwargs = {"radius_scale": 1.0, "margin_px": 14, "output_size": 128, "pad": (0, 0, 0)}
    plugin_kwargs.update(kwargs)
    out = _crop_disk_with(
        monkeypatch,
        frame,
        disk,
        radius_scale=plugin_kwargs["radius_scale"],
        margin_px=plugin_kwargs["margin_px"],
        output_size=plugin_kwargs["output_size"],
        pad_color_bgr=plugin_kwargs["pad"],
    )
    expected, _ = _pipeline_crop(frame, *disk, **plugin_kwargs)
    assert out.shape == expected.shape
    assert out.tobytes() == expected.tobytes()


# --------------------------------------------------------------------------- A2


@pytest.mark.parametrize(
    ("r", "radius_scale", "margin_px", "side"),
    [
        pytest.param(150, 1.0, 14, 328, id="spec-2*150+2*14"),
        pytest.param(100, 0.5, 10, 120, id="scale-0.5"),
        pytest.param(99, 1.5, 14, 325, id="odd-side"),
    ],
)
def test_a2_side_before_resize_follows_the_radius_formula(monkeypatch, r, radius_scale, margin_px, side):
    """A2: при output_size=0 сторона выреза = 2·r·radius_scale + 2·margin_px (328 для r=150).

    Ловит: формулу 2·r·(1+margin) старого кода (354); margin_px без удвоения (321); отбрасывание radius_scale.
    """
    out = _crop_disk_with(
        monkeypatch,
        _frame(),
        (320, 240, r),
        radius_scale=radius_scale,
        margin_px=margin_px,
        output_size=0,
        pad_color_bgr=(0, 0, 0),
    )
    assert out.shape == (side, side, 3)


# --------------------------------------------------------------------------- A3


def test_a3_left_edge_is_filled_with_pad_color_not_replicated(monkeypatch):
    """A3: cx=20, output_size=0: левые 144 столбца = (7, 8, 9); остальное — исходный кадр (x 0..183, y 76..403).

    Ловит: `oob="replicate"` (левые столбцы копируют край кадра), заливку не тем цветом, сдвиг окна.
    Литералы: half = 328 // 2 = 164 -> x0 = 20 - 164 = -144; y0 = 240 - 164 = 76.
    """
    frame = _frame()
    out = _crop_disk_with(
        monkeypatch, frame, (20, 240, 150), radius_scale=1.0, margin_px=14, output_size=0, pad_color_bgr=(7, 8, 9)
    )
    assert out.shape == (328, 328, 3)
    assert np.all(out[:, :144] == np.array([7, 8, 9], dtype=np.uint8))
    assert np.array_equal(out[:, 144:], frame[76:404, 0:184])


@pytest.mark.parametrize(
    "disk",
    [
        pytest.param((-1000, 240, 150), id="far-left"),
        pytest.param((5000, 240, 150), id="far-right"),
        pytest.param((320, -1000, 150), id="far-above"),
        pytest.param((320, 5000, 150), id="far-below"),
    ],
)
def test_a3_square_without_overlap_is_a_pad_canvas_not_an_exception(monkeypatch, disk):
    """A3: квадрат без пересечения с кадром -> холст (328, 328, 3) цвета pad_color_bgr, без исключения.

    Ловит: сохранённый `ValueError` старого `replicate`; None вместо холста; холст другого цвета/формы.
    """
    out = _crop_disk_with(
        monkeypatch, _frame(), disk, radius_scale=1.0, margin_px=14, output_size=0, pad_color_bgr=(7, 8, 9)
    )
    assert out.shape == (328, 328, 3)
    assert np.all(out == np.array([7, 8, 9], dtype=np.uint8))


def test_a3_boundary_touching_square_is_all_pad_and_one_column_overlap_is_not(monkeypatch):
    """A3 (граница, расширение): cx=-164 (x1=0) — чистый холст; cx=-163 — ровно один столбец кадра справа.

    Ловит: сдвиг границы пересечения на ±1 (<= против <), неверный индекс вклейки.
    """
    frame = _frame()
    touching = _crop_disk_with(
        monkeypatch, frame, (-164, 240, 150), radius_scale=1.0, margin_px=14, output_size=0, pad_color_bgr=(7, 8, 9)
    )
    assert np.all(touching == np.array([7, 8, 9], dtype=np.uint8))
    one_col = _crop_disk_with(
        monkeypatch, frame, (-163, 240, 150), radius_scale=1.0, margin_px=14, output_size=0, pad_color_bgr=(7, 8, 9)
    )
    assert np.all(one_col[:, :327] == np.array([7, 8, 9], dtype=np.uint8))
    assert np.array_equal(one_col[:, 327], frame[76:404, 0])


# --------------------------------------------------------------------------- A4


@pytest.mark.parametrize("output_size", [0, 128])
def test_a4_output_does_not_share_memory_with_the_frame(monkeypatch, output_size):
    """A4: выход не делит память с кадром (и без ресайза, и с ним). Кадр read-only, как view из SHM.

    Ловит: возврат view `frame[y0:y1, x0:x1]` вместо копии (особенно при output_size=0 — ресайз копию скрыл бы).
    """
    frame = _frame()
    frame.setflags(write=False)
    out = _crop_disk_with(
        monkeypatch,
        frame,
        (320, 240, 150),
        radius_scale=1.0,
        margin_px=14,
        output_size=output_size,
        pad_color_bgr=(0, 0, 0),
    )
    assert not np.shares_memory(out, frame)


def test_a4_writing_to_output_leaves_the_frame_untouched(monkeypatch):
    """A4 (наблюдаемый эффект): запись в выход не меняет кадр; выход пишется, хотя кадр read-only.

    Ловит: view на буфер кадра — запись пошла бы в живой буфер или упала на read-only флаге.
    """
    frame = _frame()
    snapshot = frame.copy()
    frame.setflags(write=False)
    out = _crop_disk_with(
        monkeypatch, frame, (320, 240, 150), radius_scale=1.0, margin_px=14, output_size=0, pad_color_bgr=(0, 0, 0)
    )
    out[...] = 255
    assert np.array_equal(frame, snapshot)


def test_a4_read_only_frame_is_accepted(monkeypatch):
    """A4: read-only кадр не вызывает исключения и даёт вырез (128, 128, 3) uint8.

    Ловит: in-place операции над входом, ресайз/вырез, падающие на write=False.
    """
    frame = _frame()
    frame.setflags(write=False)
    out = _crop_disk_with(
        monkeypatch, frame, (320, 240, 150), radius_scale=1.0, margin_px=14, output_size=128, pad_color_bgr=(0, 0, 0)
    )
    assert out.shape == (128, 128, 3)
    assert out.dtype == np.uint8


# --------------------------------------------------------------------------- A5: evaluate_holdout


def test_control_stub_engine_hit_gives_accuracy_one(tmp_path, monkeypatch):
    """Контроль харнесса A5: стаб с label = имени папки даёт accuracy 1.0 по 1 образцу (работает и на старом коде).

    Ловит: сломанный стаб/PNG-ридер — иначе красные тесты ниже краснели бы по причине харнесса, не задачи.
    """
    summary, _, _ = _run_eval(tmp_path, monkeypatch)
    assert summary["samples"] == 1
    assert summary["accuracy"] == 1.0


def test_a5_summary_has_crop_key_with_default_values(tmp_path, monkeypatch):
    """A5: с дефолтами `summary["crop"] == {radius_scale 1.0, margin_px 14, output_size 128, pad_color_bgr [0, 0, 0]}`.

    Ловит: отсутствие ключа; дефолты не те; `pad_color_bgr` кортежем (не JSON-совместимо; `(0,0,0) != [0,0,0]`).
    """
    summary, _, _ = _run_eval(tmp_path, monkeypatch)
    assert summary.get("crop") == _DEFAULT_CROP


def test_a5_summary_crop_reflects_passed_values(tmp_path, monkeypatch):
    """A5 (расширение): переданные значения попадают в `summary["crop"]` (pad_color_bgr — список).

    Ловит: «крышку» — в сводку пишутся константы, а не то, чем резали.
    """
    summary, _, _ = _run_eval(
        tmp_path, monkeypatch, radius_scale=0.5, margin_px=10, output_size=0, pad_color_bgr=(1, 2, 3)
    )
    assert summary.get("crop") == {"radius_scale": 0.5, "margin_px": 10, "output_size": 0, "pad_color_bgr": [1, 2, 3]}


def test_a5_model_input_is_byte_equal_to_the_pipeline_crop(tmp_path, monkeypatch):
    """A5/DESIGN: кадр, пришедший в `engine.predict`, побайтно равен выходу CenterCropPlugin (128x128, формула
    конвейера).

    Ловит: резку по старой формуле (354x354, репликация) и отсутствие `resize_square` до движка.
    """
    _, seen, _ = _run_eval(tmp_path, monkeypatch)
    expected, _ = _pipeline_crop(_frame(), 320, 240, 150)
    assert len(seen) == 1
    assert seen[0].shape == (128, 128, 3)
    assert seen[0].tobytes() == expected.tobytes()


def test_a5_passed_crop_parameters_reach_the_model_input(tmp_path, monkeypatch):
    """A5 (расширение): radius_scale=0.5, margin_px=10, output_size=0 -> в движок приходит (170, 170, 3) = 2·150·0.5 +
    2·10.

    Ловит: параметры, принятые сигнатурой, но не доехавшие до `_crop_disk` (дефолты зашиты ниже по стеку).
    """
    _, seen, _ = _run_eval(tmp_path, monkeypatch, radius_scale=0.5, margin_px=10, output_size=0)
    assert seen[0].shape == (170, 170, 3)


def test_a3_pad_color_reaches_the_model_input_end_to_end(tmp_path, monkeypatch):
    """A3 через `evaluate_holdout`: диск у левого края, pad (7, 8, 9), output_size=0 -> левые 144 столбца входа модели
    = (7, 8, 9).

    Ловит: `pad_color_bgr` не передан из `evaluate_holdout` в `_crop_disk` (чёрная/реплицированная заливка).
    """
    _, seen, _ = _run_eval(tmp_path, monkeypatch, disk=(20, 240, 150), output_size=0, pad_color_bgr=(7, 8, 9))
    assert seen[0].shape == (328, 328, 3)
    assert np.all(seen[0][:, :144] == np.array([7, 8, 9], dtype=np.uint8))


def test_a5_margin_argument_is_removed(tmp_path, monkeypatch):
    """A5: `evaluate_holdout(..., margin=0.18)` -> TypeError (аргумент удалён без алиаса).

    Ловит: оставленный `margin`/алиас — старый вызов продолжил бы молча работать по старой формуле.
    """
    _install_stub_engine(monkeypatch, "A", [])
    monkeypatch.setattr(holdout_eval, "detect_disk", lambda bgr: (320, 240, 150))
    root = _make_holdout(tmp_path, "A", _frame())
    with pytest.raises(TypeError, match="margin"):
        holdout_eval.evaluate_holdout("m", root, models_dir=str(tmp_path / "models"), margin=0.18)


def test_a5_miss_does_not_raise_and_accuracy_is_zero(tmp_path, monkeypatch):
    """A5: чужой label + angle_valid True + файл `A/0.png` (в имени цифра) -> сводка без исключения, accuracy 0.0.

    Ловит: дефект `holdout_eval.py:118-120` — `ang_errors[-1]` в строке лога без условия `ok` -> IndexError на первом
    промахе.
    """
    summary, _, _ = _run_eval(tmp_path, monkeypatch, labels="B")
    assert summary["samples"] == 1
    assert summary["accuracy"] == 0.0


def test_a5_miss_gives_no_angle_statistics(tmp_path, monkeypatch):
    """A5 (расширение): на промахе угол не учитывается — `angle_mae_deg is None` (угол только при верной букве).

    Ловит: «починку» IndexError через учёт угла на промахе.
    """
    summary, _, _ = _run_eval(tmp_path, monkeypatch, labels="B")
    assert summary["angle_mae_deg"] is None


def test_a5_miss_log_line_has_no_angle_suffix_after_a_hit(tmp_path, monkeypatch):
    """A5 (расширение): hold-out из `A/0.png` (попадание) и `A/1.png` (промах) -> в строке лога промаха нет
    `angle=`/`err=`.

    Ловит: «починку» `if ang_errors and …` — IndexError ушёл бы, но строка промаха показала бы УСТАРЕВШУЮ ошибку
    предыдущего образца (`ang_errors[-1]` от `0.png`). Привязано к существующему формату строки лога (`angle=`/`err=`).
    """
    _, _, records = _run_eval(tmp_path, monkeypatch, labels=["A", "B"], names=("0.png", "1.png"))
    miss_lines = [r for r in records if "A/1.png" in r]
    assert len(miss_lines) == 1  # якорь существования: строка промаха вообще была залогирована
    assert "angle=" not in miss_lines[0]
    assert "err=" not in miss_lines[0]


def test_control_hit_log_line_keeps_the_angle_suffix(tmp_path, monkeypatch):
    """Контроль к предыдущему: строка лога попадания `A/0.png` сохраняет хвост `angle=… err=…`.

    Ловит: «починку» удалением хвоста целиком (спека: условие `ok and …`, а не снятие вывода угла).
    """
    _, _, records = _run_eval(tmp_path, monkeypatch, labels=["A", "B"], names=("0.png", "1.png"))
    hit_lines = [r for r in records if "A/0.png" in r]
    assert len(hit_lines) == 1
    assert "angle=" in hit_lines[0]
    assert "err=" in hit_lines[0]


# --------------------------------------------------------------------------- A5: CLI


def _spy_evaluate_holdout(monkeypatch) -> list[tuple[tuple, dict]]:
    """Шпион на `holdout_eval.evaluate_holdout`; возвращает то, что `_cmd_eval` читает после вызова."""
    calls: list[tuple[tuple, dict]] = []

    def _fake(*args, **kwargs):
        calls.append((args, kwargs))
        return {"accuracy": 0.0, "angle_mae_deg": None}

    monkeypatch.setattr(holdout_eval, "evaluate_holdout", _fake)
    return calls


def _main(argv):
    from Services.ml_train.__main__ import main

    return main(argv)


def test_a5_cli_pad_color_is_parsed_into_a_tuple_of_ints(tmp_path, monkeypatch):
    """A5: `eval m <dir> --pad-color-bgr 7,8,9` -> шпион получил `pad_color_bgr == (7, 8, 9)` — tuple из int.

    Ловит: строку "7,8,9" без разбора; список вместо tuple; элементы-строки; флаг, не доехавший до вызова.
    """
    calls = _spy_evaluate_holdout(monkeypatch)
    assert _main(["eval", "m", str(tmp_path), "--pad-color-bgr", "7,8,9"]) == 0
    assert len(calls) == 1
    value = calls[0][1]["pad_color_bgr"]
    assert value == (7, 8, 9)
    assert type(value) is tuple
    assert all(type(c) is int for c in value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("0,0,0", (0, 0, 0), id="lower-bound"),
        pytest.param("255,255,255", (255, 255, 255), id="upper-bound"),
    ],
)
def test_a5_cli_pad_color_accepts_the_boundaries(tmp_path, monkeypatch, raw, expected):
    """A5 (граница): 0 и 255 допустимы (диапазон 0..255 включительно).

    Ловит: ошибку «< 255»/«> 0» вместо «<= 255»/«>= 0» — отвергнутые крайние значения.
    """
    calls = _spy_evaluate_holdout(monkeypatch)
    assert _main(["eval", "m", str(tmp_path), "--pad-color-bgr", raw]) == 0
    assert calls[0][1]["pad_color_bgr"] == expected


@pytest.mark.parametrize(
    ("flag", "raw", "expected"),
    [
        pytest.param("--radius-scale", "0.5", 0.5, id="radius-scale-float"),
        pytest.param("--margin-px", "10", 10, id="margin-px-int"),
        pytest.param("--margin-px", "0", 0, id="margin-px-zero-is-not-dropped"),
        pytest.param("--output-size", "64", 64, id="output-size-int"),
        pytest.param("--output-size", "0", 0, id="output-size-zero-is-not-dropped"),
    ],
)
def test_a5_cli_numeric_flags_are_forwarded_with_their_type(tmp_path, monkeypatch, flag, raw, expected):
    """A5: числовые флаги доезжают до `evaluate_holdout` числом нужного типа; нулевое значение не теряется.

    Ловит: значение-строку (нет `type=`); проверку `if args.output_size:` — `0` (ресайз выкл.) молча стал бы дефолтом
    128.
    """
    calls = _spy_evaluate_holdout(monkeypatch)
    assert _main(["eval", "m", str(tmp_path), flag, raw]) == 0
    key = flag.lstrip("-").replace("-", "_")
    value = calls[0][1][key]
    assert value == expected
    assert type(value) is type(expected)


def test_a5_cli_without_flags_passes_none_of_the_four_keys(tmp_path, monkeypatch):
    """A5: `eval m <dir>` без флагов -> в kwargs шпиона нет ни одного из четырёх ключей (дефолты живут только в
    сигнатуре).

    Ловит: дефолты, продублированные в CLI (`default=128` и т.п.), и передачу `None` явным аргументом.
    """
    calls = _spy_evaluate_holdout(monkeypatch)
    assert _main(["eval", "m", str(tmp_path)]) == 0
    assert len(calls) == 1
    assert not set(_FOUR_KEYS) & set(calls[0][1])


def test_a5_cli_still_forwards_models_dir_and_device(tmp_path, monkeypatch):
    """A5 (регрессия): прежние `models_dir`/`device` по-прежнему идут в `evaluate_holdout` kwargs.

    Ловит: перестройку вызова, потерявшую прежние аргументы.
    """
    calls = _spy_evaluate_holdout(monkeypatch)
    assert _main(["eval", "m", str(tmp_path)]) == 0
    kwargs = calls[0][1]
    assert kwargs["models_dir"] == "data/models"
    assert kwargs["device"] == "cpu"


_BAD_PAD_COLORS = ["7,8", "7,8,300", "7,8,9,10", "256,0,0", "-1,0,0", "a,b,c", ""]


@pytest.mark.parametrize("raw", _BAD_PAD_COLORS)
def test_a5_cli_bad_pad_color_exits_with_code_2(tmp_path, monkeypatch, raw):
    """A5: неверный `--pad-color-bgr` (2 числа, >255, 4 числа, <0, не числа, пусто) -> SystemExit(2), оценка не вызвана.

    ЗЕЛЁНЫЙ ДО РЕАЛИЗАЦИИ ПО НЕВЕРНОЙ ПРИЧИНЕ (argparse отвергает неизвестный флаг тем же кодом); содержательно контракт
    держат `..._accepts_...` и `..._message_...`. Ловит: молчаливое принятие неверного цвета (clamp, дополнение нулями).
    """
    calls = _spy_evaluate_holdout(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        _main(["eval", "m", str(tmp_path), f"--pad-color-bgr={raw}"])
    assert excinfo.value.code == 2
    assert calls == []


@pytest.mark.parametrize("raw", [r for r in _BAD_PAD_COLORS if r])
def test_a5_cli_bad_pad_color_message_names_the_format_and_does_not_echo_the_value(tmp_path, monkeypatch, capsys, raw):
    """A5/DESIGN: текст ошибки называет формат (`B,G,R`) и не повторяет введённое значение.

    Ловит: `type=` на голом `int()`/`ValueError` (argparse напишет `invalid ... value: '7,8,300'`) и отказ без
    подсказки формата;
    сегодняшний argparse (`unrecognized arguments: --pad-color-bgr=<значение>`) тоже красный — флага нет.
    """
    _spy_evaluate_holdout(monkeypatch)
    with pytest.raises(SystemExit) as excinfo:
        _main(["eval", "m", "holdout_dir", f"--pad-color-bgr={raw}"])
    assert excinfo.value.code == 2
    stderr = capsys.readouterr().err
    assert "error:" in stderr  # якорь существования: сообщение вообще напечатано
    message = stderr.split("error:", 1)[1]  # без строки usage: в ней метавар флага может содержать B,G,R сам по себе
    assert "B,G,R" in message
    assert raw not in message


def test_a5_cli_help_lists_the_four_new_flags(capsys):
    """A5: `eval --help` перечисляет `--radius-scale`, `--margin-px`, `--output-size`, `--pad-color-bgr`.

    Ловит: флаги, добавленные не в подпарсер `eval` (или без регистрации), — пользователь их не найдёт.
    """
    with pytest.raises(SystemExit) as excinfo:
        _main(["eval", "--help"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--radius-scale", "--margin-px", "--output-size", "--pad-color-bgr"):
        assert flag in out


# --------------------------------------------------------------------------- A8


def _find_center_crop_sections(node) -> list[dict]:
    """Все словари с `plugin_name == "center_crop"` в разобранном рецепте (рекурсивно:
    `blueprint.processes[*].plugins[*]`)."""
    found: list[dict] = []
    if isinstance(node, dict):
        if node.get("plugin_name") == "center_crop":
            found.append(node)
        for value in node.values():
            found.extend(_find_center_crop_sections(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_find_center_crop_sections(value))
    return found


def _recipe_center_crop_config() -> dict:
    doc = yaml.safe_load(_RECIPE.read_text(encoding="utf-8"))
    sections = _find_center_crop_sections(doc)
    assert len(sections) == 1, f"ожидалась ровно одна секция center_crop в рецепте, найдено {len(sections)}"
    return sections[0]["config"]


def _register_default(name: str):
    return getattr(CenterCropRegisters(), name)


def test_a8_recipe_center_crop_is_radius_mode_with_pad():
    """A8: в рецепте `size_mode == "radius"`, `pad_if_oob is True`, `drop_partial is False`.

    ЗЕЛЁНЫЙ ДО РЕАЛИЗАЦИИ (рецепт уже такой). Ловит: правку рецепта (fixed-режим, clamp/drop у края) в обход
    `holdout_eval`:
    тогда сигнатурные дефолты перестали бы описывать «то, что видит робот».
    """
    cfg = _recipe_center_crop_config()
    assert cfg["size_mode"] == "radius"
    assert cfg["pad_if_oob"] is True
    assert cfg["drop_partial"] is False


def test_a8_register_default_pad_color_is_black_and_recipe_does_not_override_it():
    """A8: дефолт регистра `pad_color_bgr == [0, 0, 0]` (литерал), рецепт цвет не переопределяет.

    ЗЕЛЁНЫЙ ДО РЕАЛИЗАЦИИ. Ловит: смену дефолта регистра/появление цвета в рецепте без правки `holdout_eval`.
    """
    assert list(_register_default("pad_color_bgr")) == [0, 0, 0]
    assert "pad_color_bgr" not in _recipe_center_crop_config()


@pytest.mark.parametrize("name", ["radius_scale", "margin_px", "output_size"])
def test_a8_evaluate_holdout_default_equals_recipe_value(name):
    """A8: дефолт параметра `evaluate_holdout` равен значению `center_crop.config` рецепта `letter_robot_sim.yaml`.

    Ловит: дефолт из сигнатуры, разошедшийся с рецептом (правка рецепта без правки `holdout_eval` -> красный);
    отсутствие параметра в сигнатуре (старый `margin`).
    """
    params = inspect.signature(holdout_eval.evaluate_holdout).parameters
    assert name in params
    assert params[name].default == _recipe_center_crop_config()[name]


def test_a8_evaluate_holdout_pad_default_equals_register_default():
    """A8: дефолт `pad_color_bgr` в сигнатуре равен дефолту `CenterCropRegisters` (сравнение как кортежей).

    Ловит: дефолт цвета, разошедшийся с регистром плагина; отсутствие параметра.
    """
    params = inspect.signature(holdout_eval.evaluate_holdout).parameters
    assert "pad_color_bgr" in params
    assert tuple(params["pad_color_bgr"].default) == tuple(_register_default("pad_color_bgr"))
