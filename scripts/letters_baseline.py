"""Замер базовой линии сети букв (letters-retrain Task 0.4; β7 плана release-1.0): буква + угол.

Это ИЗМЕРЕНИЕ, а не гейт: код выхода 0 при любом успешном замере, 2 — ошибка вызова (нет модели,
нет кадров, кривой флаг). Порогов PASS/FAIL здесь нет: пороги владельца для β7 не заданы (вопрос открыт),
печатается «пороги не заданы».

Не путать с соседями: ``scripts/capture_baseline.py`` — снимок покрытия для S7 gate (не про сеть);
``scripts/day1_capture_check.py`` — качество кадров (резкость/яркость/имена), не точность сети.

Два источника кадров, ОДИН счётчик метрик:

``sim``  — офлайн-рендер дисков кодом сима: ``Services.dataset_gen.core.layer_scene.LayerSceneGenerator``
           на пресете сима (``Services/line_sim/presets/letters_layered.yaml``, секция ``train``):
           ``layer_render.ObjectFactory`` (диск + буква), фон-лента, поперечное смещение центра
           ``lateral_offset_px`` [10, 20] со случайным знаком, вырез ``size_mode radius, margin 14, output 128``
           (те же числа, что у ``center_crop`` рецепта ``letter_robot_sim``). Дефекты выключены (0).
           Истина = (буква, угол), с которыми рендерили (угол метки генератора, градусы, против часовой).
           Приближение: вырез идёт по радиусу объекта из альфы спрайта, а не по радиусу круга Хафа
           ``circle_detector`` (шаг поиска диска в sim-режиме не выполняется).
``dir``  — папка кадров дня №1: ``<корень>/<БУКВА>/a<УГОЛ:03d>_<индекс>.<png|jpg…>``
           (схема ``scripts/day1_capture_check.py``, NAME_RE продублирован ниже). Истина = буква из
           подкаталога (NFC), угол из имени. ``--crop``:
             ``none``     — кадр уже вырез диска, уходит в сеть как есть;
             ``pipeline`` — полный кадр камеры гонится через НАСТОЯЩИЕ плагины рецепта в процессе, без процессов и
                            очередей: roi_crop → hsv_mask → morphology → circle_detector → center_crop, параметры
                            читаются из ``--recipe`` (по умолчанию letter_robot_sim.yaml; сам рецепт читается как
                            YAML, ``multiprocess_prototype.*`` не импортируется). Решение по факту чтения кода:
                            чистых функций у circle_detector/hsv_mask/morphology нет (всё в методах плагина с
                            регистром), НО плагины создаются и вызываются без процесса (как в их тестах:
                            ``configure(ctx)`` + ``process([item])``), поэтому приближение ``--crop hough`` не нужно —
                            код конвейера выполняется как есть. Вырез — ``Services.layer_render.crop`` (его же зовёт
                            center_crop). Если на кадре несколько кругов — берётся первый (сильнейший по Хафу);
                            ``line_filter`` (триггер пересечения линии) не воспроизводится. ``color_convert`` рецепта
                            (RGB→BGR камеры) не применяется: кадры берутся как лежат в файле.

Вход сети — как в приложении: тот же ``Services.ml_inference.InferenceEngine`` (stretch 128×128, RGB, нормализация
из .yaml модели), ``threshold=0.0`` у движка, порог применяется здесь как в ``MLInferencePlugin._mark_below_threshold``:
``below = not (confidence >= порога)`` (граница == порога — НЕ ниже; NaN — ниже). Симметрия класса берётся у движка
(``angle_symmetry`` топ-1 из .yaml): ``none`` — период 360°, ``180`` — период 180°, ``full`` — угол не определён
(кадр в статистику угла не входит).

Запуск из корня репозитория (интерпретатор и данные — из главного дерева, ``PYTHONPATH`` = корень этого дерева):
    python scripts/letters_baseline.py sim --models-dir <главное>/data/models --data-root <главное>/data
    python scripts/letters_baseline.py dir <папка> --crop none --models-dir <главное>/data/models
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Схема имён дня №1 — scripts/day1_capture_check.py (NAME_RE там же): a<УГОЛ:03d>_<индекс>
NAME_RE = re.compile(r"^a(\d{3})_(\d+)$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

DEFAULT_MODEL = "mobilenet_v3_large_20260616_050828"
DEFAULT_THRESHOLD = 0.5  # confidence_threshold ml_inference в рецепте letter_robot_sim
DEFAULT_LETTERS = "ПЕРМИ"
DEFAULT_ANGLES = "0,45,90,135,180,225,270,315"
DEFAULT_PRESET = "Services/line_sim/presets/letters_layered.yaml"
DEFAULT_RECIPE = "multiprocess_prototype/recipes/letter_robot_sim.yaml"
TOLERANCES_DEG = (5.0, 10.0, 15.0)
TOP_K = 5


# --------------------------------------------------------------------------- #
# Чистые функции метрик                                                        #
# --------------------------------------------------------------------------- #


def wrap_deg(value: float, period: float = 360.0) -> float:
    """Привести угол к полуинтервалу [-period/2, period/2)."""
    return (value + period / 2.0) % period - period / 2.0


def is_below(confidence: float, threshold: float) -> bool:
    """Как MLInferencePlugin._mark_below_threshold: ``not (conf >= порога)``; == порога не ниже, NaN ниже."""
    return not (float(confidence) >= float(threshold))


def symmetry_period(symmetry: str | None) -> float | None:
    """Период угла по симметрии класса: none → 360, 180 → 180, full/неизвестно → None (угол не определён)."""
    if symmetry == "none":
        return 360.0
    if symmetry == "180":
        return 180.0
    return None


def angle_error(
    pred_deg: float, truth_deg: float, symmetry: str | None, *, use_symmetry: bool = True, invert_truth: bool = False
) -> float | None:
    """Ошибка угла «сеть − истина», градусы.

    ``use_symmetry=True``: по модулю периода симметрии класса (180 → [-90, 90)); ``full`` → None.
    ``use_symmetry=False``: wrap в [-180, 180) без учёта симметрии.
    ``invert_truth=True``: истина заменена на -истина (проверка знака конвенции).
    """
    truth = -truth_deg if invert_truth else truth_deg
    if use_symmetry:
        period = symmetry_period(symmetry)
        if period is None:
            return None
    else:
        period = 360.0
    return wrap_deg(pred_deg - truth, period)


def angle_stats(deltas: list[float]) -> dict[str, Any]:
    """n, медиана (со знаком), p90 и max по |Δ|, доли |Δ| вне ±5/10/15°. Пустой список — None в числах."""
    stats: dict[str, Any] = {"n": len(deltas)}
    if not deltas:
        stats.update({"median": None, "p90_abs": None, "max_abs": None})
        stats.update({f"out_{int(t)}": None for t in TOLERANCES_DEG})
        return stats
    arr = np.asarray(deltas, dtype=np.float64)
    absd = np.abs(arr)
    stats["median"] = float(np.median(arr))
    stats["p90_abs"] = float(np.percentile(absd, 90))
    stats["max_abs"] = float(absd.max())
    for tol in TOLERANCES_DEG:
        stats[f"out_{int(tol)}"] = float((absd > tol).mean())
    return stats


def _pct(num: int, den: int) -> float | None:
    return None if den == 0 else 100.0 * num / den


@dataclass(frozen=True)
class FrameResult:
    """Один кадр: истина и ответ сети. ``pred_label is None`` — ответа нет (диск не найден / пустой predict)."""

    truth_letter: str
    truth_angle: float  # градусы, против часовой
    grid_angle: float  # ключ для таблицы «по углам сетки» (заданный угол / угол из имени)
    pred_label: str | None
    confidence: float = 0.0
    angle_deg: float | None = None
    angle_valid: bool = False
    symmetry: str | None = None


def compute_metrics(results: list[FrameResult], threshold: float) -> dict[str, Any]:
    """Все числа замера из списка кадров. Проценты «от всех» — от ``total`` (включая «диск не найден»)."""
    total = len(results)
    evaluated = [r for r in results if r.pred_label is not None]
    below = [r for r in evaluated if is_below(r.confidence, threshold)]
    answered = [r for r in evaluated if not is_below(r.confidence, threshold)]
    top1 = [r for r in evaluated if r.pred_label == r.truth_letter]
    correct_answered = [r for r in answered if r.pred_label == r.truth_letter]

    by_letter: dict[str, dict[str, Any]] = {}
    for letter in sorted({r.truth_letter for r in results}):
        rs = [r for r in results if r.truth_letter == letter]
        t1 = sum(1 for r in rs if r.pred_label == letter)
        ca = sum(1 for r in rs if r.pred_label == letter and not is_below(r.confidence, threshold))
        by_letter[letter] = {
            "n": len(rs),
            "top1": t1,
            "correct_answered": ca,
            "recall_top1_pct": _pct(t1, len(rs)),
            "recall_answered_pct": _pct(ca, len(rs)),
        }

    confusion = Counter((r.truth_letter, r.pred_label) for r in evaluated if r.pred_label != r.truth_letter)

    angle_frames = [r for r in top1 if r.angle_valid and r.angle_deg is not None]
    angle_answered = [r for r in angle_frames if not is_below(r.confidence, threshold)]

    def deltas(frames: list[FrameResult], **kw: Any) -> list[float]:
        out = (angle_error(r.angle_deg, r.truth_angle, r.symmetry, **kw) for r in frames)  # type: ignore[arg-type]
        return [d for d in out if d is not None]

    by_grid: dict[float, list[float]] = defaultdict(list)
    for r in angle_frames:
        d = angle_error(r.angle_deg, r.truth_angle, r.symmetry)  # type: ignore[arg-type]
        if d is not None:
            by_grid[r.grid_angle].append(d)

    return {
        "threshold": threshold,
        "total": total,
        "no_disc": total - len(evaluated),
        "top1_correct": len(top1),
        "top1_correct_pct": _pct(len(top1), total),
        "below_threshold": len(below),
        "below_threshold_pct": _pct(len(below), total),
        "answered": len(answered),
        "correct_answered": len(correct_answered),
        "correct_answered_pct_of_all": _pct(len(correct_answered), total),
        "correct_among_answered_pct": _pct(len(correct_answered), len(answered)),
        "recall_by_letter": by_letter,
        "confusion_top5": [
            {"truth": t, "pred": p, "count": c}
            for (t, p), c in sorted(confusion.items(), key=lambda kv: (-kv[1], kv[0]))
        ][:5],
        "angle": {
            "frames_correct_letter": len(top1),
            "frames_angle_undefined_full": len(top1) - len(angle_frames),
            "sym": angle_stats(deltas(angle_frames)),
            "sym_answered_only": angle_stats(deltas(angle_answered)),
            "no_sym": angle_stats(deltas(angle_frames, use_symmetry=False)),
            "inverted_sym": angle_stats(deltas(angle_frames, invert_truth=True)),
            "inverted_no_sym": angle_stats(deltas(angle_frames, use_symmetry=False, invert_truth=True)),
            "median_by_grid_angle_sym": {
                _fmt_angle(g): {"n": len(ds), "median": float(np.median(ds))} for g, ds in sorted(by_grid.items())
            },
        },
    }


def _fmt_angle(a: float) -> str:
    return str(int(a)) if float(a).is_integer() else str(a)


# --------------------------------------------------------------------------- #
# Вывод                                                                        #
# --------------------------------------------------------------------------- #


def _f(v: float | None, spec: str = ".1f", suffix: str = "") -> str:
    return "—" if v is None else f"{v:{spec}}{suffix}"


def format_table(m: dict[str, Any], header: list[str]) -> str:
    """Таблица метрик для печати (русский текст)."""
    lines = list(header)
    lines += [
        "",
        f"всего кадров:                              {m['total']}  (диск не найден: {m['no_disc']})",
        f"top-1 верно, % от всех (любая уверенность): {_f(m['top1_correct_pct'])} % ({m['top1_correct']}/{m['total']})",
        f"ниже порога {m['threshold']}, % от всех:              "
        f"{_f(m['below_threshold_pct'])} % ({m['below_threshold']}/{m['total']})",
        f"верно и выше порога, % от всех («Верно» плана): {_f(m['correct_answered_pct_of_all'])} % "
        f"({m['correct_answered']}/{m['total']})",
        f"верно среди ответивших (≥ порога):         {_f(m['correct_among_answered_pct'])} % "
        f"({m['correct_answered']}/{m['answered']})",
        "",
        "полнота по буквам (top-1 / верно при ответе):",
    ]
    for letter, d in m["recall_by_letter"].items():
        lines.append(
            f"  {letter}: {d['top1']}/{d['n']} = {_f(d['recall_top1_pct'])} %"
            f" / {d['correct_answered']}/{d['n']} = {_f(d['recall_answered_pct'])} %"
        )
    lines.append("матрица путаниц, топ-5 пар (истина → ответ: кадров):")
    lines += [f"  {c['truth']} → {c['pred']}: {c['count']}" for c in m["confusion_top5"]] or ["  ошибок буквы нет"]

    a = m["angle"]
    lines += [
        "",
        f"ошибка угла (сеть − истина, град), кадры с верной буквой: {a['frames_correct_letter']}"
        f", угол не определён (full): {a['frames_angle_undefined_full']}",
        f"  {'блок':<28}{'n':>5}{'медиана':>9}{'p90|Δ|':>8}{'max|Δ|':>8}{'>5°':>7}{'>10°':>7}{'>15°':>7}",
    ]
    names = {
        "sym": "по модулю симметрии",
        "sym_answered_only": "то же, только ≥ порога",
        "no_sym": "без учёта симметрии",
        "inverted_sym": "истина ИНВЕРТИРОВАНА (−θ)",
        "inverted_no_sym": "инверт., без симметрии",
    }
    for key, title in names.items():
        s = a[key]
        lines.append(
            f"  {title:<28}{s['n']:>5}{_f(s['median'], '+.1f'):>9}{_f(s['p90_abs']):>8}{_f(s['max_abs']):>8}"
            + "".join(
                f"{_f(None if s[f'out_{int(t)}'] is None else 100 * s[f'out_{int(t)}'], '.0f', '%'):>7}"
                for t in TOLERANCES_DEG
            )
        )
    lines.append(
        "  медиана Δ по углам сетки (с симметрией): "
        + (", ".join(f"{g}°: {v['median']:+.1f} (n={v['n']})" for g, v in a["median_by_grid_angle_sym"].items()) or "—")
    )
    lines += ["", "пороги PASS/FAIL не заданы (пороги владельца для β7 — вопрос открыт); код выхода 0 — это замер."]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Источник dir                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DirFrame:
    path: Path
    letter: str
    angle: int


def parse_frame_path(root: Path, path: Path) -> tuple[str, int] | None:
    """``<root>/<БУКВА>/a<УГОЛ:03d>_<индекс>.<ext>`` → (буква NFC, угол) или None, если схема не та."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if len(parts) != 2 or path.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    m = NAME_RE.match(path.stem)
    if m is None:
        return None
    return unicodedata.normalize("NFC", parts[0]), int(m.group(1))


