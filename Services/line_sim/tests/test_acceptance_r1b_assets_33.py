# -*- coding: utf-8 -*-
"""Task R1b — слепая приёмка ассетов стенда сима: весь алфавит, 33 буквы.

Контракт — ТОЛЬКО строки ACCEPTANCE и TESTS задачи R1b (``plans/line-sim/tasks/R1b.md``). Через публичный
``Services.line_sim.tools.build_stand_assets.main(["--data-dir", <tmp>])``. Worktree на коммите до реализации:
инструмент собирает 8 спрайтов (А К Р Х) — ожидаемый красный: число файлов 8 против 66, строка статуса
``built letters_ink 8 files, disk 300x300x4`` против ``built letters_ink 66 files, disk 300x300x4``.

Реальные записи — только в ``tmp_path``/``tmp_path_factory``; ``data/line_sim`` не трогается. Ожидаемые
значения — литералы ACCEPTANCE (33 папки ``Ё А Б ... Я``, 66 файлов, ``300x300x4``). Алфавит собран по кодовым
точкам (``Ё`` U+0401, ``А..Я`` U+0410..U+042F), а не набран, чтобы кириллица не смешалась с латиницей-двойником.

«Третья строка stdout» понята как третья СТРОКА СТАТУСА (префикс ``built `` / ``skipped ``, строки дочерних
CLI отфильтрованы), как в ``test_acceptance_6_5_stand_assets.py``; это вынесено в отчёт как неоднозначность.
Имена файлов в папке буквы (``DejaVuSans_s3.png``, ``DejaVuSansMono_s3.png``) взяты из соседних существующих
тестов, а не из ACCEPTANCE: в ACCEPTANCE сказано лишь «по 2 PNG RGBA».
"""

from __future__ import annotations

import io
import os
import shutil
import threading
import time
import unicodedata
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import cv2
import pytest

from Services.dataset_gen.core.catalog import imread_unicode

__all__: list[str] = []

_ALPHABET = [chr(0x0401)] + [chr(code) for code in range(0x0410, 0x0430)]  # Ё, А..Я
_OLD_LETTERS = ["А", "К", "Р", "Х"]  # А К Р Х — старые 8 спрайтов
_LETTER_FILES = ["DejaVuSans_s3.png", "DejaVuSansMono_s3.png"]
_LINE_LETTERS_BUILT = "built letters_ink 66 files, disk 300x300x4"
_RUN_DEADLINE_S = 600.0


def _run(argv: list[str]) -> tuple[int, str, str]:
    """``main(argv)`` в потоке-демоне с дедлайном; вернуть (код, stdout, stderr)."""
    from Services.line_sim.tools import build_stand_assets as bsa

    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["rc"] = bsa.main(argv)
        except SystemExit as exc:
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
    return [ln.rstrip("\r") for ln in stdout.splitlines() if ln.startswith(("built ", "skipped "))]


def _letter_files(data: Path) -> list[Path]:
    return sorted(p for p in (data / "letters_ink").rglob("*") if p.is_file())


