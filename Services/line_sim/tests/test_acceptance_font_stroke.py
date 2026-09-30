"""RED-приёмка опции `--stroke-px` инструмента `tools.make_font_letters` (blind).

Пишется ДО реализации, только по критериям S1-S7 из брифа лида (запрос владельца 2026-09-30:
аугментация букв разными шрифтами И толщиной штриха). Исходник инструмента не читался; идиома
запуска (subprocess модуля, шрифты из matplotlib data path, imread_unicode) — из
`test_acceptance_1_1b_font_tool.py`.

Все ассерты — по файлам и пикселям, не по именам функций. Ожидаемые значения — литералы.

Контракт:
  * `--stroke-px N` повторяемая, целое N >= 0, по умолчанию одно значение 0;
  * N == 0 -> `<буква>/<stem>.png` (как сегодня), N > 0 -> `<буква>/<stem>_s<N>.png`;
  * высота буквы всё равно letter_frac * size_px, по центру; штрих добавляет N px с каждой стороны;
  * неверное N (отрицательное, нецелое) -> ошибка argparse, ненулевой код, ничего не записано;
  * глиф шире size_px (после штриха) -> ненулевой выход с сообщением про `--letter-frac`/«ширина».

Сегодня опция неизвестна argparse (код 2, «unrecognized arguments») — почти все тесты красные по
этой причине; каждый тест, который иначе мог бы быть зелёным «за счёт» этой ошибки (S6, S7), явно
проверяет, что причина отказа — не «unrecognized arguments».
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import cv2
import matplotlib
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imread_unicode

WORKTREE_ROOT = Path(__file__).resolve().parents[3]
FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
DEJAVU_SANS = FONT_DIR / "DejaVuSans.ttf"
DEJAVU_SANS_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"

UNRECOGNIZED = "unrecognized arguments"


@pytest.fixture(autouse=True)
def _fonts_exist() -> None:
    """GREEN-контроль: шрифты фикстуры реально есть на диске (matplotlib data dir)."""
    for f in (DEJAVU_SANS, DEJAVU_SANS_BOLD):
        assert f.is_file(), f"шрифт не найден: {f} (проверь установку matplotlib)"


def _run_tool(args: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(WORKTREE_ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "Services.line_sim.tools.make_font_letters", *args],
        cwd=str(WORKTREE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _diag(result: subprocess.CompletedProcess) -> str:
    return f"rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"


def _read_rgba(path: Path) -> np.ndarray:
    # cv2.imread на Windows не открывает путь с кириллицей (папка буквы) — читаем как продукт пишет.
    bgra = imread_unicode(path, cv2.IMREAD_UNCHANGED)
    assert bgra is not None, f"не удалось прочитать {path}"
    assert bgra.ndim == 3 and bgra.shape[2] == 4, f"{path}: shape={bgra.shape}, ожидали RGBA"
    return cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)


def _tree(out_dir: Path) -> dict[str, np.ndarray]:
    """{относительный путь (posix): RGBA-массив} для всех файлов под out_dir."""
    return {p.relative_to(out_dir).as_posix(): _read_rgba(p) for p in sorted(out_dir.rglob("*")) if p.is_file()}


def _file_names(out_dir: Path) -> set[str]:
    return {p.relative_to(out_dir).as_posix() for p in out_dir.rglob("*") if p.is_file()}


def _alpha_bbox(rgba: np.ndarray, thr: int = 127) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(rgba[:, :, 3] > thr)
    assert len(ys) > 0, "нет пикселей с alpha > 127 вовсе"
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


def _mid_row_width(rgba: np.ndarray) -> int:
    """Ширина штриха «I» на средней высоте холста: число пикселей alpha > 127 в строке h//2."""
    row = rgba[rgba.shape[0] // 2, :, 3]
    return int((row > 127).sum())


def _assert_nothing_written(out_dir: Path) -> None:
    assert not out_dir.exists() or _file_names(out_dir) == set(), (
        f"ничего не должно быть записано, но в {out_dir} есть: {sorted(_file_names(out_dir))}"
    )


# ---------------------------------------------------------------------------
# S1: обратная совместимость
# ---------------------------------------------------------------------------


def test_s1_default_run_equals_explicit_stroke_zero(tmp_path: Path) -> None:
    """S1: без --stroke-px набор файлов и пиксели каждого файла те же, что при `--stroke-px 0`."""
    common = [
        "--letters", "АК",
        "--font", str(DEJAVU_SANS),
        "--font", str(DEJAVU_SANS_BOLD),
        "--size-px", "100",
        "--letter-frac", "0.6",
        "--grain-sigma", "5",
        "--seed", "1",
    ]  # fmt: skip
    out_default = tmp_path / "default"
    out_zero = tmp_path / "zero"
    r_default = _run_tool([*common, "--out", str(out_default)])
    r_zero = _run_tool([*common, "--stroke-px", "0", "--out", str(out_zero)])

    assert r_default.returncode == 0, f"прогон без --stroke-px: {_diag(r_default)}"
    assert r_zero.returncode == 0, f"прогон с --stroke-px 0: {_diag(r_zero)}"

    tree_default = _tree(out_default)
    tree_zero = _tree(out_zero)
    assert len(tree_default) == 4, f"ожидали 4 файла (2 буквы x 2 шрифта), получили {sorted(tree_default)}"
    assert set(tree_default) == set(tree_zero), (
        f"наборы файлов разные: default={sorted(tree_default)} zero={sorted(tree_zero)}"
    )
    for rel, arr in tree_default.items():
        assert np.array_equal(arr, tree_zero[rel]), f"{rel}: пиксели без опции и при --stroke-px 0 различаются"


# ---------------------------------------------------------------------------
# S2: имена и набор файлов
# ---------------------------------------------------------------------------


def test_s2_three_strokes_two_fonts_give_exact_twelve_files(tmp_path: Path) -> None:
    """S2: 3 значения N x 2 шрифта x 2 буквы = ровно 12 файлов с именами <stem>.png/_s2/_s4, ничего лишнего."""
    out_dir = tmp_path / "out"
    result = _run_tool(
        [
            "--letters", "АК",
            "--font", str(DEJAVU_SANS),
            "--font", str(DEJAVU_SANS_BOLD),
            "--size-px", "100",
            "--letter-frac", "0.6",
            "--stroke-px", "0",
            "--stroke-px", "2",
            "--stroke-px", "4",
            "--out", str(out_dir),
        ]
    )  # fmt: skip
    assert result.returncode == 0, _diag(result)

    expected = {
        f"{letter}/{stem}{suffix}.png"
        for letter in ("А", "К")
        for stem in ("DejaVuSans", "DejaVuSans-Bold")
        for suffix in ("", "_s2", "_s4")
    }
    assert len(expected) == 12
    assert _file_names(out_dir) == expected, (
        f"набор файлов не тот: лишние={sorted(_file_names(out_dir) - expected)} "
        f"недостающие={sorted(expected - _file_names(out_dir))}"
    )


# ---------------------------------------------------------------------------
# S3 / S4: толщина, высота, центр (один прогон на модуль, буква I, 300 px)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stroke_run_i(tmp_path_factory: pytest.TempPathFactory) -> tuple[subprocess.CompletedProcess, Path]:
    """Один прогон `I`, DejaVuSans, 300 px, frac 0.6, N in {0,2,4}. Ассертов нет — их делают тесты."""
    out_dir = tmp_path_factory.mktemp("stroke_i") / "out"
    result = _run_tool(
        [
            "--letters", "I",
            "--font", str(DEJAVU_SANS),
            "--size-px", "300",
            "--letter-frac", "0.6",
            "--stroke-px", "0",
            "--stroke-px", "2",
            "--stroke-px", "4",
            "--out", str(out_dir),
        ]
    )  # fmt: skip
    return result, out_dir


def _sprite(run: tuple[subprocess.CompletedProcess, Path], n: int) -> np.ndarray:
    result, out_dir = run
    assert result.returncode == 0, f"прогон с --stroke-px 0/2/4 не удался: {_diag(result)}"
    name = "DejaVuSans.png" if n == 0 else f"DejaVuSans_s{n}.png"
    path = out_dir / "I" / name
    assert path.is_file(), f"файл не создан: {path}; есть: {sorted(_file_names(out_dir))}"
    rgba = _read_rgba(path)
    assert rgba.shape == (300, 300, 4), f"{path}: shape={rgba.shape}, ожидали (300,300,4)"
    return rgba


@pytest.mark.parametrize(("n", "grow", "tol"), [(2, 4, 1.5), (4, 8, 2.0)])
def test_s3_stroke_widens_bar_by_2n_px(stroke_run_i, n: int, grow: int, tol: float) -> None:
    """S3: ширина штриха «I» на средней высоте (alpha > 127) = база + 2N (N=2: +4±1.5; N=4: +8±2),
    база — со спрайта N=0 того же прогона."""
    base = _mid_row_width(_sprite(stroke_run_i, 0))
    assert base > 0, "на спрайте N=0 нет непрозрачных пикселей на средней строке"
    width = _mid_row_width(_sprite(stroke_run_i, n))
    assert abs(width - (base + grow)) <= tol, f"N={n}: ширина штриха {width}, база {base}; ожидали {base + grow}±{tol}"


def test_s4_control_default_run_height_and_centre(tmp_path: Path) -> None:
    """S4-контроль (ЗЕЛЁНЫЙ сегодня): прогон без --stroke-px — высота bbox 180±2, центр в 150±1.5.
    Доказывает, что сама методика измерения корректна для буквы I 300 px / frac 0.6."""
    out_dir = tmp_path / "out"
    result = _run_tool(
        ["--letters", "I", "--font", str(DEJAVU_SANS), "--size-px", "300", "--letter-frac", "0.6",
         "--out", str(out_dir)]
    )  # fmt: skip
    assert result.returncode == 0, _diag(result)
    rgba = _read_rgba(out_dir / "I" / "DejaVuSans.png")
    y0, y1, x0, x1 = _alpha_bbox(rgba)
    assert abs((y1 - y0 + 1) - 180) <= 2, f"высота bbox {y1 - y0 + 1}, ожидали 180±2"
    assert abs((y0 + y1) / 2.0 - 150) <= 1.5, f"центр по Y {(y0 + y1) / 2.0}, ожидали 150±1.5"
    assert abs((x0 + x1) / 2.0 - 150) <= 1.5, f"центр по X {(x0 + x1) / 2.0}, ожидали 150±1.5"


@pytest.mark.parametrize("n", [0, 2, 4])
def test_s4_height_and_centre_unchanged_by_stroke(stroke_run_i, n: int) -> None:
    """S4: для N in {0,2,4} высота alpha-bbox (alpha > 127) = round(0.6*300) = 180 ± 2,
    центр bbox в пределах ±1.5 px от центра холста (150) по обеим осям."""
    rgba = _sprite(stroke_run_i, n)
    y0, y1, x0, x1 = _alpha_bbox(rgba)
    height = y1 - y0 + 1
    assert abs(height - 180) <= 2, f"N={n}: высота bbox {height}, ожидали 180±2"
    cy, cx = (y0 + y1) / 2.0, (x0 + x1) / 2.0
    assert abs(cy - 150) <= 1.5, f"N={n}: центр по Y {cy}, ожидали 150±1.5"
    assert abs(cx - 150) <= 1.5, f"N={n}: центр по X {cx}, ожидали 150±1.5"


# ---------------------------------------------------------------------------
# S5: опции чернил действуют на спрайты со штрихом
# ---------------------------------------------------------------------------


def test_s5_ink_and_grain_apply_to_stroked_sprite(tmp_path: Path) -> None:
    """S5: `--ink-rgb 65,70,82 --grain-sigma 9 --seed 1`: у `_s2` спрайта непрозрачные пиксели (alpha == 255)
    имеют средний RGB в пределах ±4 от (65,70,82) и std по каждому каналу в [4, 14]."""
    out_dir = tmp_path / "out"
    result = _run_tool(
        [
            "--letters", "А",
            "--font", str(DEJAVU_SANS),
            "--size-px", "200",
            "--letter-frac", "0.6",
            "--stroke-px", "2",
            "--ink-rgb", "65,70,82",
            "--grain-sigma", "9",
            "--seed", "1",
            "--out", str(out_dir),
        ]
    )  # fmt: skip
    assert result.returncode == 0, _diag(result)
    path = out_dir / "А" / "DejaVuSans_s2.png"
    assert path.is_file(), f"файл не создан: {path}; есть: {sorted(_file_names(out_dir))}"
    rgba = _read_rgba(path)
    opaque = rgba[rgba[:, :, 3] == 255][:, 0:3].astype(np.float64)
    assert len(opaque) >= 200, f"слишком мало пикселей alpha == 255: {len(opaque)}"
    mean = opaque.mean(axis=0)
    std = opaque.std(axis=0)
    for ch, target in enumerate((65, 70, 82)):
        assert abs(mean[ch] - target) <= 4, f"канал {ch}: среднее {mean[ch]:.2f}, ожидали {target}±4"
        assert 4 <= std[ch] <= 14, f"канал {ch}: std {std[ch]:.2f}, ожидали в [4, 14]"


# ---------------------------------------------------------------------------
# S6: неверные значения
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["-1", "1.5"])
def test_s6_invalid_stroke_value_rejected_and_valid_one_accepted(tmp_path: Path, bad: str) -> None:
    """S6: `--stroke-px -1` / `1.5` -> ненулевой код, --out не создан или пуст. Чтобы тест не был зелёным
    «за счёт» неизвестной опции: (а) валидный `--stroke-px 2` тем же набором аргументов -> код 0;
    (б) отказ на плохом значении — не «unrecognized arguments»."""
    base = ["--letters", "А", "--font", str(DEJAVU_SANS), "--size-px", "100", "--letter-frac", "0.6"]

    ok_out = tmp_path / "ok"
    ok = _run_tool([*base, "--stroke-px", "2", "--out", str(ok_out)])
    assert ok.returncode == 0, f"валидный --stroke-px 2 должен приниматься: {_diag(ok)}"

    bad_out = tmp_path / "bad"
    result = _run_tool([*base, "--stroke-px", bad, "--out", str(bad_out)])
    assert result.returncode != 0, f"--stroke-px {bad} должно отвергаться: {_diag(result)}"
    assert UNRECOGNIZED not in result.stderr, (
        f"отказ из-за неизвестной опции, а не из-за значения {bad}: {_diag(result)}"
    )
    _assert_nothing_written(bad_out)