def scan_dir(root: Path) -> tuple[list[DirFrame], list[str]]:
    """(кадры по схеме дня №1, файлы-картинки не по схеме)."""
    frames: list[DirFrame] = []
    skipped: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        parsed = parse_frame_path(root, p)
        if parsed is None:
            skipped.append(str(p.relative_to(root)))
        else:
            frames.append(DirFrame(p, parsed[0], parsed[1]))
    return frames, skipped


def read_image(path: Path) -> np.ndarray | None:
    """BGR-кадр или None. imdecode(fromfile), а не imread: путь с кириллицей (Windows)."""
    import cv2

    try:
        img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, cv2.error):
        return None
    return img


class RecipePipeline:
    """Настоящие плагины рецепта в процессе: roi_crop → hsv_mask → morphology → circle_detector → center_crop.

    Параметры — из YAML рецепта (blueprint.processes[*].plugins[*].config по plugin_name). Плагины зовутся так же,
    как в их тестах: ``configure(ctx)`` с заглушкой контекста и ``process([item])``.
    """

    def __init__(self, recipe_path: Path) -> None:
        import yaml

        from Plugins.processing.center_crop.plugin import CenterCropPlugin
        from Plugins.processing.circle_detector.plugin import CircleDetectorPlugin
        from Plugins.processing.hsv_mask.plugin import HsvMaskPlugin
        from Plugins.processing.morphology.plugin import MorphologyPlugin
        from Plugins.processing.roi_crop.plugin import RoiCropPlugin

        recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
        configs: dict[str, dict] = {}
        for proc in recipe["blueprint"]["processes"]:
            for plug in proc.get("plugins") or []:
                configs[plug["plugin_name"]] = plug.get("config") or {}
        classes = {
            "roi_crop": RoiCropPlugin,
            "hsv_mask": HsvMaskPlugin,
            "morphology": MorphologyPlugin,
            "circle_detector": CircleDetectorPlugin,
            "center_crop": CenterCropPlugin,
        }
        self.plugins: dict[str, Any] = {}
        for name, cls in classes.items():
            if name not in configs:
                raise ValueError(f"в рецепте {recipe_path} нет плагина {name}")
            ctx = MagicMock()  # заглушка PluginContext: registers=None → плагин берёт локальный регистр из config
            ctx.config = configs[name]
            ctx.registers = None
            plugin = cls()
            plugin.configure(ctx)
            self.plugins[name] = plugin

    def crop(self, frame_bgr: np.ndarray) -> np.ndarray | None:
        """Полный кадр камеры → вырез 128×128 BGR вокруг первого найденного круга; None — круг не найден."""
        items = [{"frame": frame_bgr}]
        for name in ("roi_crop", "hsv_mask", "morphology", "circle_detector"):
            items = self.plugins[name].process(items)
            if not items:
                return None
        item = items[0]
        detections = item.get("detections") or []
        if not detections:
            return None
        cx, cy = detections[0]["center"]  # Хаф отдаёт круги по убыванию голосов; line_filter не воспроизводится
        item = {**item, "filtered": [{"xy": [cx, cy]}]}
        out = self.plugins["center_crop"].process([item])
        return out[0]["frame"] if out else None


