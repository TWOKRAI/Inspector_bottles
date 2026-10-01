# -*- coding: utf-8 -*-
"""Acceptance-тесты Task 3.6 — инструмент `Services/line_sim/tools/make_seamless_texture.py`
(период/зеркало, масштаб по шагу звена и по ширине фото).

Тесты фона-текстуры компоновщика (одиночный тайл) удалены в layer-render 1.3 вместе с параметром: те же свойства
(фон едет с объектом, цикличность сдвига, узкий тайл повторяется без растяжения, любая картинка — валидный фон)
держит стек слоёв — `test_acceptance_1_3_single_background.py::test_layers_*`.

Контракт инструмента: `make_seamless_tile(image) -> SeamlessResult(tile, method, period_px, seam_diff,
inner_diff)`, `method` in {"period", "mirror"}; `main(argv) -> int`.
`step(a, b) = mean(|a.astype(float) - b.astype(float)|)` по строкам и каналам;
`inner_diff = max по u in [0, tw-2] step(tile[:,u], tile[:,u+1])`, `seam_diff = step(tile[:,tw-1], tile[:,0])` —
тест пересчитывает эти величины САМ по возвращённому `tile`, числам инструмента не доверяет.
Источник контракта и догадки тестера — `docs/reviews/2026-09-23_task-3.6-tester.md`.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode


# --------------------------------------------------------------------------------------
# Хелперы пересчёта шва/внутреннего скачка тайла (не тестируют ничего сами)
# --------------------------------------------------------------------------------------


def _step(a: np.ndarray, b: np.ndarray) -> float:
    """Мера шага между столбцами тайла — литерал из контракта, не из кода под тестом."""
    return float(np.mean(np.abs(a.astype(float) - b.astype(float))))


def _recompute_inner_and_seam(tile: np.ndarray) -> tuple[float, float]:
    """Пересчёт `inner_diff`/`seam_diff` САМИМ тестом по возвращённому `tile` — числам
    инструмента не доверяем (инструкция ведущего)."""
    tw = tile.shape[1]
    inner_diff = max(_step(tile[:, u], tile[:, u + 1]) for u in range(tw - 1))
    seam_diff = _step(tile[:, tw - 1], tile[:, 0])
    return inner_diff, seam_diff


# --------------------------------------------------------------------------------------
# make_seamless_texture.py (импорт ВНУТРИ теста — отсутствие модуля роняет только эти
# четыре теста, не компоновщик выше)
# --------------------------------------------------------------------------------------


def test_tool_finds_known_period():
    """Критерий 5: периодический вход (синтетический тайл с периодом P, повторённый
    3.5 раза) — найденный период = P ± 1 px, ширина результата кратна `period_px`."""
    from Services.line_sim.tools.make_seamless_texture import make_seamless_tile

    period = 16
    width = int(round(period * 3.5))  # 56 px — ровно 3.5 периода, как требует критерий
    height = 8
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(width):
        level = int(255 * (x % period) / period)  # пилообразный профиль, без симметрии внутри периода
        image[:, x, :] = level

    result = make_seamless_tile(image)

    assert result.method == "period"
    assert abs(result.period_px - period) <= 1
    assert result.tile.shape[1] % result.period_px == 0


def test_tool_mirror_on_aperiodic_input():
    """Критерий 6: непериодический вход (монотонный градиент, без повторов на этой
    ширине) — не падает, откатывается на зеркальную склейку; собственный шов <=
    собственной внутренней разницы (контракт: зеркало даёт шов ровно 0)."""
    from Services.line_sim.tools.make_seamless_texture import make_seamless_tile

    width, height = 60, 8
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(width):
        image[:, x, :] = min(255, x * 4)  # монотонный градиент -> периода на этой ширине нет

    result = make_seamless_tile(image)

    assert result.method == "mirror"
    inner_diff, seam_diff = _recompute_inner_and_seam(result.tile)
    assert seam_diff <= inner_diff
    assert seam_diff == pytest.approx(0.0, abs=1e-6)  # зеркало стыкует буквально одинаковые столбцы


def test_tool_scale_by_pitch(tmp_path, capsys):
    """Добавленный критерий: `--pitch-mm M --scene-px-per-mm S` -> `period_px` результата
    == `round(M*S)` ± 1, проверено через `main()` + токены stdout + записанный PNG."""
    from Services.line_sim.tools import make_seamless_texture as tool

    period = 16
    width = int(round(period * 3.5))
    height = 8
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(width):
        image[:, x, :] = int(255 * (x % period) / period)

    src = tmp_path / "photo.png"
    imwrite_unicode(src, image)
    out = tmp_path / "tile.png"

    pitch_mm = 60.0
    scene_px_per_mm = 2.0
    expected_period_px = round(pitch_mm * scene_px_per_mm)  # round(120.0) = 120

    argv = [
        str(src),
        "--out",
        str(out),
        "--pitch-mm",
        str(pitch_mm),
        "--scene-px-per-mm",
        str(scene_px_per_mm),
    ]
    code = tool.main(argv)
    stdout_text = capsys.readouterr().out

    assert code == 0
    assert out.exists()
    # Правка лида 2026-09-23: только отдельный токен. Прежний r"period_px=(\d+)" находил число
    # внутри note= («период найден (period_px=121)…») — инструмент давал method=mirror, а тест
    # был зелёным с самого начала.
    match = re.search(r"(?:^|\s)period_px=(\d+)", stdout_text)
    assert match is not None, f"нет токена period_px в выводе: {stdout_text!r}"
    assert abs(int(match.group(1)) - expected_period_px) <= 1


def test_tool_scale_by_photo_width(tmp_path, capsys):
    """Добавленный критерий: `--photo-width-mm W --scene-px-per-mm S` -> токен `scale=`
    равен `S*W/photo_width`; на непериодическом входе ширина тайла = `2*round(W*S)` ± 2."""
    from Services.line_sim.tools import make_seamless_texture as tool

    photo_width, height = 60, 8
    image = np.zeros((height, photo_width, 3), dtype=np.uint8)
    for x in range(photo_width):
        image[:, x, :] = min(255, x * 4)  # непериодический вход -> ветка "зеркало"

    src = tmp_path / "photo.png"
    imwrite_unicode(src, image)
    out = tmp_path / "tile.png"

    photo_width_mm = 100.0
    scene_px_per_mm = 2.0
    expected_scale = scene_px_per_mm * photo_width_mm / photo_width  # 200/60 = 3.3(3)
    expected_scaled_width = round(photo_width_mm * scene_px_per_mm)  # round(200.0) = 200
    expected_tile_width = 2 * expected_scaled_width

    argv = [
        str(src),
        "--out",
        str(out),
        "--photo-width-mm",
        str(photo_width_mm),
        "--scene-px-per-mm",
        str(scene_px_per_mm),
    ]
    code = tool.main(argv)
    stdout_text = capsys.readouterr().out

    assert code == 0
    assert out.exists()
    scale_match = re.search(r"scale=([\d.]+)", stdout_text)
    assert scale_match is not None, f"нет токена scale в выводе: {stdout_text!r}"
    assert float(scale_match.group(1)) == pytest.approx(expected_scale, rel=1e-2)

    size_match = re.search(r"size=(\d+)x(\d+)", stdout_text)
    assert size_match is not None, f"нет токена size в выводе: {stdout_text!r}"
    result_width = int(size_match.group(1))
    assert abs(result_width - expected_tile_width) <= 2
