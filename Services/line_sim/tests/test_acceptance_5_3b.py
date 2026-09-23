# -*- coding: utf-8 -*-
"""RED-приёмка Task 5.3b — компоновщик (§4.2.1) и каталожный инструмент (§4.2.4).

Независимый tester, worktree на коммите контракта лида (``bfe9edd4``), до реализации.
Контракт — ТОЛЬКО §4.2.1/§4.2.4/§4.4 ``plans/line-sim/phase-5-contract-5.3.md``. Этот
файл — ``Services/line_sim/tests/``, поэтому НЕ импортирует ``Plugins.*`` (граница
слоёв, правило 9 корневого CLAUDE.md) — только ``Services.line_sim.*``.

``test_default_direction_unchanged`` — легитимно ЗЕЛЁНЫЙ уже сегодня: дефолт
контракта (``belt_direction=1``, ``entry_x_px=0.0``) даёт ту же формулу центра,
что и текущий код (``cx = offset_mm * px_per_mm - x_px``), байт-в-байт (докстринг
§4.2.1). Остальные — RED: параметров ``belt_direction``/``entry_x_px`` у
конструктора сегодня нет (``TypeError``), модуля ``make_letter_catalog`` нет
(``ModuleNotFoundError``).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from Services.line_sim.core.scene_compositor import SceneCompositor
from Services.line_sim.interfaces import ObjectPassport

pytestmark = pytest.mark.timeout(30)


def _opaque_sprite(size_px: int = 20) -> np.ndarray:
    """Простой непрозрачный квадрат RGBA — геометрия теста не зависит от формы."""
    sprite = np.zeros((size_px, size_px, 4), dtype=np.uint8)
    sprite[:, :, 0] = 200
    sprite[:, :, 3] = 255
    return sprite


class _FakeObj:
    def __init__(self, passport: ObjectPassport, sprite: np.ndarray) -> None:
        self.passport = passport
        self._sprite = sprite

    def render(self) -> np.ndarray:
        return self._sprite


class _FakeSpawner:
    def __init__(self, obj: _FakeObj) -> None:
        self._obj = obj

    def active_objects(self) -> list[_FakeObj]:
        return [self._obj]


def _passport(spawn_encoder: float = 0.0) -> ObjectPassport:
    return ObjectPassport(object_id="o1", class_name="А", angle_deg=0.0, defect=None, spawn_encoder=spawn_encoder)


def _find_object_cx(frame: np.ndarray, marker_channel: int = 0, threshold: int = 150) -> float:
    """Центр объекта по X — см. приём File 1 (индекс канала, не имя цвета)."""
    mask = frame[:, :, marker_channel] > threshold
    xs = np.nonzero(mask)[1]
    assert xs.size > 0, "объект не найден в кадре"
    return float(xs.mean())


def test_default_direction_unchanged():
    """§4.2.1: дефолт (без belt_direction/entry_x_px) — поведение байт-в-байт
    прежнее. Ожидаемо ЗЕЛЁНЫЙ уже сегодня — см. докстринг файла.

    ``now_encoder`` выбран так, чтобы центр объекта (100 px от левого края при
    px_per_mm=2.0) был дальше половины ширины спрайта (10 px) от обеих границ
    кадра — иначе спрайт обрезается краем кадра и центроид маски съезжает
    (это баг измерения теста, не компоновщика: см. Post ``_bbox_intersects`` —
    частично видимый объект НАМЕРЕННО считается видимым и рисуется обрезанным).
    """
    px_per_mm = 2.0
    belt_y_px = 50.0
    sprite = _opaque_sprite()
    spawner = _FakeSpawner(_FakeObj(_passport(spawn_encoder=0.0), sprite))
    compositor = SceneCompositor(spawner, px_per_mm=px_per_mm, belt_y_px=belt_y_px)

    from Services.line_sim.core.belt import encoder_to_offset_mm
    from Services.robot_comm.core.registers import FACTOR_MM

    target_cx_px = 100.0
    now_encoder = (target_cx_px / px_per_mm) / FACTOR_MM
    frame, passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 200.0, 100.0))
    assert passports
    cx = _find_object_cx(frame)

    # Формула сегодняшнего кода: cx = offset_mm * px_per_mm - x_px (см. scene_compositor.py).
    expected_cx = encoder_to_offset_mm(now_encoder, 0.0) * px_per_mm
    assert abs(cx - expected_cx) <= 1.0


def test_reverse_direction_moves_left_from_entry():
    """§4.2.1: belt_direction=-1 — с ростом encoder объект едет в сторону
    МЕНЬШЕГО x кадра (навстречу belt_direction=+1)."""
    px_per_mm = 2.0
    belt_y_px = 50.0
    entry_x_px = 180.0
    sprite = _opaque_sprite()

    def _cx_at(now_encoder: float) -> float:
        spawner = _FakeSpawner(_FakeObj(_passport(spawn_encoder=0.0), sprite))
        # Task 4.2.1: параметров belt_direction/entry_x_px у конструктора сегодня нет —
        # TypeError, ожидаемый провал ДО реализации.
        compositor = SceneCompositor(
            spawner,
            px_per_mm=px_per_mm,
            belt_y_px=belt_y_px,
            belt_direction=-1,
            entry_x_px=entry_x_px,
        )
        frame, passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 200.0, 100.0))
        assert passports
        return _find_object_cx(frame)

    cx_early = _cx_at(0.0)
    cx_later = _cx_at(15.0)
    assert cx_later < cx_early, f"belt_direction=-1: cx должен убывать, но {cx_early} -> {cx_later}"


def test_invalid_direction_raises():
    """§4.2.1: belt_direction вне {-1, 1} (0 или 2) -> ValueError."""
    sprite = _opaque_sprite()
    spawner = _FakeSpawner(_FakeObj(_passport(), sprite))
    with pytest.raises(ValueError):
        SceneCompositor(spawner, px_per_mm=2.0, belt_y_px=50.0, belt_direction=0)


def test_invalid_direction_raises_for_two():
    """Симметрично test_invalid_direction_raises — belt_direction=2 тоже ValueError."""
    sprite = _opaque_sprite()
    spawner = _FakeSpawner(_FakeObj(_passport(), sprite))
    with pytest.raises(ValueError):
        SceneCompositor(spawner, px_per_mm=2.0, belt_y_px=50.0, belt_direction=2)


# --------------------------------------------------------------------------- #
# §4.2.4 — Services/line_sim/tools/make_letter_catalog.py (НОВЫЙ модуль)
#
# Внутреннего Python API контракт не называет — только CLI-форму
# (``python -m ... --src --letters --diameter-px --out``, §4.2.4 плана). Вызов через
# subprocess избегает угадывания имени внутренней функции (ловушка «RED без
# interface.py»): либо модуля нет (ModuleNotFoundError), либо контракт неверно
# реализован — оба видны по коду возврата/stderr, без домыслов об устройстве модуля.
# --------------------------------------------------------------------------- #


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_png(path: Path, size_px: int, alpha_value: int = 255) -> None:
    """Записать простой RGBA PNG через реальный ``imwrite_unicode`` (кириллица в путях)."""
    import cv2

    from Services.dataset_gen.core.catalog import imwrite_unicode

    sprite = np.zeros((size_px, size_px, 4), dtype=np.uint8)
    sprite[:, :, :3] = 100
    sprite[:, :, 3] = alpha_value
    path.parent.mkdir(parents=True, exist_ok=True)
    imwrite_unicode(path, cv2.cvtColor(sprite, cv2.COLOR_RGBA2BGRA))


def _run_tool(src: Path, letters: str, diameter_px: int, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "Services.line_sim.tools.make_letter_catalog",
            "--src",
            str(src),
            "--letters",
            letters,
            "--diameter-px",
            str(diameter_px),
            "--out",
            str(out),
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.mark.parametrize("letter, src_size_px", [("А", 40), ("К", 120)])
def test_letter_catalog_tool_resizes_and_keeps_alpha(tmp_path: Path, letter: str, src_size_px: int):
    """§4.2.4: для каждой буквы все ``*.png`` папки источника ресайзятся до
    ``diameter-px`` с сохранением альфы. Модуля сегодня нет — ``returncode != 0``
    («No module named»), ожидаемый провал ДО реализации."""
    src = tmp_path / "manual_sprites"
    _write_png(src / letter / "sprite1.png", src_size_px, alpha_value=200)
    out = tmp_path / "out"
    diameter_px = 60

    result = _run_tool(src, letter, diameter_px, out)
    assert result.returncode == 0, f"stderr={result.stderr}"

    from Services.dataset_gen.core.catalog import imread_unicode

    out_files = list((out / letter).glob("*.png"))
    assert out_files, f"буква {letter!r}: выходных PNG нет"
    result_img = imread_unicode(out_files[0])
    assert result_img.shape[2] == 4, "альфа-канал потерян при ресайзе"
    assert max(result_img.shape[:2]) == diameter_px
    assert np.any(result_img[:, :, 3] == 200), "значения альфы не сохранены (не просто 0/255)"


def test_letter_catalog_tool_copies_meta_yaml(tmp_path: Path):
    """§4.2.4: ``meta.yaml`` копируется в выходную папку буквы."""
    src = tmp_path / "manual_sprites"
    _write_png(src / "А" / "sprite1.png", 40)
    meta_src = src / "А" / "meta.yaml"
    meta_src.write_text("defect_probability: 0.1\n", encoding="utf-8")
    out = tmp_path / "out"

    result = _run_tool(src, "А", 60, out)
    assert result.returncode == 0, f"stderr={result.stderr}"

    meta_out = out / "А" / "meta.yaml"
    assert meta_out.is_file(), "meta.yaml не скопирован"
    assert meta_out.read_text(encoding="utf-8") == meta_src.read_text(encoding="utf-8")


def test_letter_catalog_tool_missing_letter(tmp_path: Path):
    """§4.2.4: нет папки буквы источника -> ``SystemExit``, называющий букву
    (снаружи процесса — ненулевой код возврата, имя буквы в stderr)."""
    src = tmp_path / "manual_sprites"
    _write_png(src / "А" / "sprite1.png", 40)  # только А, Х нет
    out = tmp_path / "out"

    result = _run_tool(src, "АХ", 60, out)
    assert result.returncode != 0
    assert "Х" in result.stderr, f"stderr не называет отсутствующую букву: {result.stderr!r}"