def _snapshot(data: Path) -> dict[str, tuple[bytes, int]]:
    return {
        p.relative_to(data).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(data.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Один настоящий прогон на чистом tmp-каталоге: код, stdout, stderr, путь и время сборки (с)."""
    data = tmp_path_factory.mktemp("r1b_assets") / "data"
    started = time.perf_counter()
    rc, out, err = _run(["--data-dir", str(data)])
    elapsed = time.perf_counter() - started
    print(f"R1B_BUILD_SECONDS={elapsed:.2f}")  # для отчёта: `pytest -s`
    return {"rc": rc, "out": out, "err": err, "data": data, "seconds": elapsed}


def test_full_run_code_0_and_third_status_line(built: dict[str, object]) -> None:
    """ACCEPTANCE: ``main`` -> код 0, третья строка статуса ``built letters_ink 66 files, disk 300x300x4``.
    Ловит: набор букв, оставшийся на 4 (8 файлов), и старый литерал строки статуса."""
    assert built["rc"] == 0, built["err"]
    statuses = _status_lines(built["out"])  # type: ignore[arg-type]
    assert len(statuses) == 3, statuses
    assert statuses[2] == _LINE_LETTERS_BUILT, statuses


def test_letters_ink_33_folders_two_rgba_pngs_each(built: dict[str, object]) -> None:
    """ACCEPTANCE: в ``letters_ink`` 33 папки с именами ``Ё А Б ... Я``, в каждой ровно 2 PNG RGBA, всего 66.
    Ловит: пропущенную букву (``Ё``/``Й``/``Ъ``/``Ы``/``Ь``), лишнюю папку, файл не RGBA, неверное число файлов."""
    assert built["rc"] == 0, built["err"]
    data: Path = built["data"]  # type: ignore[assignment]
    root = data / "letters_ink"

    assert sorted(p.name for p in root.iterdir()) == sorted(_ALPHABET)
    assert all(p.is_dir() for p in root.iterdir())
    for letter in _ALPHABET:
        names = sorted(p.name for p in (root / letter).iterdir())
        assert names == sorted(_LETTER_FILES), (letter, names)
        for name in names:
            image = imread_unicode(root / letter / name, cv2.IMREAD_UNCHANGED)
            assert image is not None and image.ndim == 3 and image.shape[2] == 4, (
                letter,
                name,
                None if image is None else image.shape,
            )
    assert len(_letter_files(data)) == 66


def test_second_run_skipped_and_files_untouched(built: dict[str, object]) -> None:
    """ACCEPTANCE: второй запуск без ``--force`` -> ``skipped letters_ink 66 files, ...`` третьей строкой статуса,
    ни одной строки ``built``, байты и mtime файлов не изменились.
    Ловит: пересборку полного каталога из 33 букв при каждом запуске."""
    assert built["rc"] == 0, built["err"]
    data: Path = built["data"]  # type: ignore[assignment]
    before = _snapshot(data)

    rc, out, err = _run(["--data-dir", str(data)])

    assert rc == 0, err
    statuses = _status_lines(out)
    assert len(statuses) == 3, statuses
    assert all(line.startswith("skipped ") for line in statuses), statuses
    assert statuses[2].startswith("skipped letters_ink 66 files, "), statuses
    assert _snapshot(data) == before


def test_old_8_sprite_catalog_rebuilt(built: dict[str, object], tmp_path: Path) -> None:
    """ACCEPTANCE: каталог на 8 спрайтов (А К Р Х) пересобирается -> ``built letters_ink 66 files, ...``,
    после — 33 папки и 66 файлов. Ловит: приём старого полного набора 4 букв за «готово» (``skipped``)."""
    assert built["rc"] == 0, built["err"]
    source: Path = built["data"]  # type: ignore[assignment]
    data = tmp_path / "data"
    shutil.copytree(source, data)
    for folder in (data / "letters_ink").iterdir():
        if folder.name not in _OLD_LETTERS:
            shutil.rmtree(folder)
    assert len(_letter_files(data)) == 8  # фикстура: ровно старый каталог

    rc, out, err = _run(["--data-dir", str(data)])

    assert rc == 0, err
    statuses = _status_lines(out)
    assert len(statuses) == 3, statuses
    assert statuses[2] == _LINE_LETTERS_BUILT, statuses
    assert len(_letter_files(data)) == 66
    assert sorted(p.name for p in (data / "letters_ink").iterdir()) == sorted(_ALPHABET)


def test_load_catalog_sees_33_classes_in_nfc(built: dict[str, object]) -> None:
    """ACCEPTANCE: ``load_catalog(<tmp>/letters_ink)`` -> ``num_classes == 33``, ``class_names`` = ``Ё А Б ... Я``;
    все имена классов и папок в NFC (``Ё`` и ``Й`` — одна кодовая точка, не разложенные).
    Ловит: 4 класса вместо 33, папки в NFD (``Й`` как ``И`` + breve), неверный порядок/состав имён."""
    from Services.layer_render.catalog import load_catalog

    assert built["rc"] == 0, built["err"]
    data: Path = built["data"]  # type: ignore[assignment]
    catalog = load_catalog(data / "letters_ink")

    assert catalog.num_classes == 33
    assert list(catalog.class_names) == _ALPHABET
    assert all(unicodedata.is_normalized("NFC", name) for name in catalog.class_names)
    assert all(unicodedata.is_normalized("NFC", name) for name in os.listdir(data / "letters_ink"))
