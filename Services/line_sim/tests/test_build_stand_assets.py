# -*- coding: utf-8 -*-
"""Тесты автора Task 6.5 (line-sim): сборка ассетов стенда `build_stand_assets`.

Purpose: проверить `Services.line_sim.tools.build_stand_assets.main(argv)` на реальных
дочерних CLI и закоммиченных фикстурах: борта фото по усечённой медиане при нетронутом
теле, плитка 410x484x4, каталог букв (8 файлов) и диск 300x300x4, идемпотентность по
группам (байты и mtime), `--force`, пересборка частичной/нечитаемой группы, предпроверка
до первой записи, код 1 при провале дочернего CLI, разрешение `--data-dir` через
`preset.REPO_ROOT`, точные аргументы дочерних вызовов. Все записи — только в `tmp_path`;
реальный `data/line_sim` не трогается. Ожидаемые значения — литералы спеки
(`plans/line-sim/phase-6-task-6.5.md`); эталон бортов считается из фикстуры по формуле
усечения (не из кода модуля).

Модуль-под-тестом импортируется лениво (фикстура `bsa`): до реализации каждый тест падает сам.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode

__all__: list[str] = []

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

_PHOTO = "belt_photo_full.png"
_TILE = "belt_tile.png"
_DISK = "letters_ink_disk.png"
_LETTER_DIRS = ["А", "К", "Р", "Х"]  # А К Р Х (кириллица)
_LETTER_FILES = ["DejaVuSans_s3.png", "DejaVuSansMono_s3.png"]

_LINE_PHOTO = "belt_photo_full.png 598x484x3"
_LINE_TILE = "belt_tile.png 410x484x4"
_LINE_LETTERS = "letters_ink 8 files, disk 300x300x4"

_RAIL_ROWS = np.array(list(range(0, 22)) + list(range(463, 484)))


def _all_files() -> list[str]:
    letters = [f"letters_ink/{d}/{f}" for d in _LETTER_DIRS for f in _LETTER_FILES]
    return [_PHOTO, _TILE, *letters, _DISK]


def _status(out: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith(("built ", "skipped "))]


def _snapshot(data: Path) -> dict[str, tuple[bytes, int]]:
    return {rel: ((data / rel).read_bytes(), (data / rel).stat().st_mtime_ns) for rel in _all_files()}


def _letter_files(data: Path) -> list[Path]:
    return sorted(p for p in (data / "letters_ink").rglob("*") if p.is_file())


@pytest.fixture
def bsa() -> ModuleType:
    return importlib.import_module("Services.line_sim.tools.build_stand_assets")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Один настоящий прогон на чистом tmp-каталоге: код, stdout, stderr и путь."""
    bsa = importlib.import_module("Services.line_sim.tools.build_stand_assets")
    data = tmp_path_factory.mktemp("author6_5") / "data"
    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = bsa.main(["--data-dir", str(data)])
    return {"rc": rc, "out": out.getvalue(), "err": err.getvalue(), "data": data}


def test_photo_rails_flat_body_equal(built: dict[str, object]) -> None:
    assert built["rc"] == 0, built["err"]
    data: Path = built["data"]  # type: ignore[assignment]
    fixture = imread_unicode(_FIXTURES / _PHOTO, cv2.IMREAD_COLOR)
    photo = imread_unicode(data / _PHOTO, cv2.IMREAD_COLOR)

    assert photo.shape == (484, 598, 3)
    assert (photo[_RAIL_ROWS].std(axis=1) == 0).all()
    expected = np.median(fixture[_RAIL_ROWS], axis=1).astype(np.uint8)
    assert (photo[_RAIL_ROWS] == expected[:, None, :]).all()
    assert np.array_equal(photo[22:463], fixture[22:463])
    assert _status(built["out"])[0] == f"built {_LINE_PHOTO}"  # type: ignore[arg-type]


def test_tile_is_410x484x4(built: dict[str, object]) -> None:
    data: Path = built["data"]  # type: ignore[assignment]
    tile = imread_unicode(data / _TILE, cv2.IMREAD_UNCHANGED)
    assert tile.shape == (484, 410, 4)
    assert "period_px=205" in built["out"]  # type: ignore[operator]
    assert _status(built["out"])[1] == f"built {_LINE_TILE}"  # type: ignore[arg-type]