# ---------------------------------------------------------------------------
# S7: защита от слишком широкого глифа продолжает работать со штрихом
# ---------------------------------------------------------------------------


def _assert_wide_guard(result: subprocess.CompletedProcess, out_dir: Path) -> None:
    assert result.returncode != 0, f"слишком широкий глиф должен давать ненулевой код: {_diag(result)}"
    text = result.stdout + result.stderr
    assert UNRECOGNIZED not in text, f"отказ из-за неизвестной опции, а не из-за ширины: {text!r}"
    # usage argparse тоже содержит «--letter-frac», поэтому проверка выше (не «unrecognized arguments») обязательна.
    assert "--letter-frac" in text or "ширина" in text.lower(), (
        f"в сообщении нет '--letter-frac' или 'ширина': {text!r}"
    )
    _assert_nothing_written(out_dir)


def test_s7_literal_brief_case_wide_glyph_guard_fires(tmp_path: Path) -> None:
    """S7 (пример из брифа буквально): Ж, --size-px 120 --letter-frac 0.9 --stroke-px 20 -> ненулевой выход
    с '--letter-frac'/'ширина', ничего не записано.
    ВНИМАНИЕ: Ж при 120/0.9 шире size_px уже БЕЗ штриха (156 > 120, замер сегодняшнего прогона), поэтому
    этот тест штрих не изолирует — его изолирует test_s7_stroke_alone_makes_glyph_too_wide."""
    out_dir = tmp_path / "out"
    result = _run_tool(
        ["--letters", "Ж", "--font", str(DEJAVU_SANS), "--size-px", "120", "--letter-frac", "0.9",
         "--stroke-px", "20", "--out", str(out_dir)]
    )  # fmt: skip
    _assert_wide_guard(result, out_dir)


