# -*- coding: utf-8 -*-
"""Слепая приёмка Task 6.5 (line-sim): сборка ассетов стенда одной командой из фикстур.

Purpose: проверить публичный контракт модуля `Services.line_sim.tools.build_stand_assets`
(`main(argv) -> int`, константа `FIXTURES_DIR`, CLI `--data-dir` / `--force`) по пунктам 1-16
раздела ACCEPTANCE плана `plans/line-sim/phase-6-task-6.5.md`: размеры и пиксели собранных
файлов, строки stdout/stderr, идемпотентность по группам, независимость от cwd, путь с
кириллицей, провал дочернего CLI. Реализации в момент написания нет (по конструкции).

Источник: спека, разделы «Посылка», «DESIGN» (только публичные имена и литералы вывода) и
«ACCEPTANCE». Тесты автора и тело модуля не читались. Все записи — только в tmp; реальный
`data/line_sim` не трогается. Ожидаемые значения — литералы спеки (598x484x3, 410x484x4,
300x300x4, 8 файлов в каталогах А К Р Х); эталон пикселей борта считается здесь же из
закоммиченной фикстуры по формуле усечения `np.median(row, axis=0).astype(np.uint8)`.

Модуль-под-тестом импортируется лениво (фикстура `bsa`), чтобы до реализации каждый тест
падал сам, а не весь файл на сборе.
"""

from __future__ import annotations

import importlib
import io
import shutil
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imread_unicode

__all__: list[str] = []

# --- литералы спеки -----------------------------------------------------------------------

_FIXTURE_PHOTO = Path(__file__).resolve().parent / "fixtures" / "belt_photo_full.png"

# А К Р Х (кириллица), записаны кодами, чтобы кодировка исходника не влияла.
_LETTER_DIRS = ["А", "К", "Р", "Х"]
_LETTER_FILES = ["DejaVuSans_s3.png", "DejaVuSansMono_s3.png"]

_PHOTO = "belt_photo_full.png"
_TILE = "belt_tile.png"
_DISK = "letters_ink_disk.png"

_LINE_PHOTO = "belt_photo_full.png 598x484x3"
_LINE_TILE = "belt_tile.png 410x484x4"
_LINE_LETTERS = "letters_ink 8 files, disk 300x300x4"

_RAIL_ROWS = list(range(0, 22)) + list(range(463, 484))
_BODY = slice(22, 463)  # строки 22..462

_RUN_DEADLINE_S = 180.0


# --- помощники ------------------------------------------------------------------------------


def _all_files() -> list[str]:
    """11 файлов сборки: относительные пути от `--data-dir` (posix-вид)."""
    letters = [f"letters_ink/{d}/{f}" for d in _LETTER_DIRS for f in _LETTER_FILES]
    return [_PHOTO, _TILE, *letters, _DISK]


def _run(bsa: ModuleType, argv: list[str]) -> tuple[int, str, str]:
    """`main(argv)` в потоке-демоне с дедлайном; вернуть (код, stdout, stderr)."""
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["rc"] = bsa.main(argv)
        except SystemExit as exc:  # main обязан возвращать код, но SystemExit тоже читаем как код
            box["rc"] = 0 if exc.code is None else exc.code
        except BaseException as exc:  # noqa: BLE001 - пробрасываем в основной поток
            box["exc"] = exc

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(_RUN_DEADLINE_S)
    assert not thread.is_alive(), f"main({argv}) завис дольше {_RUN_DEADLINE_S} с"
    if "exc" in box:
        raise AssertionError(f"main({argv}) бросил {box['exc']!r}\nstderr:\n{err.getvalue()}") from box["exc"]  # type: ignore[arg-type]
    return box["rc"], out.getvalue(), err.getvalue()  # type: ignore[return-value]


def _status_lines(stdout: str) -> list[str]:
    """Строки stdout с префиксом `built ` / `skipped ` (строки дочерних CLI отфильтрованы)."""
    return [ln.rstrip("\r") for ln in stdout.splitlines() if ln.startswith(("built ", "skipped "))]


def _snapshot(data: Path) -> dict[str, tuple[bytes, int]]:
    snap: dict[str, tuple[bytes, int]] = {}
    for rel in _all_files():
        p = data / rel
        snap[rel] = (p.read_bytes(), p.stat().st_mtime_ns)
    return snap


def _letters_files(data: Path) -> list[Path]:
    root = data / "letters_ink"
    return sorted(p for p in root.rglob("*") if p.is_file())