def test_letters_8_files_and_disk_300(built: dict[str, object]) -> None:
    data: Path = built["data"]  # type: ignore[assignment]
    assert sorted(p.name for p in (data / "letters_ink").iterdir()) == sorted(_LETTER_DIRS)
    for letter in _LETTER_DIRS:
        assert sorted(p.name for p in (data / "letters_ink" / letter).iterdir()) == sorted(_LETTER_FILES)
    assert len(_letter_files(data)) == 8
    assert imread_unicode(data / _DISK, cv2.IMREAD_UNCHANGED).shape == (300, 300, 4)
    assert _status(built["out"])[2] == f"built {_LINE_LETTERS}"  # type: ignore[arg-type]
    assert "ошибка шага" not in built["err"]  # type: ignore[operator]  # stderr дочернего tile несёт заметку про масштаб


def test_second_run_skips_and_keeps_bytes_and_mtime(
    bsa: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    assert bsa.main(["--data-dir", str(data)]) == 0
    first = _snapshot(data)
    capsys.readouterr()

    assert bsa.main(["--data-dir", str(data)]) == 0

    assert _status(capsys.readouterr().out) == [
        f"skipped {_LINE_PHOTO}",
        f"skipped {_LINE_TILE}",
        f"skipped {_LINE_LETTERS}",
    ]
    assert _snapshot(data) == first


def test_force_rebuilds_all(bsa: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = tmp_path / "data"
    assert bsa.main(["--data-dir", str(data)]) == 0
    before = _snapshot(data)
    capsys.readouterr()

    assert bsa.main(["--data-dir", str(data), "--force"]) == 0

    assert _status(capsys.readouterr().out) == [
        f"built {_LINE_PHOTO}",
        f"built {_LINE_TILE}",
        f"built {_LINE_LETTERS}",
    ]
    after = _snapshot(data)
    for rel in _all_files():
        assert after[rel][1] > before[rel][1], rel


def test_partial_letters_group_rebuilt_and_junk_removed(
    bsa: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    assert bsa.main(["--data-dir", str(data)]) == 0
    base = {rel: v for rel, v in _snapshot(data).items() if rel in (_PHOTO, _TILE)}
    (data / "letters_ink" / "Х" / "DejaVuSansMono_s3.png").unlink()  # неполная группа: 7 файлов
    junk = data / "letters_ink" / "К" / "junk.png"
    junk.write_bytes(b"not an image")
    capsys.readouterr()

    assert bsa.main(["--data-dir", str(data)]) == 0

    assert _status(capsys.readouterr().out) == [
        f"skipped {_LINE_PHOTO}",
        f"skipped {_LINE_TILE}",
        f"built {_LINE_LETTERS}",
    ]
    assert not junk.exists()
    assert len(_letter_files(data)) == 8
    for rel, (data_bytes, mtime) in base.items():
        assert (data / rel).read_bytes() == data_bytes
        assert (data / rel).stat().st_mtime_ns == mtime


def test_photo_rebuilt_forces_tile_and_unreadable_tile_rebuilt(
    bsa: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    assert bsa.main(["--data-dir", str(data)]) == 0
    letters = {rel: v for rel, v in _snapshot(data).items() if rel.startswith("letters_ink") or rel == _DISK}

    # фото пересобрано -> исправный тайл тоже пересобирается; буквы не трогаются
    old_tile_mtime = (data / _TILE).stat().st_mtime_ns
    (data / _PHOTO).unlink()
    capsys.readouterr()
    assert bsa.main(["--data-dir", str(data)]) == 0
    assert _status(capsys.readouterr().out) == [
        f"built {_LINE_PHOTO}",
        f"built {_LINE_TILE}",
        f"skipped {_LINE_LETTERS}",
    ]
    assert (data / _TILE).stat().st_mtime_ns > old_tile_mtime
    for rel, (data_bytes, mtime) in letters.items():
        assert ((data / rel).read_bytes(), (data / rel).stat().st_mtime_ns) == (data_bytes, mtime)

    # нечитаемый тайл (0 байт) -> только тайл пересобирается
    (data / _TILE).write_bytes(b"")
    assert bsa.main(["--data-dir", str(data)]) == 0
    assert _status(capsys.readouterr().out) == [
        f"skipped {_LINE_PHOTO}",
        f"built {_LINE_TILE}",
        f"skipped {_LINE_LETTERS}",
    ]
    assert imread_unicode(data / _TILE, cv2.IMREAD_UNCHANGED).shape == (484, 410, 4)


def test_missing_fixture_exit_nonzero_nothing_written(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "real_disk_snapshot.png").write_bytes(b"x")  # нет только фото
    monkeypatch.setattr(bsa, "FIXTURES_DIR", fixtures)
    data = tmp_path / "data"

    rc = bsa.main(["--data-dir", str(data)])

    err = capsys.readouterr().err
    assert rc == 1
    assert err.strip() == f"ошибка шага preflight: {fixtures / _PHOTO} не найден"
    assert not data.exists()


def test_child_failure_exit1_error_line(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mst = importlib.import_module("Services.line_sim.tools.make_seamless_texture")
    mfl = importlib.import_module("Services.line_sim.tools.make_font_letters")
    real_mst = mst.main

    # 1) тайл: код != 0 -> шаг tile, буквы не строятся, фото уже на диске
    monkeypatch.setattr(mst, "main", lambda argv=None: 2)
    data = tmp_path / "tile_rc"
    assert bsa.main(["--data-dir", str(data)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("ошибка шага tile: ")
    assert (data / _PHOTO).is_file() and not (data / "letters_ink").exists()

    # 2) тайл: исключение -> шаг tile
    def boom(argv: list[str] | None = None) -> int:
        raise ValueError("плохая плитка")

    monkeypatch.setattr(mst, "main", boom)
    assert bsa.main(["--data-dir", str(tmp_path / "tile_exc"), "--force"]) == 1
    assert "ошибка шага tile: " in capsys.readouterr().err

    # 3) буквы: SystemExit со строкой -> шаг letters
    monkeypatch.setattr(mst, "main", real_mst)

    def exit_x(argv: list[str] | None = None) -> None:
        raise SystemExit("x")

    monkeypatch.setattr(mfl, "main", exit_x)
    assert bsa.main(["--data-dir", str(tmp_path / "letters_exit")]) == 1
    assert "ошибка шага letters: " in capsys.readouterr().err

    # 4) буквы: исключение -> шаг letters
    def raises(argv: list[str] | None = None) -> None:
        raise RuntimeError("шрифт")

    monkeypatch.setattr(mfl, "main", raises)
    assert bsa.main(["--data-dir", str(tmp_path / "letters_exc")]) == 1
    assert "ошибка шага letters: " in capsys.readouterr().err


def test_tile_child_nonzero_code_with_valid_file_fails(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mst = importlib.import_module("Services.line_sim.tools.make_seamless_texture")

    def writes_valid_tile_but_fails(argv: list[str] | None = None) -> int:
        out = Path(argv[argv.index("--out") + 1])  # type: ignore[index, union-attr]
        imwrite_unicode(out, np.zeros((484, 410, 4), dtype=np.uint8))  # читаемый тайл нужной формы
        return 2

    monkeypatch.setattr(mst, "main", writes_valid_tile_but_fails)
    data = tmp_path / "data"

    rc = bsa.main(["--data-dir", str(data)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "ошибка шага tile" in captured.err
    assert "built belt_tile.png" not in captured.out
    assert not (data / "letters_ink").exists()


def test_relative_data_dir_resolves_from_preset_repo_root(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preset = importlib.import_module("Services.line_sim.core.preset")
    root, cwd = tmp_path / "root", tmp_path / "cwd"
    root.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(preset, "REPO_ROOT", root)
    monkeypatch.chdir(cwd)

    assert bsa.main(["--data-dir", "out"]) == 0

    assert (root / "out" / _PHOTO).is_file()
    assert not (cwd / "out").exists()


def test_children_called_with_spec_arguments(bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mst = importlib.import_module("Services.line_sim.tools.make_seamless_texture")
    mfl = importlib.import_module("Services.line_sim.tools.make_font_letters")
    calls: dict[str, list[list[str]]] = {"tile": [], "letters": []}
    real_mst, real_mfl = mst.main, mfl.main

    def spy_tile(argv: list[str] | None = None) -> int:
        calls["tile"].append(list(argv or []))
        return real_mst(argv)

    def spy_letters(argv: list[str] | None = None) -> None:
        calls["letters"].append(list(argv or []))
        return real_mfl(argv)

    monkeypatch.setattr(mst, "main", spy_tile)
    monkeypatch.setattr(mfl, "main", spy_letters)
    data = tmp_path / "data"

    assert bsa.main(["--data-dir", str(data)]) == 0

    assert calls["tile"] == [[str(data / _PHOTO), "--out", str(data / _TILE), "--force-period", "--gap-alpha"]]
    fonts = Path(importlib.import_module("matplotlib").get_data_path()) / "fonts" / "ttf"
    expected = [
        [
            "--letters", "АКРХ", "--font", str(fonts / f"{name}.ttf"),
            "--stroke-px", "3", "--size-px", "300", "--letter-frac", "0.4763",
            "--ink-rgb", "65,70,82", "--grain-sigma", "9", "--edge-blur-px", "1", "--seed", "1",
            "--disk-from-photo", str(_FIXTURES / "real_disk_snapshot.png"),
            "--out", str(data / "letters_ink"), "--disk-out", str(data / _DISK),
        ]
        for name in ("DejaVuSans", "DejaVuSansMono")
    ]  # fmt: skip
    assert calls["letters"] == expected


def test_tile_child_systemexit_fails_step_tile(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mst = importlib.import_module("Services.line_sim.tools.make_seamless_texture")

    def exits(argv: list[str] | None = None) -> int:
        raise SystemExit(2)  # argparse-ошибка дочернего CLI

    monkeypatch.setattr(mst, "main", exits)
    data = tmp_path / "data"

    assert bsa.main(["--data-dir", str(data)]) == 1

    assert capsys.readouterr().err.startswith("ошибка шага tile: ")
    assert not (data / "letters_ink").exists()


def test_missing_font_fails_preflight_without_writes(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mpl = importlib.import_module("matplotlib")
    monkeypatch.setattr(mpl, "get_data_path", lambda: str(tmp_path / "no_mpl"))
    data = tmp_path / "data"

    rc = bsa.main(["--data-dir", str(data)])

    expected_font = Path(str(tmp_path / "no_mpl")) / "fonts" / "ttf" / "DejaVuSans.ttf"
    assert rc == 1
    assert capsys.readouterr().err.strip() == f"ошибка шага preflight: {expected_font} не найден"
    assert not data.exists()


def test_grayscale_photo_status_line_does_not_crash(
    bsa: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    assert bsa.main(["--data-dir", str(data)]) == 0
    imwrite_unicode(data / _PHOTO, np.zeros((484, 598), dtype=np.uint8))  # серый PNG на месте фото
    capsys.readouterr()

    assert bsa.main(["--data-dir", str(data)]) == 0

    assert _status(capsys.readouterr().out) == [
        "skipped belt_photo_full.png 598x484x1",
        f"skipped {_LINE_TILE}",
        f"skipped {_LINE_LETTERS}",
    ]


def test_data_dir_is_a_file_fails_preflight(
    bsa: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    occupied = tmp_path / "occupied"
    occupied.write_bytes(b"not a directory")

    rc = bsa.main(["--data-dir", str(occupied)])

    assert rc == 1
    assert capsys.readouterr().err.startswith("ошибка шага preflight: каталог")
    assert occupied.read_bytes() == b"not a directory"


def test_extra_png_in_letters_dir_rebuilds_group(
    bsa: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    assert bsa.main(["--data-dir", str(data)]) == 0
    extra = data / "letters_ink" / "А" / "DejaVuSans_s2.png"  # читаемая копия под чужим именем
    extra.write_bytes((data / "letters_ink" / "А" / "DejaVuSans_s3.png").read_bytes())
    capsys.readouterr()

    assert bsa.main(["--data-dir", str(data)]) == 0

    assert _status(capsys.readouterr().out) == [
        f"skipped {_LINE_PHOTO}",
        f"skipped {_LINE_TILE}",
        f"built {_LINE_LETTERS}",
    ]
    assert not extra.exists()
    assert len(_letter_files(data)) == 8


def test_extra_webp_in_letters_dir_rebuilds_group(
    bsa: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    assert bsa.main(["--data-dir", str(data)]) == 0
    junk = data / "letters_ink" / "А" / "junk.webp"  # другой суффикс спрайта каталога
    junk.write_bytes(b"not an image")
    capsys.readouterr()

    assert bsa.main(["--data-dir", str(data)]) == 0

    assert _status(capsys.readouterr().out) == [
        f"skipped {_LINE_PHOTO}",
        f"skipped {_LINE_TILE}",
        f"built {_LINE_LETTERS}",
    ]
    assert not junk.exists()
    assert len(_letter_files(data)) == 8
