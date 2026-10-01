# -*- coding: utf-8 -*-
"""Независимые acceptance-тесты Task 1.2 плана layer-render — опция `--gap-alpha` у
`Services/line_sim/tools/make_seamless_texture.py`; написаны ДО реализации, ожидаемо КРАСНЫЕ.

Источник контракта: только `plans/layer-render/phase-1.md`, раздел "Task 1.2" (Goal / DESIGN /
Acceptance) + рамка `plan.md`. Рабочее дерево — git worktree на коммите плана (03d90836), реализации
опции в нём нет по построению.

ЗАПРЕЩЁННЫЕ ПУТИ (не читались): `.claude/worktrees/layer-render` и любая другая ветка/worktree с
реализацией Task 1.2; чужие тесты автора. Прочитано как готовая зависимость: текущий
`make_seamless_texture.py` (CLI-паттерн `main(argv)`, строка stdout `period_px=...`), его существующие
тесты (стиль). Реальный ассет данных (`data/line_sim/belt_photo_full.png`) читался только в роли
входа инструмента и для замера цветов (не для вывода порогов: пороги тестов — явные CLI-флаги).

Что фиксируют тесты (пороги синтетики задаются ЯВНЫМИ флагами `--gap-hue/--gap-sat-min/--rails-px`:
дефолты по плану измеряет разработчик на реальном фото, тестер их не знает):
  - без опции выход не меняется (sha-голден снят ДО реализации; зелёный сегодня — это защита);
  - с опцией RGB побайтно тот же, альфа бинарная uint8, просветы 0 / звенья 255 / борта 255;
  - просвет определяется конъюнкцией «тон в [LO,HI] И насыщенность >= SAT_MIN» (по отдельному
    двойнику на каждое условие), а не яркостью (V мяты 79 против звеньев 78);
  - борта `--rails-px TOP,BOTTOM` всегда 255 (верх/низ не перепутаны), вне зоны борт — по HSV;
  - периодичность альфы: столбцы x и x+P совпадают;
  - кривые значения порогов -> SystemExit, в сообщении об ошибке — имя именно того флага.

ДОГАДКИ ТЕСТЕРА (контракт молчит — см. отчёт):
  - границы `--gap-hue` и `--gap-sat-min` включительные (LO==HI допустим);
  - альфа на выходе CLI — 4-й канал PNG (cv2.IMREAD_UNCHANGED -> BGRA);
  - `gap_alpha_mask(tile_rgb, ...)` возвращает 2D `uint8 (h, w)` и не мутирует вход.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode
from Services.line_sim.tools import make_seamless_texture as tool

# ── синтетический «снимок ленты» ──────────────────────────────────────────────────────────
# Цвета заданы в HSV OpenCV (H 0..179, S/V 0..255) и переведены в BGR cv2 — независимо от кода под тестом.
_P = 40  # период звеньев, px (целый: find_period отдаёт целый лаг)
_PERIODS = 10  # фото = 10 периодов в ширину
_H = 96
_RAIL = 15  # строк борта сверху и снизу
_TOL = 4  # допуск отнесения пикселя к классу (шум ±2 + округление)

_HSV = {
    "link": (105, 22, 78),  # серое звено: S низкая, V=78
    "mint": (72, 70, 79),  # мятный просвет: V=79 (по яркости от звена неотличим), S выше звена
    "rail": (70, 100, 190),  # зелёный борт: тон ВНУТРИ диапазона просвета, S>=SAT_MIN -> спасает только зона бортов
    "glare": (72, 12, 110),  # блик на звене: тон в диапазоне, S низкая, V=110 -> не просвет (условие по S)
    "offhue": (18, 70, 79),  # насыщенное пятно вне диапазона тона -> не просвет (условие по тону)
}
_GAP_HUE = "55,95"
_GAP_SAT = "45"
_RAILS = "15,15"


def _bgr(name: str) -> np.ndarray:
    px = cv2.cvtColor(np.uint8([[_HSV[name]]]), cv2.COLOR_HSV2BGR)
    return px[0, 0].astype(int)


def _photo(noise: bool = True) -> np.ndarray:
    """BGR uint8 (96, 400, 3): борта 15 строк; середина — мята; в каждом периоде звено 28x52
    (строки 22..73, столбцы k*P+4..k*P+31) с бликом (30..37, k*P+8..15) и «тёплым» пятном (50..57, k*P+8..15)."""
    img = np.zeros((_H, _P * _PERIODS, 3), np.int32)
    img[:] = _bgr("mint")
    img[:_RAIL] = _bgr("rail")
    img[_H - _RAIL :] = _bgr("rail")
    for k in range(_PERIODS):
        x0 = k * _P
        img[22:74, x0 + 4 : x0 + 32] = _bgr("link")
        img[30:38, x0 + 8 : x0 + 16] = _bgr("glare")
        img[50:58, x0 + 8 : x0 + 16] = _bgr("offhue")
    if noise:  # детерминированный разнотонный шум ±2 по каналам, без RNG
        y, x, c = np.mgrid[0:_H, 0 : _P * _PERIODS, 0:3]
        img = img + ((x * 7 + y * 13 + c * 3) % 5 - 2)
    return np.clip(img, 0, 255).astype(np.uint8)


def _run(tmp_path: Path, capsys, photo: np.ndarray, *extra: str, name: str = "tile.png"):
    src = tmp_path / "photo.png"
    out = tmp_path / name
    imwrite_unicode(str(src), photo)
    rc = tool.main([str(src), "--out", str(out), *extra])
    stdout = capsys.readouterr().out
    return rc, stdout, out


def _sub(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    return d


def _read(path: Path) -> np.ndarray:
    img = imread_unicode(str(path), cv2.IMREAD_UNCHANGED)
    assert img is not None, f"выход не читается: {path}"
    return img


def _run_ok(tmp_path, capsys, photo, *extra, name="tile.png"):
    """Прогон, который обязан завершиться кодом 0. SystemExit (argparse: опция неизвестна) -> AssertionError."""
    try:
        rc, stdout, out = _run(tmp_path, capsys, photo, *extra, name=name)
    except SystemExit as exc:
        pytest.fail(f"main({extra}) завершился SystemExit({exc.code!r}), ждали код 0")
    assert rc == 0, f"main({extra}) вернул {rc}, ждали 0"
    return stdout, out


def _gap_run(tmp_path, capsys, *extra, photo=None, hue=_GAP_HUE, sat=_GAP_SAT, rails=_RAILS):
    """Прогон с --gap-alpha и явными порогами; возвращает (stdout, rgb, alpha)."""
    flags = ["--gap-alpha", f"--gap-hue={hue}", f"--gap-sat-min={sat}", f"--rails-px={rails}", *extra]
    stdout, out = _run_ok(tmp_path, capsys, _photo() if photo is None else photo, *flags)
    img = _read(out)
    assert img.ndim == 3 and img.shape[2] == 4, f"ждали RGBA-PNG (h, w, 4), получили {img.shape}"
    return stdout, img[:, :, :3], img[:, :, 3]


def _classes(rgb_bgr: np.ndarray) -> dict[str, np.ndarray]:
    """Маски классов пикселей тайла по близости к базовым цветам (истина берётся из самого тайла)."""
    return {
        n: (np.abs(rgb_bgr.astype(int) - _bgr(n)).max(axis=2) <= _TOL)
        for n in ("link", "mint", "rail", "glare", "offhue")
    }


# ── 1. без опции — выход не меняется ──────────────────────────────────────────────────────
# Литералы сняты ДО реализации опции (текущим инструментом, фото `_photo()`).
_GOLDEN_PIXELS_SHA256 = "f83d00a91f9604b96731f77abfb93774650da984608b86a6e2eae33a900801df"
_GOLDEN_PNG_SHA256 = "7f5114c9525136f59aa91561bdc5b32bb54e5721e98494f0a70004e2742602a0"
_GOLDEN_SIZE = (_H, 200, 3)  # (h, w, ch) снято до реализации


def test_off_decoded_pixels_equal_pre_task_golden(tmp_path, capsys):
    """Критерий 1 (пиксели): без `--gap-alpha` выход 3-канальный, пиксели == голдену. ЗЕЛЁНЫЙ сегодня."""
    rc, _, out = _run(tmp_path, capsys, _photo())
    assert rc == 0
    img = _read(out)
    assert img.shape == _GOLDEN_SIZE, f"форма {img.shape}, ждали {_GOLDEN_SIZE}"
    assert hashlib.sha256(np.ascontiguousarray(img).tobytes()).hexdigest() == _GOLDEN_PIXELS_SHA256


def test_off_png_bytes_equal_pre_task_golden(tmp_path, capsys):
    """Критерий 1 (байты PNG, как в плане: sha256 файла). ЗЕЛЁНЫЙ сегодня. Хрупок к версии zlib/libpng."""
    _, _, out = _run(tmp_path, capsys, _photo())
    assert hashlib.sha256(out.read_bytes()).hexdigest() == _GOLDEN_PNG_SHA256


# ── 2. с опцией: RGB побайтно тот же, формат RGBA ────────────────────────────────────────
def test_on_rgb_is_bytewise_equal_to_tile_without_option(tmp_path, capsys):
    """Критерий 2: `out[:, :, :3]` побайтно равен тайлу без опции — опция добавляет только альфу."""
    _, _, out_plain = _run(_sub(tmp_path, "a"), capsys, _photo())
    plain = _read(out_plain)
    _, rgb, alpha = _gap_run(_sub(tmp_path, "b"), capsys)
    assert plain.shape[:2] == alpha.shape, f"форма альфы {alpha.shape} != форме тайла {plain.shape[:2]}"
    assert np.array_equal(rgb, plain), f"RGB изменился: различается {int((rgb != plain).any(axis=2).sum())} пикселей"


def test_on_alpha_is_binary_uint8(tmp_path, capsys):
    """DESIGN: маска бинарная, сглаживания края нет -> альфа uint8, значения только {0, 255}, и оба значения есть."""
    _, _, alpha = _gap_run(tmp_path, capsys)
    assert alpha.dtype == np.uint8
    assert set(np.unique(alpha).tolist()) == {0, 255}, f"значения альфы: {np.unique(alpha).tolist()}"


# ── 3. синтетика: просветы 0 / звенья 255 / борта 255 ─────────────────────────────────────
def test_fixture_gap_is_not_separable_from_links_by_brightness(tmp_path, capsys):
    """Страховка фикстуры (не про код): V мяты и звена отличаются <= 2 — яркость не разделяет, как в реальной плитке."""
    _, rgb, _ = _gap_run(tmp_path, capsys)
    v = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV)[:, :, 2].astype(float)
    cls = _classes(rgb)
    assert abs(v[cls["mint"]].mean() - v[cls["link"]].mean()) <= 2.0
    assert cls["mint"].sum() > 5000 and cls["link"].sum() > 5000


def test_gap_pixels_between_rails_get_alpha_zero(tmp_path, capsys):
    """Критерий 3a: альфа 0 у >= 99 % пикселей просвета (мята между бортами)."""
    _, rgb, alpha = _gap_run(tmp_path, capsys)
    m = _classes(rgb)["mint"]
    m[:_RAIL] = False
    m[_H - _RAIL :] = False
    frac = float((alpha[m] == 0).mean())
    assert frac >= 0.99, f"просвет прозрачен у {frac:.4f} пикселей ({int(m.sum())} шт.), нужно >= 0.99"


def test_link_pixels_get_alpha_255(tmp_path, capsys):
    """Критерий 3b: альфа 255 у >= 99 % пикселей звеньев."""
    _, rgb, alpha = _gap_run(tmp_path, capsys)
    m = _classes(rgb)["link"]
    frac = float((alpha[m] == 255).mean())
    assert frac >= 0.99, f"звенья непрозрачны у {frac:.4f} пикселей ({int(m.sum())} шт.), нужно >= 0.99"


def test_rail_rows_all_alpha_255_even_when_hue_sat_match(tmp_path, capsys):
    """Критерий 3c: у 100 % бортов альфа 255, хотя тон и S борта лежат в пороге просвета."""
    _, rgb, alpha = _gap_run(tmp_path, capsys)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV)
    rail_rows = np.r_[0:_RAIL, _H - _RAIL : _H]
    assert ((hsv[rail_rows, :, 0] >= 55) & (hsv[rail_rows, :, 0] <= 95) & (hsv[rail_rows, :, 1] >= 45)).all(), (
        "фикстура: борт обязан попадать под порог тона/насыщенности"
    )
    assert (alpha[rail_rows] == 255).all(), f"не 255 у {int((alpha[rail_rows] != 255).sum())} пикселей бортов"


def test_low_saturation_glare_with_gap_hue_stays_opaque(tmp_path, capsys):
    """Условие насыщенности: блик (тон в диапазоне, S=12 < 45, V=110) остаётся непрозрачным, >= 99 %."""
    _, rgb, alpha = _gap_run(tmp_path, capsys)
    m = _classes(rgb)["glare"]
    frac = float((alpha[m] == 255).mean())
    assert m.sum() > 200 and frac >= 0.99, f"блик непрозрачен у {frac:.4f} из {int(m.sum())}"


def test_saturated_off_hue_patch_stays_opaque(tmp_path, capsys):
    """Условие тона: насыщенное (S=70 >= 45) пятно с тоном 18 вне [55,95] остаётся непрозрачным, >= 99 %."""
    _, rgb, alpha = _gap_run(tmp_path, capsys)
    m = _classes(rgb)["offhue"]
    frac = float((alpha[m] == 255).mean())
    assert m.sum() > 200 and frac >= 0.99, f"пятно непрозрачно у {frac:.4f} из {int(m.sum())}"


# ── 4. границы порогов (бесшумная фикстура: HSV пикселей известен точно) ─────────────────────
def _mint_h_s() -> tuple[int, int]:
    hsv = cv2.cvtColor(np.uint8(_bgr("mint").reshape(1, 1, 3)), cv2.COLOR_BGR2HSV)[0, 0]
    return int(hsv[0]), int(hsv[1])


def _mint_alpha_fraction_zero(tmp_path, capsys, hue: str, sat: str) -> float:
    _, rgb, alpha = _gap_run(tmp_path, capsys, photo=_photo(noise=False), hue=hue, sat=sat)
    m = _classes(rgb)["mint"]
    m[:_RAIL] = False
    m[_H - _RAIL :] = False
    assert m.sum() > 5000
    return float((alpha[m] == 0).mean())


def test_sat_min_is_inclusive_lower_bound(tmp_path, capsys):
    """S пикселя мяты == SAT_MIN -> просвет (>=, как в DESIGN)."""
    _, s0 = _mint_h_s()
    assert _mint_alpha_fraction_zero(tmp_path, capsys, _GAP_HUE, str(s0)) >= 0.99


def test_sat_min_above_pixel_saturation_makes_gap_opaque(tmp_path, capsys):
    """S пикселя мяты < SAT_MIN (на 1) -> уже не просвет."""
    _, s0 = _mint_h_s()
    assert _mint_alpha_fraction_zero(tmp_path, capsys, _GAP_HUE, str(s0 + 1)) <= 0.01


@pytest.mark.parametrize(
    ("shift_lo", "shift_hi", "expect_gap"),
    [(0, 0, True), (1, 9, False), (-9, -1, False)],
    ids=["LO==HI==H_pixel", "range_just_above", "range_just_below"],
)
def test_gap_hue_range_bounds(tmp_path, capsys, shift_lo, shift_hi, expect_gap):
    """Тон пикселя мяты внутри [LO,HI] включительно -> просвет; в соседнем диапазоне — нет (заодно ловит BGR/RGB)."""
    h0, s0 = _mint_h_s()
    frac = _mint_alpha_fraction_zero(tmp_path, capsys, f"{h0 + shift_lo},{h0 + shift_hi}", str(s0))
    assert (frac >= 0.99) if expect_gap else (frac <= 0.01), f"доля прозрачных {frac:.4f}, expect_gap={expect_gap}"


# ── 5. зона бортов --rails-px TOP,BOTTOM ──────────────────────────────────────────────────
def test_rails_zero_zero_makes_green_rails_transparent(tmp_path, capsys):
    """`--rails-px 0,0`: исключений нет -> борт (тон/S в пороге) прозрачен >= 99 %: зона берётся из флага."""
    _, rgb, alpha = _gap_run(tmp_path, capsys, rails="0,0")
    m = _classes(rgb)["rail"]
    frac = float((alpha[m] == 0).mean())
    assert frac >= 0.99, f"борт прозрачен у {frac:.4f} пикселей, ждали >= 0.99"


def test_rails_asymmetric_top_zone_is_forced_opaque(tmp_path, capsys):
    """`--rails-px 20,5`: строки [0,20) — всегда 255, включая мяту в строках 15..19 (она иначе была бы просветом)."""
    _, rgb, alpha = _gap_run(tmp_path, capsys, rails="20,5")
    assert (alpha[:20] == 255).all()
    mint_in_zone = _classes(rgb)["mint"][15:20]
    assert mint_in_zone.sum() > 300, "фикстура: в строках 15..19 должна быть мята"


def test_rails_asymmetric_bottom_zone_is_forced_opaque(tmp_path, capsys):
    """`--rails-px 20,5`: строки [h-5,h) — всегда 255."""
    _, _, alpha = _gap_run(tmp_path, capsys, rails="20,5")
    assert (alpha[_H - 5 :] == 255).all()


def test_rails_asymmetric_does_not_swap_top_and_bottom(tmp_path, capsys):
    """`--rails-px 20,5`: вне зон решает HSV — нижний борт [h-15,h-5) и мята в строках 20..21 прозрачны >= 99 %."""
    _, rgb, alpha = _gap_run(tmp_path, capsys, rails="20,5")
    cls = _classes(rgb)
    lower_rail = cls["rail"][_H - _RAIL : _H - 5]
    upper_mint = cls["mint"][20:22]
    fl = alpha[_H - _RAIL : _H - 5][lower_rail]
    fu = alpha[20:22][upper_mint]
    assert lower_rail.sum() > 1500 and upper_mint.sum() > 300
    assert (fl == 0).mean() >= 0.99, f"нижний борт вне зоны прозрачен у {(fl == 0).mean():.4f}"
    assert (fu == 0).mean() >= 0.99, f"мята вне зоны (строки 20..21) прозрачна у {(fu == 0).mean():.4f}"


# ── 6. периодичность альфы ────────────────────────────────────────────────────────────────
def test_alpha_is_periodic_with_period_px_from_tool_output(tmp_path, capsys):
    """Критерий 4: P = period_px из вывода инструмента; столбцы x и x+P совпадают у >= 99 % строк для ВСЕХ x < P."""
    stdout, _, alpha = _gap_run(tmp_path, capsys)
    m = re.search(r"period_px=(\d+)", stdout)
    assert m, f"фикстура: инструмент не нашёл период (stdout={stdout!r}); тайл — зеркало, периодичность не проверить"
    p = int(m.group(1))
    assert p == _P, f"фикстура: period_px={p}, ждали {_P}"
    assert alpha.shape[1] >= 2 * p, f"ширина тайла {alpha.shape[1]} < 2P"
    worst = min(float((alpha[:, x] == alpha[:, x + p]).mean()) for x in range(p))
    assert worst >= 0.99, f"худший столбец x<P совпадает с x+P только у {worst:.4f} строк"


# ── 7. кривые значения порогов -> SystemExit с именем флага ──────────────────────────────
def _error_text(exc: SystemExit, stderr: str) -> str:
    """Текст самой ошибки. Строка usage у argparse перечисляет ВСЕ флаги — по ней имя флага не проверять."""
    if isinstance(exc.code, str):
        return exc.code
    tail = stderr.rsplit("error:", 1)
    assert len(tail) == 2, f"SystemExit({exc.code!r}) без текста ошибки: {stderr!r}"
    return tail[1]


_BAD = [
    ("--gap-hue", "--gap-hue=60,40"),
    ("--gap-hue", "--gap-hue=-1,40"),
    ("--gap-hue", "--gap-hue=40,180"),
    ("--gap-sat-min", "--gap-sat-min=256"),
    ("--gap-sat-min", "--gap-sat-min=-1"),
    ("--rails-px", "--rails-px=48,48"),
    ("--rails-px", "--rails-px=200,0"),
]
_BAD_IDS = ["hue_lo_gt_hi", "hue_lo_neg", "hue_hi_180", "sat_256", "sat_neg", "rails_sum_eq_h", "rails_top_gt_h"]


@pytest.mark.parametrize(("flag", "arg"), _BAD, ids=_BAD_IDS)
def test_bad_threshold_is_systemexit_naming_the_flag(tmp_path, capsys, flag, arg):
    """Критерий 5: кривое значение -> SystemExit (код != 0), в тексте ошибки — имя флага. Контроль: валидное ок."""
    ok = {"--gap-hue": "55,95", "--gap-sat-min": "45", "--rails-px": "15,15"}
    ok_arg = f"{flag}={ok[flag]}"
    _run_ok(tmp_path, capsys, _photo(), "--gap-alpha", ok_arg, name="control.png")  # без реализации — AssertionError
    with pytest.raises(SystemExit) as info:
        tool.main([str(tmp_path / "photo.png"), "--out", str(tmp_path / "bad.png"), "--gap-alpha", arg])
    err = _error_text(info.value, capsys.readouterr().err)
    assert info.value.code not in (0, None)
    assert flag in err, f"в тексте ошибки нет {flag}: {err!r}"


_GOOD_EDGES = [
    "--gap-hue=0,179",
    "--gap-hue=54,54",
    "--gap-sat-min=0",
    "--gap-sat-min=255",
    "--rails-px=48,47",
]


@pytest.mark.parametrize("arg", _GOOD_EDGES)
def test_threshold_edge_values_are_accepted(tmp_path, capsys, arg):
    """Границы допустимого (0..179, 0..255, TOP+BOTTOM = h-1) не отвергаются."""
    _, out = _run_ok(tmp_path, capsys, _photo(), "--gap-alpha", arg)
    assert _read(out).shape[2] == 4


# ── 8. чистая функция gap_alpha_mask (имя — из плана; сигнатура за пределами первого аргумента — догадка) ──
def test_gap_alpha_mask_is_pure_2d_uint8(tmp_path):
    """`gap_alpha_mask(tile_rgb)` -> 2D uint8 (h, w) со значениями {0,255}, вход не мутирует."""
    rgb = np.ascontiguousarray(_photo()[:, :, ::-1])  # функция берёт RGB (имя аргумента tile_rgb)
    before = rgb.copy()
    mask = tool.gap_alpha_mask(rgb)
    assert isinstance(mask, np.ndarray) and mask.dtype == np.uint8
    assert mask.shape == rgb.shape[:2], f"форма маски {mask.shape}, ждали {rgb.shape[:2]}"
    assert set(np.unique(mask).tolist()) <= {0, 255}
    assert np.array_equal(rgb, before), "функция изменила входной массив"


# ── 9. реальный ассет (вне git; пропуск, если его нет) ───────────────────────────────────
_REAL = Path(os.environ.get("LINE_SIM_BELT_PHOTO") or Path(__file__).parents[3] / "data/line_sim/belt_photo_full.png")


@pytest.mark.skipif(not _REAL.exists(), reason="реального фото ленты нет (data/ вне git)")
def test_real_photo_default_thresholds_rgb_unchanged_alpha_sane(tmp_path, capsys):
    """Реальное фото, `--force-period`, дефолтные пороги: RGB == тайлу без опции, альфа бинарная, доля прозрачных
    в (0, 0.5); при `--rails-px 12,12` строки 0..11 и h-12..h-1 — 255. Пороги доли — оценка тестера, не контракт."""
    photo = imread_unicode(str(_REAL), cv2.IMREAD_COLOR)
    rc, _, plain_out = _run(_sub(tmp_path, "p"), capsys, photo, "--force-period")
    assert rc == 0
    plain = _read(plain_out)
    _, out = _run_ok(_sub(tmp_path, "g"), capsys, photo, "--force-period", "--gap-alpha")
    img = _read(out)
    assert img.shape == (plain.shape[0], plain.shape[1], 4)
    assert np.array_equal(img[:, :, :3], plain)
    alpha = img[:, :, 3]
    assert set(np.unique(alpha).tolist()) <= {0, 255}
    zero = float((alpha == 0).mean())
    assert 0.0 < zero < 0.5, f"доля прозрачных пикселей {zero:.4f} вне (0, 0.5)"
    _, out_r = _run_ok(_sub(tmp_path, "r"), capsys, photo, "--force-period", "--gap-alpha", "--rails-px=12,12")
    a_r = _read(out_r)[:, :, 3]
    assert (a_r[:12] == 255).all() and (a_r[-12:] == 255).all()