def _check_assets(data: Path) -> None:
    """ACCEPTANCE 1-5: размеры/тип/состав. Чтение только через `imread_unicode`."""
    photo = imread_unicode(data / _PHOTO, cv2.IMREAD_UNCHANGED)
    assert photo.shape == (484, 598, 3), photo.shape
    assert photo.dtype == np.uint8

    tile = imread_unicode(data / _TILE, cv2.IMREAD_UNCHANGED)
    assert tile.shape == (484, 410, 4), tile.shape

    root = data / "letters_ink"
    assert sorted(p.name for p in root.iterdir()) == sorted(_LETTER_DIRS)
    for d in _LETTER_DIRS:
        assert (root / d).is_dir()
        assert sorted(p.name for p in (root / d).iterdir()) == sorted(_LETTER_FILES), d
        for f in _LETTER_FILES:
            assert imread_unicode(root / d / f, cv2.IMREAD_UNCHANGED).size > 0
    assert len(_letters_files(data)) == 8

    disk = imread_unicode(data / _DISK, cv2.IMREAD_UNCHANGED)
    assert disk.shape == (300, 300, 4), disk.shape


def _fixture_photo() -> np.ndarray:
    return imread_unicode(_FIXTURE_PHOTO, cv2.IMREAD_COLOR)


def _copy_tree(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst)
    return dst


# --- фикстуры -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def bsa() -> ModuleType:
    return importlib.import_module("Services.line_sim.tools.build_stand_assets")


