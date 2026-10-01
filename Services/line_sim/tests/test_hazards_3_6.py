# -*- coding: utf-8 -*-
"""Hazard-тесты автора для Task 3.6 — инструмент `make_seamless_texture.py` (H6, H7, H12-H15) и
форма тайла слоя `ScrollingTile` (H2, перенесён в layer-render 1.3).

Компоновщиковые hazard'ы одиночного тайла (H1, H3, H4, H5, H10, H11) удалены в layer-render 1.3 вместе с
параметром одиночного тайла: те же свойства (множитель `px_per_mm` в сдвиге, нечётная высота/нецелые
`belt_y_px`/`y_px`, цикличность на 1e9, `x_px` в формуле столбцов, копия массива) держит стек слоёв —
`test_acceptance_1_3_single_background.py` (test_layers_h1/h3/h5/h10/h11 и сплошная заливка `background_bgr`).
"""

from __future__ import annotations

import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.layer_render import ScrollingTile
from Services.line_sim.tools.make_seamless_texture import make_seamless_tile


# --------------------------------------------------------------------------------------
# Хелперы пересчёта шва/внутреннего скачка тайла (не тестируют ничего сами)
# --------------------------------------------------------------------------------------


def _step(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(float) - b.astype(float))))


def _recompute_inner_and_seam(tile: np.ndarray) -> tuple[float, float]:
    tw = tile.shape[1]
    inner_diff = max(_step(tile[:, u], tile[:, u + 1]) for u in range(tw - 1))
    seam_diff = _step(tile[:, tw - 1], tile[:, 0])
    return inner_diff, seam_diff


# --------------------------------------------------------------------------------------
# H1 — инвариант px_per_mm на нестандартном значении и ненулевом spawn_encoder
# --------------------------------------------------------------------------------------


# --------------------------------------------------------------------------------------
# H2 — валидация формы/dtype background_tile
# --------------------------------------------------------------------------------------


# --------------------------------------------------------------------------------------
# H2 — валидация формы/dtype тайла слоя (перенос с одиночного тайла компоновщика, layer-render 1.3)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(np.zeros((10, 10), dtype=np.uint8), id="grey_2d"),
        pytest.param(np.zeros((10, 10, 5), dtype=np.uint8), id="five_channels"),
        pytest.param(np.zeros((10, 10, 3), dtype=np.float32), id="float32"),
        pytest.param(np.zeros((10, 0, 3), dtype=np.uint8), id="zero_width"),
        pytest.param(np.zeros((0, 10, 3), dtype=np.uint8), id="zero_height"),
    ],
)
def test_h2_bad_scrolling_tile_shapes_raise_value_error(bad):
    """H2: невалидный массив тайла отвергается в конструкторе слоя (`ValueError`), а не доползает до `render()`
    и там падает на непредвиденной форме (или тихо даёт мусор в кадре). Раньше то же держал компоновщик для
    одиночного тайла; после его удаления границей стал `ScrollingTile`."""
    with pytest.raises(ValueError):
        ScrollingTile(bad)


# --------------------------------------------------------------------------------------
# H6 — виньетирование ломает период визуально, откат на зеркало обязателен
# --------------------------------------------------------------------------------------


