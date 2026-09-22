# -*- coding: utf-8 -*-
"""Независимые acceptance-тесты Task 3.6 — фон-текстура ленты (`SceneCompositor` +
`Services/line_sim/tools/make_seamless_texture.py`), написаны ДО реализации.

Источник контракта: `plans/line-sim/phase-3-object-engine.md`, раздел
"### Task 3.6 (новая, 2026-09-23)" вплоть до блока "**Уточнено лидом 2026-09-23 перед
тестером (контракт; отменяет расходящиеся строки выше)**" — этот блок ЯВНО отменяет
расходящиеся более ранние строки того же раздела (путь текстуры — ключ конфига плагина
`background_texture`, НЕ поле `ScenePreset`; кросс-фейда у зеркальной склейки нет) и
является источником истины для сигнатур ниже. Критерии — 7 исходных чекбоксов раздела +
2 из подраздела "Критерии в дополнение".

Рабочее дерево — git worktree на коммите 27b1800f ("docs(plans): line-sim 3.6 — контракт
фона-текстуры до тестера"), ДО имплементации Task 3.6: реализация `background_tile` в
`SceneCompositor` и модуль `make_seamless_texture.py` в этом дереве НЕ СУЩЕСТВУЮТ по
конструкции (RED enforced деревом, не только прозой).

ЗАПРЕЩЁННЫЕ ПУТИ (не читались, потому что их нет в этом дереве / не относятся к тестеру):
любой diff/реализация Task 3.6 (её физически нет в этом коммите); чужие тесты автора не
существуют. Прочитано как ГОТОВАЯ ЗАВИСИМОСТЬ (не то, что тестируется здесь): раздел плана
Task 3.6, `Services/line_sim/core/scene_compositor.py` (Task 3.4, ДО добавления
`background_tile`), `Services/line_sim/core/belt.py`, `Services/robot_comm/core/registers.py`
(`FACTOR_MM`), `Services/dataset_gen/core/catalog.py` (`imread_unicode`/`imwrite_unicode`),
`Services/line_sim/tests/test_acceptance_3_4.py` (паттерн fixture-каталога/спавнера).

СИГНАТУРЫ, ПРЕДПОЛАГАЕМЫЕ (ещё не реализованы — источник: блок "Уточнено лидом"), сверить
при имплементации:
  - `SceneCompositor(spawner, px_per_mm, belt_y_px, background_bgr=(60, 60, 60),
     background_tile: np.ndarray | None = None)`. `background_tile` — RGB uint8
    `(th, tw, 3)`, `th >= 1`, `tw >= 1`.
  - По X: `shift_px = round(encoder_to_offset_mm(now_encoder, 0.0) * px_per_mm)`; столбец
    кадра `u` показывает столбец тайла `(u + round(x_px) - shift_px) mod tw`. Тайл не
    растягивается — уже кадра значит повторение.
  - По Y: `top = round(belt_y_px - th / 2)`; строка кадра `v` показывает строку тайла
    `v + round(y_px) - top`, если она в `[0, th)`, иначе — `background_bgr` (в RGB).
  - `Services.line_sim.tools.make_seamless_texture.make_seamless_tile(image) ->
     SeamlessResult(tile, method, period_px, seam_diff, inner_diff)`, `method` in
     {"period", "mirror"}. `main(argv: list[str] | None) -> int`.
  - `step(a, b) = mean(|a.astype(float) - b.astype(float)|)` по строкам и каналам;
    `inner_diff = max по u in [0, tw-2] step(tile[:,u], tile[:,u+1])`,
    `seam_diff = step(tile[:,tw-1], tile[:,0])` — тест пересчитывает эти величины САМ по
    возвращённому `tile`, числам инструмента не доверяет (инструкция ведущего).

ДОГАДКИ ТЕСТЕРА и неоднозначности контракта — см. итоговый отчёт
`docs/reviews/2026-09-23_task-3.6-tester.md`.
"""

from __future__ import annotations

import re
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

pytestmark = pytest.mark.timeout(30)


# --------------------------------------------------------------------------------------
# Fixture-хелперы (скопированы из test_acceptance_3_4.py — готовая зависимость, не то,
# что тестируется здесь; не тестируют ничего сами)
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
    """Ровно один объект с `passport.spawn_encoder == spawn_encoder` (см. докстринг
    `ObjectSpawner.tick`: первый `tick()` только взводит срок в режиме `interval_s`,
    второй — спавнит с `spawn_encoder = now_encoder` ЭТОГО тика)."""
    rng = np.random.default_rng(seed)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=0.0, rng=rng)
    spawner.tick(now_encoder=spawn_encoder, now_wall_s=2000.0, rng=rng)
    objs = spawner.active_objects()
    assert len(objs) == 1, "setup sanity: ожидался ровно один заспавненный объект"
    return objs[0]


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
# SceneCompositor + background_tile
# --------------------------------------------------------------------------------------


