"""Авторские hazard-тесты `--stroke-px` (`tools.make_font_letters`): внутренние места механизма.

Независимая приёмка — `test_acceptance_font_stroke.py`; здесь только то, что видно автору:
дедупликация значений штриха, порядок «всё отрендерить, потом писать» при плохом значении в списке,
порядок потребления rng (буква x шрифт x штрих) и его последствие для зерна.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import pytest

from Services.line_sim.tools.make_font_letters import build_font_letters, main

FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
DEJAVU_SANS = FONT_DIR / "DejaVuSans.ttf"
DEJAVU_SANS_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"

_GRAIN = {"grain_sigma": 9.0, "seed": 1}


def _names(out: Path) -> set[str]:
    return {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}


def test_h1_duplicate_strokes_write_one_file_each(tmp_path: Path) -> None:
    """Повтор значения в списке: один файл, а не две записи в один путь; порядок — первое вхождение."""
    written = build_font_letters("I", [DEJAVU_SANS], 100, 0.6, tmp_path / "out", stroke_px=[2, 2, 0, 2, 0])

    assert [p.name for p in written] == ["DejaVuSans_s2.png", "DejaVuSans.png"], written
    assert _names(tmp_path / "out") == {"I/DejaVuSans_s2.png", "I/DejaVuSans.png"}


def test_h2_bad_value_anywhere_in_list_writes_nothing(tmp_path: Path) -> None:
    """`--stroke-px 2 --stroke-px -1`: argparse отвергает список ДО рендера — валидное 2 не успевает записаться."""
    out = tmp_path / "out"
    argv = ["--letters", "I", "--font", str(DEJAVU_SANS), "--size-px", "100", "--out", str(out)]
    with pytest.raises(SystemExit) as exc:
        main([*argv, "--stroke-px", "2", "--stroke-px", "-1"])

    assert exc.value.code == 2
    assert not out.exists() or _names(out) == set(), f"записано: {sorted(_names(out))}"


def test_h3_rng_order_letter_font_stroke_first_triple_keeps_grain(tmp_path: Path) -> None:
    """Зерно: rng один на вызов, порядок буква x шрифт x штрих. Следствие, проверяемое здесь:
    * штрих 0 ПЕРВЫМ в списке -> спрайт N=0 первой пары буква/шрифт побайтно равен прогону без штриха;
    * штрих 0 не первым -> его зерно другое (первые числа rng ушли на N=2);
    * второй шрифт при добавлении штриха тоже получает другое зерно (rng сдвинут спрайтом N=2 первого)."""

    def run(name: str, strokes: list[int]) -> Path:
        out = tmp_path / name
        build_font_letters("I", [DEJAVU_SANS, DEJAVU_SANS_BOLD], 100, 0.6, out, stroke_px=strokes, **_GRAIN)
        return out / "I"

    plain = run("plain", [0])
    zero_first = run("zero_first", [0, 2])
    zero_last = run("zero_last", [2, 0])

    assert (zero_first / "DejaVuSans.png").read_bytes() == (plain / "DejaVuSans.png").read_bytes()
    assert (zero_last / "DejaVuSans.png").read_bytes() != (plain / "DejaVuSans.png").read_bytes()
    assert (zero_first / "DejaVuSans-Bold.png").read_bytes() != (plain / "DejaVuSans-Bold.png").read_bytes()


def test_h4_guard_boundary_4n_vs_desired_height(tmp_path: Path) -> None:
    """Граница защиты `4 * N >= round(frac * size)`: size 100, frac 0.6 -> desired 60.
    N=14 (4N == 56 == desired - 4) принимается, N=15 (4N == 60 == desired) отвергается ДО рендера,
    сообщение содержит `--stroke-px` и оба числа; N=15 в списке вместе с валидным N=0 не пишет и N=0."""
    ok = build_font_letters("I", [DEJAVU_SANS], 100, 0.6, tmp_path / "ok", stroke_px=[14])
    assert [p.name for p in ok] == ["DejaVuSans_s14.png"]

    out = tmp_path / "bad"
    with pytest.raises(SystemExit) as exc:
        build_font_letters("I", [DEJAVU_SANS], 100, 0.6, out, stroke_px=[0, 15])
    message = str(exc.value)
    assert "--stroke-px" in message and "60" in message and "15" in message, message
    assert not out.exists() or _names(out) == set(), f"записано: {sorted(_names(out))}"


def test_h5_empty_stroke_list_is_rejected_not_silently_empty(tmp_path: Path) -> None:
    """`stroke_px=[]` раньше молча возвращал [] и ничего не писал; теперь ValueError до рендера."""
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="stroke_px"):
        build_font_letters("I", [DEJAVU_SANS], 100, 0.6, out, stroke_px=[])
    assert not out.exists() or _names(out) == set()


@pytest.mark.parametrize("bad", [-1, 1.5, "2", True])
def test_h6_bad_stroke_value_in_api_is_rejected_before_render(tmp_path: Path, bad: object) -> None:
    """`[0, bad]`: раньше отрицательное давало имя `<stem>.png` и перезаписывало файл N=0; теперь ValueError
    с плохим значением в тексте, ни одного файла (валидный 0 тоже не пишется)."""
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="stroke_px") as exc:
        build_font_letters("I", [DEJAVU_SANS], 100, 0.6, out, stroke_px=[0, bad])  # type: ignore[list-item]
    assert repr(bad) in str(exc.value)
    assert not out.exists() or _names(out) == set()