# --------------------------------------------------------------------------- #
# Источник sim                                                                 #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SimFrame:
    letter: str
    grid_angle: float
    truth_angle: float
    bgr: np.ndarray


def parse_angles(text: str) -> list[float]:
    try:
        angles = [float(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise ValueError(f"--angles: ожидался список чисел через запятую, получено {text!r}") from None
    if not angles or any(not 0.0 <= a < 360.0 for a in angles):
        raise ValueError(f"--angles: углы должны быть в [0, 360), получено {text!r}")
    return angles


def load_sim_preset(preset_path: Path, data_root: Path | None):
    """ScenePreset сима с defect_probability 0 в секции train. С ``data_root`` пути пресета (``../../../data/...``)
    резолвятся от ``<data_root>/../<тот же каталог пресета>`` — дерево с данными должно лежать целиком
    (рядом Services/)."""
    from Services.layer_render import ScenePreset

    preset = ScenePreset.from_yaml(preset_path)
    if data_root is not None:
        base = data_root.resolve().parent / preset_path.resolve().parent.relative_to(REPO_ROOT)
        if not base.is_dir():
            raise ValueError(f"--data-root: рядом с ним нет каталога {base} (нужно дерево репозитория с data/)")
        preset = preset.model_copy(update={"base_dir": str(base)})
    return preset.model_copy(update={"train": {**(preset.train or {}), "defect_probability": 0.0}})


def iter_sim_frames(preset, letters: list[str], angles: list[float], per_cell: int, seed: int) -> Iterator[SimFrame]:
    """Диски тем же генератором, что обучает/кормит сим. На каждый угол сетки — свой генератор с angle_range (a, a)."""
    import cv2

    from Services.dataset_gen.core.layer_scene import LayerSceneGenerator

    for ai, angle in enumerate(angles):
        gen = LayerSceneGenerator(preset.model_copy(update={"angle_range_deg": (angle, angle)}), seed=seed)
        names = gen.class_names
        for li, letter in enumerate(letters):
            if letter not in names:
                raise ValueError(f"буква {letter!r} нет в каталоге сима ({len(names)} классов)")
            rng = np.random.default_rng([seed, ai, li])
            for _ in range(per_cell):
                rgb, label = gen.generate_sample(class_index=names.index(letter), rng=rng)
                yield SimFrame(letter, angle, float(label.angle_deg), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


# --------------------------------------------------------------------------- #
# Прогон через сеть                                                            #
# --------------------------------------------------------------------------- #


def classify_frame(
    engine: Any, bgr: np.ndarray | None, letter: str, truth_angle: float, grid_angle: float
) -> FrameResult:
    """Кадр (None — диск не найден) → FrameResult через engine.predict (threshold=0.0, как в плагине)."""
    if bgr is None:
        return FrameResult(letter, truth_angle, grid_angle, None)
    preds = engine.predict(bgr, top_k=TOP_K, threshold=0.0)
    if not preds:
        return FrameResult(letter, truth_angle, grid_angle, None)
    top = preds[0]
    return FrameResult(
        truth_letter=letter,
        truth_angle=truth_angle,
        grid_angle=grid_angle,
        pred_label=top["label"],
        confidence=float(top["confidence"]),
        angle_deg=float(top["angle_deg"]) if "angle_deg" in top else None,
        angle_valid=bool(top.get("angle_valid", False)),
        symmetry=top.get("angle_symmetry"),
    )


def run_dir(engine: Any, frames: list[DirFrame], cropper: RecipePipeline | None) -> tuple[list[FrameResult], int]:
    """(результаты, нечитаемых файлов). cropper=None — кадр уже вырез."""
    results: list[FrameResult] = []
    unreadable = 0
    for fr in frames:
        img = read_image(fr.path)
        if img is None:
            unreadable += 1
            continue
        crop = cropper.crop(img) if cropper is not None else img
        results.append(classify_frame(engine, crop, fr.letter, float(fr.angle), float(fr.angle)))
    return results, unreadable


def run_sim(engine: Any, frames: Iterator[SimFrame]) -> list[FrameResult]:
    return [classify_frame(engine, f.bgr, f.letter, f.truth_angle, f.grid_angle) for f in frames]


def load_engine(models_dir: Path, model_id: str, device: str) -> Any:
    from Services.ml_inference.engine import InferenceEngine

    engine = InferenceEngine(str(models_dir))
    engine.load_model(model_id, device=device)  # ValueError, если модели нет в каталоге
    return engine


def read_labels(models_dir: Path, model_id: str) -> list[str]:
    path = models_dir / f"{model_id}_classes.txt"
    return [
        unicodedata.normalize("NFC", ln.strip()) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="letters_baseline",
        description="Замер базовой линии сети букв: top-1, порог, полнота по буквам, ошибка угла. "
        "Измерение, не гейт: код выхода 0, 2 — ошибка вызова. Порогов PASS/FAIL нет. Режимы sim и dir; "
        "флаги каждого режима — ниже.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--models-dir", default=str(REPO_ROOT / "data" / "models"), help="каталог моделей (onnx + yaml + _classes.txt)"
    )
    common.add_argument("--model", default=DEFAULT_MODEL, help="id модели (stem файла весов), по умолчанию %(default)s")
    common.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help="порог уверенности, по умолчанию %(default)s (как в рецепте)",
    )
    common.add_argument("--device", default="cpu", help="устройство движка, по умолчанию %(default)s")
    common.add_argument("--json-out", help="записать все метрики в JSON")
    sub = p.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("sim", parents=[common], help="офлайн-рендер дисков кодом сима, истина = (буква, угол) рендера")
    s.add_argument("--letters", default=DEFAULT_LETTERS, help="буквы подряд, по умолчанию %(default)s")
    s.add_argument("--all", action="store_true", help="все буквы из _classes.txt модели (33), перекрывает --letters")
    s.add_argument("--angles", default=DEFAULT_ANGLES, help="углы сетки, град, через запятую; по умолчанию %(default)s")
    s.add_argument("--per-cell", type=int, default=4, help="кадров на (буква, угол), по умолчанию %(default)s")
    s.add_argument("--seed", type=int, default=0, help="зерно, по умолчанию %(default)s")
    s.add_argument("--preset", default=DEFAULT_PRESET, help="пресет слоёв сима, по умолчанию %(default)s")
    s.add_argument(
        "--data-root",
        help="каталог data/ дерева с данными сима (belt_tile, letters_ink); по умолчанию — data/ этого дерева",
    )

    d = sub.add_parser("dir", parents=[common], help="папка кадров дня №1: <корень>/<БУКВА>/a<УГОЛ:03d>_<индекс>.<ext>")
    d.add_argument("root", help="корень набора кадров")
    d.add_argument(
        "--crop",
        choices=("none", "pipeline"),
        default="none",
        help="none: кадр уже вырез диска; pipeline: полный кадр через плагины рецепта "
        "(roi_crop→hsv_mask→morphology→circle_detector→center_crop)",
    )
    d.add_argument(
        "--recipe",
        default=DEFAULT_RECIPE,
        help="рецепт с параметрами плагинов для --crop pipeline, по умолчанию %(default)s",
    )
    # один вызов --help показывает оба режима и все их флаги
    p.epilog = "\n".join(f"=== режим {name} ===\n{sp.format_help()}" for name, sp in sub.choices.items())
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    models_dir = Path(args.models_dir)
    try:
        engine = load_engine(models_dir, args.model, args.device)
    except Exception as exc:  # noqa: BLE001 — любая причина «модели нет/не грузится» = ошибка вызова
        print(f"ошибка: модель {args.model} не загружена из {models_dir}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    header = [f"модель {args.model}; порог {args.threshold}; устройство {args.device}"]
    unreadable = 0
    try:
        if args.mode == "sim":
            letters = (
                read_labels(models_dir, args.model) if args.all else list(unicodedata.normalize("NFC", args.letters))
            )
            angles = parse_angles(args.angles)
            preset = load_sim_preset(Path(args.preset), Path(args.data_root) if args.data_root else None)
            results = run_sim(engine, iter_sim_frames(preset, letters, angles, args.per_cell, args.seed))
            lat = (preset.train or {}).get("lateral_offset_px")
            header += [
                f"источник: sim, букв {len(letters)}, углов {len(angles)}, "
                f"по {args.per_cell} на ячейку, seed {args.seed}",
                f"сим: дефекты 0, смещение центра ±{lat} px (секция train пресета), вырез radius/margin 14/128",
                "ПРИБЛИЖЕНИЕ: вырез по радиусу объекта из альфы спрайта, не по кругу Хафа circle_detector",
            ]
        else:
            root = Path(args.root)
            if not root.is_dir():
                print(f"ошибка: нет каталога {root}", file=sys.stderr)
                return 2
            frames, skipped = scan_dir(root)
            cropper = RecipePipeline(Path(args.recipe)) if args.crop == "pipeline" else None
            results, unreadable = run_dir(engine, frames, cropper)
            header += [
                f"источник: dir {root}, кадров по схеме {len(frames)}, не по схеме {len(skipped)}, "
                f"нечитаемых {unreadable}",
                "вход сети: кадр как есть (вырез диска)"
                if cropper is None
                else f"вход сети: плагины рецепта {args.recipe} в процессе "
                "(roi_crop→hsv_mask→morphology→circle_detector→center_crop), "
                "круг — первый по Хафу, line_filter не воспроизводится",
            ]
    except (ValueError, OSError, KeyError) as exc:
        print(f"ошибка: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if not results:
        print("ошибка: нет кадров для замера", file=sys.stderr)
        return 2

    metrics = compute_metrics(results, args.threshold)
    metrics["source"] = {"mode": args.mode, "model": args.model, "unreadable": unreadable, "header": header}
    metrics["thresholds_pass_fail"] = "не заданы (вопрос владельца β7)"
    print(format_table(metrics, header))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