def test_h6_periodic_pattern_with_vignetting_falls_back_to_mirror():
    """H6: период вдоль X есть, но накрыт линейным затемнением слева направо
    (виньетирование камеры) — обрезка ровно по периоду больше НЕ даёт совпадающих
    краёв (яркость на левом и правом краю тайла разная), значит `seam_diff >
    inner_diff` и код обязан откатиться на зеркало с печатью причины — тихий выбор
    "period" здесь был бы дефектом (шов виден на реальном стенде).

    Профиль — ГЛАДКАЯ синусоида (не пила): внутренний шаг между соседними столбцами
    остаётся маленьким (плавная производная), а виньетирование (амплитуда падает к
    правому краю линейно) создаёт скачок ИМЕННО на стыке последний-первый столбец —
    там, где яркость ещё не успела просесть, встречается с уже просевшим краем.
    Пилообразный профиль (как в тестах поиска периода) для этого не годится: у него и
    без виньетирования уже есть большой внутренний скачок на каждой границе периода
    (сброс пилы), который перекрывает эффект виньетирования и маскирует дефект."""
    period = 20
    width = int(round(period * 6.4))  # 128 px, 6.4 периода
    height = 6
    x = np.arange(width)
    base = 128.0 + 100.0 * np.sin(2 * np.pi * x / period)
    vignette = 1.0 - 0.8 * (x / (width - 1))  # яркость падает к правому краю
    profile = np.clip(base * vignette, 0, 255).astype(np.uint8)
    image = np.tile(profile[None, :, None], (height, 1, 3))

    result = make_seamless_tile(image)

    assert result.method == "mirror"
    assert result.note != "", "причина отката обязана печататься, а не проглатываться молча"
    inner_diff, seam_diff = _recompute_inner_and_seam(result.tile)
    assert seam_diff <= inner_diff + 1e-9


# --------------------------------------------------------------------------------------
# H7 — CLI: несовместимые/недостаточные аргументы масштаба
# --------------------------------------------------------------------------------------


def test_h7_cli_arg_validation_and_aperiodic_pitch(tmp_path):
    """H7: три пути неверного/невозможного вызова CLI не должны молча создавать файл
    или тихо использовать масштаб 1.0 по умолчанию — оба масштабных ключа сразу
    (argparse mutually exclusive), масштаб без опорной величины (`parser.error`), и
    `--pitch-mm` на изображении без периода (диагностируемый отказ, код 1)."""
    from Services.line_sim.tools import make_seamless_texture as tool

    width, height = 40, 6
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(width):
        image[:, x, :] = min(255, x * 8)  # монотонный градиент -> период не находится
    src = tmp_path / "photo.png"
    imwrite_unicode(src, image)

    out_wm = tmp_path / "wm.png"
    with pytest.raises(SystemExit) as exc_wm:
        tool.main(
            [
                str(src),
                "--out",
                str(out_wm),
                "--photo-width-mm",
                "100",
                "--pitch-mm",
                "10",
                "--scene-px-per-mm",
                "1.0",
            ]
        )
    assert exc_wm.value.code == 2
    assert not out_wm.exists()

    out_s_alone = tmp_path / "s.png"
    with pytest.raises(SystemExit) as exc_s:
        tool.main([str(src), "--out", str(out_s_alone), "--scene-px-per-mm", "1.0"])
    assert exc_s.value.code == 2
    assert not out_s_alone.exists()

    out_pitch = tmp_path / "pitch.png"
    code = tool.main([str(src), "--out", str(out_pitch), "--pitch-mm", "10", "--scene-px-per-mm", "1.0"])
    assert code == 1
    assert not out_pitch.exists()


def test_h12_non_integer_period_keeps_period_path():
    """H12 (лид, живой стенд 2026-09-23): период звена в пикселях сцены почти никогда не целый —
    25.4 мм × 0.6 px/мм = 15.24 px. Автокорреляция находит целые 15, и обрезка «целым числом
    найденных периодов» (10 × 15 = 150 px) копит сдвиг фазы на шве 10 × 0.24 = 2.4 px: шов хуже
    внутреннего перехода, инструмент откатывался в зеркало. На синтетическом «фото ленты» со
    стенда так и было (`period_px=15`, шов 33.83 > внутри 31.76 → mirror). Второе лицо того же
    дефекта — в этой фикстуре: шум поднимает `inner_diff` (это МАКСИМУМ внутренних шагов), и
    наивная обрезка 150 px проходит проверку шва (37.3 ≤ 39.25) с рывком фазы 2.4 px на шве —
    проверка шва его не видит. Поэтому тест ловит сдвиг фазы ширины тайла, а не шов."""
    true_period = 15.24  # 25.4 мм * 0.6 px/мм — литерал, не из кода
    width, height = 156, 40
    x = np.arange(width)
    hinge = 70.0 + 35.0 * (np.cos(2 * np.pi * x / true_period) > 0.85)
    rng = np.random.default_rng(3)
    plane = np.clip(hinge[None, :] + rng.normal(0, 6, (height, width)), 0, 255).astype(np.uint8)
    image = np.repeat(plane[:, :, None], 3, axis=2)

    result = make_seamless_tile(image)

    assert result.method == "period", result.note
    inner_diff, seam_diff = _recompute_inner_and_seam(result.tile)
    assert seam_diff <= inner_diff
    tile_w = result.tile.shape[1]
    phase_err = abs(tile_w - round(tile_w / true_period) * true_period)
    assert phase_err <= 0.5, f"ширина тайла {tile_w} не кратна истинному периоду: сдвиг фазы {phase_err:.2f} px"