def test_s7_stroke_alone_makes_glyph_too_wide(tmp_path: Path) -> None:
    """S7 (изолирующий вариант): Ж, --size-px 120 --letter-frac 0.6 — без штриха влезает (контроль, код 0,
    зелёный сегодня); с `--stroke-px 20` (+40 px ширины) — не влезает -> guard срабатывает."""
    base = ["--letters", "Ж", "--font", str(DEJAVU_SANS), "--size-px", "120", "--letter-frac", "0.6"]

    control = _run_tool([*base, "--out", str(tmp_path / "control")])
    assert control.returncode == 0, f"контроль: Ж без штриха при frac 0.6 должна влезать: {_diag(control)}"

    out_dir = tmp_path / "out"
    result = _run_tool([*base, "--stroke-px", "20", "--out", str(out_dir)])
    _assert_wide_guard(result, out_dir)


def test_s7_small_stroke_below_the_limit_is_accepted(tmp_path: Path) -> None:
    """S7 (другая сторона границы): та же Ж, 120 px, frac 0.6, `--stroke-px 5` (+10 px) — влезает -> код 0
    и файл `Ж/DejaVuSans_s5.png` создан. Защита от «guard отвергает любой штрих»."""
    out_dir = tmp_path / "out"
    result = _run_tool(
        ["--letters", "Ж", "--font", str(DEJAVU_SANS), "--size-px", "120", "--letter-frac", "0.6",
         "--stroke-px", "5", "--out", str(out_dir)]
    )  # fmt: skip
    assert result.returncode == 0, _diag(result)
    assert (out_dir / "Ж" / "DejaVuSans_s5.png").is_file(), f"нет файла; есть: {sorted(_file_names(out_dir))}"