@pytest.fixture(scope="module")
def lifecycle(bsa: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Один каталог: 1-й прогон, 2-й без --force, --force. Результаты каждого шага сохранены."""
    data = tmp_path_factory.mktemp("stand6_5") / "data"
    res: dict[str, object] = {"data": data}

    res["first"] = _run(bsa, ["--data-dir", str(data)])
    res["snap_first"] = _snapshot(data)

    res["second"] = _run(bsa, ["--data-dir", str(data)])
    res["snap_second"] = _snapshot(data)

    res["forced"] = _run(bsa, ["--data-dir", str(data), "--force"])
    res["snap_forced"] = _snapshot(data)
    return res


@pytest.fixture(scope="module")
def built_template(lifecycle: dict[str, object], tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Копия собранного каталога (после --force): шаблон для тестов с повреждением."""
    src: Path = lifecycle["data"]  # type: ignore[assignment]
    return _copy_tree(src, tmp_path_factory.mktemp("stand6_5_tpl") / "data")


# --- 1-5: первый прогон ---------------------------------------------------------------------


def test_acc01_exit_zero_and_photo_shape(lifecycle: dict[str, object]) -> None:
    rc, _out, err = lifecycle["first"]  # type: ignore[misc]
    assert rc == 0, err
    data: Path = lifecycle["data"]  # type: ignore[assignment]
    photo = imread_unicode(data / _PHOTO, cv2.IMREAD_UNCHANGED)
    assert photo.shape == (484, 598, 3)
    assert photo.dtype == np.uint8


def test_acc02_rail_rows_equal_truncated_median(lifecycle: dict[str, object]) -> None:
    data: Path = lifecycle["data"]  # type: ignore[assignment]
    built = imread_unicode(data / _PHOTO, cv2.IMREAD_COLOR)
    fixture = _fixture_photo()
    rows = np.array(_RAIL_ROWS)

    # std вдоль X == 0 по каждому каналу в каждой строке борта
    assert (built[rows].std(axis=1) == 0).all()

    # эталон — усечение; считается здесь из фикстуры
    expected = np.median(fixture[rows], axis=1).astype(np.uint8)  # (43, 3)
    assert (built[rows] == expected[:, None, :]).all()

    # чувствительность теста: округление дало бы другой эталон (спека: 7774 px на 1)
    rounded = np.round(np.median(fixture[rows], axis=1)).astype(np.uint8)
    assert (rounded != expected).any()


def test_acc03_body_rows_equal_fixture(lifecycle: dict[str, object]) -> None:
    data: Path = lifecycle["data"]  # type: ignore[assignment]
    built = imread_unicode(data / _PHOTO, cv2.IMREAD_COLOR)
    fixture = _fixture_photo()
    assert built.shape == fixture.shape
    assert np.array_equal(built[_BODY], fixture[_BODY])


def test_acc04_tile_shape_and_child_stdout(lifecycle: dict[str, object]) -> None:
    _rc, out, _err = lifecycle["first"]  # type: ignore[misc]
    data: Path = lifecycle["data"]  # type: ignore[assignment]
    tile = imread_unicode(data / _TILE, cv2.IMREAD_UNCHANGED)
    assert tile.shape == (484, 410, 4)
    assert "period_px=205" in out
    assert "size=410x484" in out


def test_acc05_letters_and_disk(lifecycle: dict[str, object]) -> None:
    data: Path = lifecycle["data"]  # type: ignore[assignment]
    _check_assets(data)


# --- 6-7: stdout, идемпотентность, --force --------------------------------------------------


def test_acc06a_first_run_status_lines(lifecycle: dict[str, object]) -> None:
    _rc, out, _err = lifecycle["first"]  # type: ignore[misc]
    assert _status_lines(out) == [
        f"built {_LINE_PHOTO}",
        f"built {_LINE_TILE}",
        f"built {_LINE_LETTERS}",
    ]


def test_acc06b_second_run_skips_and_keeps_files(lifecycle: dict[str, object]) -> None:
    rc, out, err = lifecycle["second"]  # type: ignore[misc]
    assert rc == 0, err
    assert _status_lines(out) == [
        f"skipped {_LINE_PHOTO}",
        f"skipped {_LINE_TILE}",
        f"skipped {_LINE_LETTERS}",
    ]
    before: dict = lifecycle["snap_first"]  # type: ignore[assignment]
    after: dict = lifecycle["snap_second"]  # type: ignore[assignment]
    assert len(before) == 11 and set(before) == set(after)
    for rel in before:
        assert after[rel][0] == before[rel][0], f"байты изменились: {rel}"
        assert after[rel][1] == before[rel][1], f"mtime_ns изменился: {rel}"


def test_acc07_force_rebuilds_everything(lifecycle: dict[str, object]) -> None:
    rc, out, err = lifecycle["forced"]  # type: ignore[misc]
    assert rc == 0, err
    assert _status_lines(out) == [
        f"built {_LINE_PHOTO}",
        f"built {_LINE_TILE}",
        f"built {_LINE_LETTERS}",
    ]
    before: dict = lifecycle["snap_second"]  # type: ignore[assignment]
    after: dict = lifecycle["snap_forced"]  # type: ignore[assignment]
    assert len(after) == 11
    for rel in before:
        assert after[rel][1] > before[rel][1], f"mtime_ns не вырос: {rel}"


# --- 8, 13, 14, 16: повреждения и пересборка по группам -------------------------------------


def test_acc08_missing_letter_file_rebuilds_only_letters(bsa: ModuleType, built_template: Path, tmp_path: Path) -> None:
    data = _copy_tree(built_template, tmp_path / "data")
    (data / "letters_ink" / "Х" / "DejaVuSansMono_s3.png").unlink()
    snap = _snapshot_existing(data, [_PHOTO, _TILE])

    rc, out, err = _run(bsa, ["--data-dir", str(data)])

    assert rc == 0, err
    assert _status_lines(out) == [
        f"skipped {_LINE_PHOTO}",
        f"skipped {_LINE_TILE}",
        f"built {_LINE_LETTERS}",
    ]
    assert len(_letters_files(data)) == 8
    _check_assets(data)
    for rel, (data_bytes, mtime) in snap.items():
        assert (data / rel).read_bytes() == data_bytes
        assert (data / rel).stat().st_mtime_ns == mtime


def test_acc13_missing_photo_rebuilds_photo_and_tile_not_letters(
    bsa: ModuleType, built_template: Path, tmp_path: Path
) -> None:
    data = _copy_tree(built_template, tmp_path / "data")
    (data / _PHOTO).unlink()
    old_tile_mtime = (data / _TILE).stat().st_mtime_ns
    letters_snap = _snapshot_existing(
        data, [f"letters_ink/{d}/{f}" for d in _LETTER_DIRS for f in _LETTER_FILES] + [_DISK]
    )

    rc, out, err = _run(bsa, ["--data-dir", str(data)])

    assert rc == 0, err
    assert _status_lines(out) == [
        f"built {_LINE_PHOTO}",
        f"built {_LINE_TILE}",
        f"skipped {_LINE_LETTERS}",
    ]
    assert (data / _TILE).stat().st_mtime_ns > old_tile_mtime
    for rel, (data_bytes, mtime) in letters_snap.items():
        assert (data / rel).read_bytes() == data_bytes
        assert (data / rel).stat().st_mtime_ns == mtime
    _check_assets(data)


def test_acc14_truncated_tile_is_rebuilt(bsa: ModuleType, built_template: Path, tmp_path: Path) -> None:
    data = _copy_tree(built_template, tmp_path / "data")
    (data / _TILE).write_bytes(b"")
    assert (data / _TILE).stat().st_size == 0

    rc, out, err = _run(bsa, ["--data-dir", str(data)])

    assert rc == 0, err
    assert f"built {_LINE_TILE}" in _status_lines(out)
    assert imread_unicode(data / _TILE, cv2.IMREAD_UNCHANGED).shape == (484, 410, 4)


def test_acc16_junk_in_letters_removed_and_disk_restored(bsa: ModuleType, built_template: Path, tmp_path: Path) -> None:
    data = _copy_tree(built_template, tmp_path / "data")
    junk = data / "letters_ink" / "А" / "junk.png"
    junk.write_bytes(b"not an image")
    (data / _DISK).unlink()

    rc, _out, err = _run(bsa, ["--data-dir", str(data)])

    assert rc == 0, err
    assert not junk.exists()
    assert len(_letters_files(data)) == 8
    assert sorted(p.name for p in _letters_files(data)) == sorted(_LETTER_FILES * 4)
    assert imread_unicode(data / _DISK, cv2.IMREAD_UNCHANGED).shape == (300, 300, 4)


def _snapshot_existing(data: Path, rels: list[str]) -> dict[str, tuple[bytes, int]]:
    return {rel: ((data / rel).read_bytes(), (data / rel).stat().st_mtime_ns) for rel in rels}


# --- 9: предпроверка ------------------------------------------------------------------------


def test_acc09_missing_fixtures_fail_preflight_without_writes(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    empty = tmp_path / "empty_fixtures"
    empty.mkdir()
    monkeypatch.setattr(bsa, "FIXTURES_DIR", empty)
    data = tmp_path / "data"

    rc, _out, err = _run(bsa, ["--data-dir", str(data)])

    assert rc != 0
    assert "preflight" in err
    assert not data.exists() or not any(data.iterdir())


# --- 10-12: путь --data-dir -----------------------------------------------------------------


def test_acc10_absolute_data_dir_independent_of_cwd(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    data = tmp_path / "data_abs"

    rc, out, err = _run(bsa, ["--data-dir", str(data)])

    assert rc == 0, err
    _check_assets(data)
    assert "period_px=205" in out and "size=410x484" in out
    assert not any(elsewhere.iterdir())  # в cwd ничего не оставлено


def test_acc11_relative_data_dir_resolves_from_repo_root(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    preset = importlib.import_module("Services.line_sim.core.preset")
    root = tmp_path / "root"
    cwd = tmp_path / "cwd"
    root.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(preset, "REPO_ROOT", root)
    monkeypatch.chdir(cwd)

    rc, _out, err = _run(bsa, ["--data-dir", "out"])

    assert rc == 0, err
    _check_assets(root / "out")
    assert not (cwd / "out").exists()


def test_acc12_cyrillic_and_space_data_dir(bsa: ModuleType, tmp_path: Path) -> None:
    data = tmp_path / "ассеты стенда"  # «ассеты стенда»

    rc, out, err = _run(bsa, ["--data-dir", str(data)])

    assert rc == 0, err
    _check_assets(data)
    assert _status_lines(out) == [
        f"built {_LINE_PHOTO}",
        f"built {_LINE_TILE}",
        f"built {_LINE_LETTERS}",
    ]


# --- 15: провал дочернего CLI ---------------------------------------------------------------


def test_acc15a_tile_child_nonzero_code_fails_step_tile(
    bsa: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mst = importlib.import_module("Services.line_sim.tools.make_seamless_texture")
    monkeypatch.setattr(mst, "main", lambda argv=None: 2)
    data = tmp_path / "data"

    rc, _out, err = _run(bsa, ["--data-dir", str(data)])

    assert rc == 1
    assert "ошибка шага tile" in err
    assert not (data / "letters_ink").exists()


def test_acc15b_letters_child_systemexit_fails_step_letters(
    bsa: ModuleType, built_template: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mfl = importlib.import_module("Services.line_sim.tools.make_font_letters")

    def boom(argv: list[str] | None = None) -> None:
        raise SystemExit("x")

    monkeypatch.setattr(mfl, "main", boom)
    data = _copy_tree(built_template, tmp_path / "data")
    shutil.rmtree(data / "letters_ink")  # фото и тайл готовы, группа letters обязана собираться

    rc, _out, err = _run(bsa, ["--data-dir", str(data)])

    assert rc == 1
    assert "ошибка шага letters" in err