def test_h13_tile_not_narrower_than_half_photo():
    """H13 (лид): при нескольких точных повторах тайл берётся не уже половины фото — иначе фактура
    ленты (пятна, износ) повторяется в кадре через каждые пару звеньев. Фикстура без шума с
    периодом ровно 61/3 px: рисунок точно повторяется через 61 px, а в окне одного периода
    бинарный рисунок совпадает и на других ширинах (замер: без границы выбирается 41, с ней —
    102 = 5 × 20.33, сдвиг 0.33 px). Проверяется само свойство «не уже половины», не ширина."""
    width, height = 150, 20
    x = np.arange(width)
    hinge = 70.0 + 35.0 * (np.cos(2 * np.pi * x / (61 / 3)) > 0.85)
    image = np.repeat(np.repeat(hinge[None, :], height, axis=0)[:, :, None], 3, axis=2).astype(np.uint8)

    result = make_seamless_tile(image)

    assert result.method == "period", result.note
    assert result.tile.shape[1] >= (width + 1) // 2  # 75


def test_h14_pitch_mode_prints_source_period_and_links(tmp_path, capsys):
    """H14 (ревью 2026-09-23): при `--pitch-mm` `period_px` после масштаба равен `S·M` по
    построению и гармонику не покажет — двойной/половинный шаг звена виден только по периоду на
    исходнике и числу звеньев на фото. Пила 16 px × 3.5 периода: `source_period_px=16`,
    `links_in_photo=3.50`, и путь «период», а не зеркало."""
    from Services.line_sim.tools import make_seamless_texture as tool

    image = np.zeros((8, 56, 3), dtype=np.uint8)
    for x in range(56):
        image[:, x, :] = int(255 * (x % 16) / 16)
    src, out = tmp_path / "saw.png", tmp_path / "tile.png"
    imwrite_unicode(src, image)

    assert tool.main([str(src), "--out", str(out), "--pitch-mm", "60", "--scene-px-per-mm", "2"]) == 0
    text = capsys.readouterr().out
    assert " source_period_px=16 " in text
    assert " links_in_photo=3.50" in text
    assert "method=period " in text, text


def test_h15_short_photo_margin_does_not_force_bad_width():
    """H15 (ревью 2026-09-23, итерация 2): на коротком фото отступ от края съедал допустимые
    ширины — при W = 51, P ≈ 15.1 и отступе 8 ширина ограничена 28 px (1.85 звена, сдвиг фазы
    2.2 px), хотя 30 px (2 звена, сдвиг 0.2) помещается от самого края. Начало тайла и ширина
    ищутся совместно, отступ — не обязанность, а разрешение."""
    true_period = 15.1  # 2 × 15.1 = 30.2 — два звена почти целые, литерал
    width, height = 51, 20
    x = np.arange(width)
    hinge = 70.0 + 35.0 * (np.cos(2 * np.pi * x / true_period) > 0.85)
    image = np.repeat(np.repeat(hinge[None, :], height, axis=0)[:, :, None], 3, axis=2).astype(np.uint8)

    result = make_seamless_tile(image)

    assert result.method == "period", result.note
    tile_w = result.tile.shape[1]
    phase_err = abs(tile_w - round(tile_w / true_period) * true_period)
    assert phase_err <= 0.5, f"ширина {tile_w}: сдвиг фазы {phase_err:.2f} px"
