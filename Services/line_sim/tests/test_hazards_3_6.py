# -*- coding: utf-8 -*-
"""Hazard-тесты автора для Task 3.6 (фон-текстура `SceneCompositor` + инструмент
`make_seamless_texture.py`) — что может сломаться в ЭТОМ механизме, а не в общей
приёмке. Тестерский набор (`test_acceptance_3_6.py`) гоняет всё на `px_per_mm=1.0` и
`spawn_encoder=0.0`, что маскирует ошибку «забыли умножить сдвиг фона на px_per_mm»
(H1) — оба параметра совпадают с идентичным множителем 1.0. Остальные — форма/dtype
входа компоновщика (H2), нечётная геометрия тайла (H3), регресс поведения без тайла
(H4), большие значения энкодера (H5), и два случая инструмента, где «выбрать метод
молча» было бы дефектом (H6, H7).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim import (
    FACTOR_MM,
    ObjectFactory,
    ObjectSpawner,
    SceneCompositor,
    ScenePreset,
    encoder_to_offset_mm,
)
from Services.line_sim.tools.make_seamless_texture import make_seamless_tile

pytestmark = pytest.mark.timeout(30)


# --------------------------------------------------------------------------------------
# Fixture-хелперы (тот же паттерн, что в test_acceptance_3_6.py — не тестируют ничего сами)
# --------------------------------------------------------------------------------------


def _make_fixture_catalog(tmp_path: Path, color_bgr: tuple[int, int, int]) -> Path:
    classes_dir = tmp_path / "classes"
    class_dir = classes_dir / "square"
    class_dir.mkdir(parents=True)
    b, g, r = color_bgr
    sprite_bgra = np.zeros((16, 16, 4), dtype=np.uint8)
    sprite_bgra[:, :, 0] = b
    sprite_bgra[:, :, 1] = g
    sprite_bgra[:, :, 2] = r
    sprite_bgra[:, :, 3] = 255
    imwrite_unicode(class_dir / "sprite.png", sprite_bgra)
    return classes_dir


def _make_spawner(tmp_path: Path, color_bgr: tuple[int, int, int], **spawner_kwargs) -> ObjectSpawner:
    classes_dir = _make_fixture_catalog(tmp_path, color_bgr)
    preset = ScenePreset(catalog_dir=str(classes_dir), angle_range_deg=(0.0, 0.0), defect_probability=0.0)
    factory = ObjectFactory(preset)
    kwargs = {"interval_s": (1000.0, 1000.0), "scene_length_mm": 1_000_000.0, "max_active": 200}
    kwargs.update(spawner_kwargs)
    return ObjectSpawner(factory, **kwargs)


def _spawn_one_at(spawner: ObjectSpawner, spawn_encoder: float, seed: int = 0):
    rng = np.random.default_rng(seed)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=2000.0, rng=rng)
    objs = spawner.active_objects()
    assert len(objs) == 1, "setup sanity: ожидался ровно один заспавненный объект"
    return objs[0]


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


def test_h1_background_follows_object_at_nonzero_encoder_and_stand_px_per_mm(tmp_path):
    """H1: тестерский набор гоняет всё на `px_per_mm=1.0` и объекте со `spawn_encoder=0.0`
    — там множитель `px_per_mm` неотличим от 1 и совпадает со сдвигом фона по
    совпадению. Здесь `px_per_mm=0.6` (реальное значение стенда, `make_demo_catalog.py`)
    и объект заспавнен на НЕНУЛЕВОМ энкодере: если реализация забыла умножить сдвиг фона
    на `px_per_mm` (использует голый `encoder_to_offset_mm(now_encoder, 0.0)` без
    множителя), координата тайла под центром объекта поедет с ростом энкодера вместо
    того, чтобы стоять на месте — именно то, из-за чего задача существует («по льду»)."""
    px_per_mm = 0.6
    tw, th = 200, 60
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = u  # tw=200 < 256 -> прямое кодирование индекса столбца

    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    spawn_encoder = 700.0
    obj = _spawn_one_at(spawner, spawn_encoder=spawn_encoder)
    belt_y_px = 100.0
    compositor = SceneCompositor(
        spawner, px_per_mm=px_per_mm, belt_y_px=belt_y_px, background_bgr=(60, 60, 60), background_tile=tile
    )
    # top = round(100 - 60/2) = 70 -> полоса [70,130); спрайт 16x16 при cy=100 занимает
    # [92,108) -> строка 75 внутри полосы, но заведомо вне спрайта.
    read_row = 75

    columns: list[int] = []
    for now_encoder in (700.0, 1200.0, 2100.0):
        cx = encoder_to_offset_mm(now_encoder, obj.passport.spawn_encoder) * px_per_mm
        u = int(round(cx))
        frame, _passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 400.0, 200.0))
        columns.append(int(frame[read_row, u, 0]))

    base = columns[0]
    for c in columns[1:]:
        diff = min(abs(c - base) % tw, tw - (abs(c - base) % tw))
        assert diff <= 1, f"столбец тайла под объектом уехал при росте энкодера: {columns}"


# --------------------------------------------------------------------------------------
# H2 — валидация формы/dtype background_tile
# --------------------------------------------------------------------------------------


def test_h2_bad_background_tile_shapes_raise_value_error(tmp_path):
    """H2: `SceneCompositor` обязан отвергать невалидный `background_tile` в
    конструкторе (`ValueError`), а не дать ему проползти в `render()` и там упасть на
    непредвиденной форме массива (или тихо дать мусор в кадре)."""
    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    kwargs = dict(px_per_mm=1.0, belt_y_px=10.0, background_bgr=(60, 60, 60))

    grey_2d = np.zeros((10, 10), dtype=np.uint8)
    with pytest.raises(ValueError):
        SceneCompositor(spawner, background_tile=grey_2d, **kwargs)

    rgba_4ch = np.zeros((10, 10, 4), dtype=np.uint8)
    with pytest.raises(ValueError):
        SceneCompositor(spawner, background_tile=rgba_4ch, **kwargs)

    float32_tile = np.zeros((10, 10, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        SceneCompositor(spawner, background_tile=float32_tile, **kwargs)

    zero_width = np.zeros((10, 0, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        SceneCompositor(spawner, background_tile=zero_width, **kwargs)


# --------------------------------------------------------------------------------------
# H3 — нечётная высота тайла + нецелые belt_y_px/y_px
# --------------------------------------------------------------------------------------


def test_h3_odd_tile_height_noninteger_belt_y_and_y_px(tmp_path):
    """H3: нечётная высота тайла (`round(th/2)` не тривиален) и нецелые `belt_y_px`/
    `y_px` — граница полосы (`top`) обязана считаться строго по формуле контракта
    (`round(belt_y_px - th/2)`), а строки вне полосы — РОВНО фоновым цветом в RGB, не
    приблизительно."""
    tw, th = 20, 41  # нечётная высота
    tile = np.full((th, tw, 3), fill_value=200, dtype=np.uint8)  # заведомо не равно фону
    background_bgr = (60, 61, 62)

    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    belt_y_px = 50.7
    compositor = SceneCompositor(
        spawner, px_per_mm=1.0, belt_y_px=belt_y_px, background_bgr=background_bgr, background_tile=tile
    )
    y_px = 3.4
    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, y_px, 30.0, 100.0))
    assert passports == []

    top = round(belt_y_px - th / 2)
    b, g, r = background_bgr
    for v in range(100):
        row_in_tile = v + round(y_px) - top
        if 0 <= row_in_tile < th:
            assert frame[v, 0, 0] == 200, f"строка {v} должна быть тайлом (row_in_tile={row_in_tile})"
        else:
            assert tuple(int(c) for c in frame[v, 0]) == (r, g, b), f"строка {v} должна быть фоном"


# --------------------------------------------------------------------------------------
# H4 — background_tile=None не меняет поведение 3.4
# --------------------------------------------------------------------------------------


def test_h4_background_tile_none_matches_3_4_solid_fill(tmp_path):
    """H4: `background_tile=None` обязан давать РОВНО то же поведение, что было до
    Task 3.6 (сплошная заливка `background_bgr`) — побитовое сравнение кадров с явно
    переданным `None` и с дефолтом конструктора."""
    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    background_bgr = (11, 22, 33)
    compositor_explicit_none = SceneCompositor(
        spawner, px_per_mm=1.0, belt_y_px=20.0, background_bgr=background_bgr, background_tile=None
    )
    compositor_default = SceneCompositor(spawner, px_per_mm=1.0, belt_y_px=20.0, background_bgr=background_bgr)

    frame_a, passports_a = compositor_explicit_none.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 40.0, 40.0))
    frame_b, passports_b = compositor_default.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 40.0, 40.0))

    assert passports_a == passports_b == []
    assert np.array_equal(frame_a, frame_b)
    b, g, r = background_bgr
    assert np.all(frame_a[:, :, 0] == r) and np.all(frame_a[:, :, 1] == g) and np.all(frame_a[:, :, 2] == b)


# --------------------------------------------------------------------------------------
# H5 — очень большой энкодер, цикличность на масштабе 1e9
# --------------------------------------------------------------------------------------


def test_h5_very_large_encoder_no_exception_and_cyclic(tmp_path):
    """H5: энкодер порядка 1e9 (реалистичный счётчик к концу смены) не должен ронять
    `render()` и цикличность сдвига обязана держаться и на таких величинах, не только
    около нуля — используются взаимно простые `tw`/шаг узора, чтобы ошибка округления
    не спряталась за случайным совпадением."""
    tw, th = 37, 20
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = (u * 3) % 256

    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    compositor = SceneCompositor(
        spawner, px_per_mm=1.0, belt_y_px=15.0, background_bgr=(60, 60, 60), background_tile=tile
    )

    big_encoder = 1e9
    shifted_encoder = big_encoder + tw / FACTOR_MM  # сдвиг ровно на одну ширину тайла

    frame_big, passports_big = compositor.render(now_encoder=big_encoder, camera_rect=(0.0, 0.0, 80.0, 40.0))
    frame_shifted, passports_shifted = compositor.render(
        now_encoder=shifted_encoder, camera_rect=(0.0, 0.0, 80.0, 40.0)
    )

    assert passports_big == [] and passports_shifted == []
    assert np.array_equal(frame_big, frame_shifted)


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


def test_h10_camera_rect_x_offset_shifts_tile_columns(tmp_path):
    """H10: `x_px` (первая компонента `camera_rect`) обязана входить в формулу сдвига
    тайла (`cols = (arange(w) + round(x_px) - shift_px) % tw`). Ни один тест тестера
    и ни один из H1-H7 не задаёт для фона `camera_rect` с `x_px != 0` — все камеры
    выше начинались от `(0.0, ...)`. Инъекция `cols = (np.arange(w) - shift_px) % tw`
    (x_px молча выпал из формулы) осталась бы зелёной на всём прежнем наборе.
    Найдено break-injection'ом лида (2026-09-23)."""
    tw, th = 100, 30
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = u  # tw=100 < 256 -> прямое кодирование индекса столбца

    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))  # пустой спавнер
    belt_y_px = 20.0
    compositor = SceneCompositor(
        spawner, px_per_mm=1.0, belt_y_px=belt_y_px, background_bgr=(60, 60, 60), background_tile=tile
    )
    # top = round(20 - 15) = 5 -> полоса [5, 35); read_row=10 -> row_in_tile=5, внутри полосы
    read_row = 10

    for x_px in (7.0, 12.4):  # целое ненулевое и нецелое значение
        w, h = 60, 40
        frame, passports = compositor.render(now_encoder=0.0, camera_rect=(x_px, 0.0, float(w), float(h)))
        assert passports == []
        shift_px = 0  # now_encoder=0.0 -> encoder_to_offset_mm(0, 0) == 0
        for u in (0, 1, w - 1):
            expected_col = (u + round(x_px) - shift_px) % tw
            assert frame[read_row, u, 0] == expected_col, f"x_px={x_px}, u={u}: столбец тайла не учитывает x_px"


def test_h11_background_tile_stored_as_copy_not_reference(tmp_path):
    """H11: конструктор обязан хранить КОПИЮ `background_tile`, не ссылку на массив
    вызывающего — иначе мутация массива после создания `SceneCompositor` (например,
    вызывающий переиспользует буфер для следующего кадра) незаметно меняет уже
    построенную сцену. Инъекция `return tile.copy()` -> `return tile` в
    `_validate_background_tile` осталась бы зелёной на всём прежнем наборе (ни один
    тест не мутирует исходный массив после конструктора). Найдено break-injection'ом
    лида (2026-09-23)."""
    tw, th = 10, 10
    tile = np.full((th, tw, 3), fill_value=50, dtype=np.uint8)

    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))  # пустой спавнер
    compositor = SceneCompositor(
        spawner, px_per_mm=1.0, belt_y_px=5.0, background_bgr=(60, 60, 60), background_tile=tile
    )

    tile[:, :, :] = 200  # мутация массива вызывающего ПОСЛЕ конструктора

    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 10.0, 10.0))
    assert passports == []
    # top = round(5 - 10/2) = 0 -> вся полоса покрывает весь кадр (h=10)
    assert np.all(frame == 50), "мутация исходного массива после конструктора протекла в рендер"


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