def test_background_moves_with_object(tmp_path):
    """Критерий 1: фон едет с объектом — при росте энкодера столбец текстуры, стоящий
    под центром объекта, тот же (объект не «скользит» по ленте). Тайл кодирует индекс
    столбца прямо в R-канале, чтобы читать позицию текстуры без интерполяции."""
    tw, th = 50, 60
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = u  # tw=50 < 256 -> индекс столбца кодируется без переполнения uint8

    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))
    obj = _spawn_one_at(spawner, spawn_encoder=0.0)
    belt_y_px = 100.0
    compositor = SceneCompositor(
        spawner, px_per_mm=1.0, belt_y_px=belt_y_px, background_bgr=(60, 60, 60), background_tile=tile
    )

    # полоса тайла: top = round(100 - 60/2) = 70 -> строки [70, 130); спрайт объекта
    # (16x16, cy=belt_y_px=100) занимает по вертикали [92, 108) -> строка 75 внутри полосы,
    # но заведомо вне спрайта — читаем чистый фон, даже если столбец совпадёт с объектом.
    read_row = 75

    # три значения энкодера; ни одно не близко к границе округления .5 (FACTOR_MM=0.144473,
    # проверено вручную: 0*F=0.0, 500*F=72.2365, 1300*F=187.8149 — ни одно не оканчивается на
    # X.5, банковское округление round() тут не создаёт неоднозначности)
    for now_encoder in (0.0, 500.0, 1300.0):
        cx = encoder_to_offset_mm(now_encoder, obj.passport.spawn_encoder) * 1.0 - 0.0
        u = round(cx)
        frame, _passports = compositor.render(now_encoder=now_encoder, camera_rect=(0.0, 0.0, 300.0, 200.0))
        tile_col = int(frame[read_row, u, 0])
        # spawn_encoder=0.0 и x_px=0.0 -> ожидаемый столбец тайла ~0 на ЛЮБОМ now_encoder
        # (тот же множитель `encoder_to_offset_mm(...)*px_per_mm`, что и у сдвига фона) —
        # допуск ±1 px с учётом цикличности (mod tw)
        diff = min(tile_col % tw, (tw - tile_col) % tw)
        assert diff <= 1, f"encoder={now_encoder}: ожидался столбец тайла ~0, получен {tile_col}"


def test_background_shift_is_cyclic(tmp_path):
    """Критерий 2: сдвиг фона цикличен — `offset_px == tile_width` даёт кадр, попиксельно
    равный `offset_px == 0` (без объектов — сравнение кадров должно быть чистым)."""
    tw, th = 50, 40
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = (u * 5) % 256  # неоднородный узор по столбцам (не константа)

    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))  # spawner.tick() ни разу не звался -> пусто
    compositor = SceneCompositor(
        spawner, px_per_mm=1.0, belt_y_px=50.0, background_bgr=(60, 60, 60), background_tile=tile
    )

    now_encoder_zero_shift = 0.0
    now_encoder_full_shift = tw / FACTOR_MM  # ровно один оборот тайла: shift_px == tw

    frame_zero, passports_zero = compositor.render(
        now_encoder=now_encoder_zero_shift, camera_rect=(0.0, 0.0, 200.0, 100.0)
    )
    frame_full, passports_full = compositor.render(
        now_encoder=now_encoder_full_shift, camera_rect=(0.0, 0.0, 200.0, 100.0)
    )

    assert passports_zero == [] and passports_full == []
    assert np.array_equal(frame_zero, frame_full)


def test_narrow_tile_fills_frame_without_stretch(tmp_path):
    """Критерий 3: тайл (200 px) уже кадра (640 px) — кадр заполнен целиком повторением
    тайла, без чёрных полей и БЕЗ растягивания. Проверка литеральная: каждый столбец
    строки сравнивается с ожидаемым `u mod tw`."""
    tw, th = 200, 40
    tile = np.zeros((th, tw, 3), dtype=np.uint8)
    for u in range(tw):
        tile[:, u, 0] = u  # tw=200 < 256 -> прямое кодирование индекса в R без переполнения

    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))  # пустой спавнер
    belt_y_px = 50.0
    compositor = SceneCompositor(
        spawner, px_per_mm=1.0, belt_y_px=belt_y_px, background_bgr=(60, 60, 60), background_tile=tile
    )

    frame_w, frame_h = 640, 100
    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, float(frame_w), float(frame_h)))

    assert passports == []
    # top тайла = round(50 - 40/2) = 30 -> строка 35 внутри полосы [30, 70)
    read_row = 35
    expected_row = np.zeros((frame_w, 3), dtype=np.uint8)
    for u in range(frame_w):
        expected_row[u, 0] = u % tw  # shift_px=0 (now_encoder=0.0) -> tile_col = u mod tw
    assert np.array_equal(frame[read_row], expected_row)


def test_any_image_is_valid_background(tmp_path):
    """Критерий 7: любая читаемая картинка — валидный фон (однотонная с диагональю, НЕ
    похожая на ленту) — кадр собирается без исключений, содержимое читается литерально."""
    tw, th = 40, 40
    flat = (10, 20, 30)
    tile = np.empty((th, tw, 3), dtype=np.uint8)
    tile[:, :, 0], tile[:, :, 1], tile[:, :, 2] = flat
    diag_marker = (250, 5, 5)
    for i in range(min(tw, th)):
        tile[i, i] = diag_marker

    spawner = _make_spawner(tmp_path, color_bgr=(0, 0, 255))  # пустой спавнер
    belt_y_px = 50.0
    compositor = SceneCompositor(
        spawner, px_per_mm=1.0, belt_y_px=belt_y_px, background_bgr=(60, 60, 60), background_tile=tile
    )

    frame, passports = compositor.render(now_encoder=0.0, camera_rect=(0.0, 0.0, 80.0, 100.0))

    top = round(belt_y_px - th / 2)  # round(50 - 20) = 30, целое -> без banker's-неоднозначности
    assert passports == []
    assert frame.dtype == np.uint8
    diag_i = 5
    assert tuple(int(v) for v in frame[top + diag_i, diag_i]) == diag_marker
    off_diag_col = diag_i + 1
    assert tuple(int(v) for v in frame[top + diag_i, off_diag_col]) == flat


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
    match = re.search(r"period_px=(\d+)", stdout_text)
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
