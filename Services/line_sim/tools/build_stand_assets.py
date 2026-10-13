# -*- coding: utf-8 -*-
"""Собрать ассеты стенда line_sim (`data/line_sim`) одной командой из закоммиченных фикстур.

Purpose:
    `data/` вне git, а стенду нужны фото ленты, плитка ленты и каталог букв. Модуль строит их
    из фикстур `Services/line_sim/tests/fixtures` (`belt_photo_full.png`, `real_disk_snapshot.png`)
    и шрифтов DejaVu из matplotlib. Три группы: `photo` (`belt_photo_full.png`), `tile`
    (`belt_tile.png`), `letters` (`letters_ink/<буква>/*.png` и `letters_ink_disk.png`).
    Борта фото выравниваются медианой строки вдоль X (belt-look «Итог 1.3»): без этого
    `make_seamless_texture --force-period` берёт одно звено (205x484), а не два (410x484).

Public API:
    ``main(argv) -> int`` и CLI ``python -m Services.line_sim.tools.build_stand_assets
    [--data-dir data/line_sim] [--force]``; константа ``FIXTURES_DIR`` (читается при вызове ``main``).

Stability: lite

Идемпотентность по группам: группа готова, только если ВСЕ её файлы существуют и читаются
обратно через ``imread_unicode``; иначе пересобирается вся группа целиком (каталог букв
перед этим удаляется: лишний файл в ``letters_ink/<буква>/`` стал бы образцом класса, LS-014).
Собранное фото всегда тянет пересборку тайла. ``--force`` пересобирает все три группы.

Вывод: три строки ``built|skipped <имя> <размер>`` в stdout (порядок photo, tile, letters);
провал шага — ``ошибка шага <photo|tile|letters|preflight>: <причина>`` в stderr и код 1.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode
from Services.line_sim.core import preset
from Services.line_sim.tools import make_font_letters, make_seamless_texture

__all__ = ["FIXTURES_DIR", "main"]

#: Закоммиченные фикстуры сборки. Читается в момент вызова `main` (тесты подменяют).
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

_DEFAULT_DATA_DIR = "data/line_sim"

_PHOTO = "belt_photo_full.png"
_TILE = "belt_tile.png"
_LETTERS_DIR = "letters_ink"
_DISK = "letters_ink_disk.png"
_DISK_SNAPSHOT = "real_disk_snapshot.png"

# belt-look: тело — кропы y 22..462, борта — строки реального кадра; медиана вдоль X с усечением —
# Итог 1.3, оригинал data/line_sim_original_2026-09-30.
_RAIL_TOP_ROWS = range(0, 22)
_RAIL_BOTTOM_ROWS = range(463, 484)

_LETTERS = "АКРХ"
_FONTS = ("DejaVuSans", "DejaVuSansMono")
_STROKE_PX = 3


class _StepError(Exception):
    """Провал шага сборки: `step` и причина уходят в stderr, код возврата 1."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason


def _font_path(name: str) -> Path:
    import matplotlib

    return Path(matplotlib.get_data_path()) / "fonts" / "ttf" / f"{name}.ttf"


def _readable_shape(path: Path) -> tuple[int, ...] | None:
    """Форма изображения, прочитанного через `imread_unicode` (с альфой); `None` — нет или нечитаемо."""
    if not path.is_file():
        return None
    try:
        return tuple(imread_unicode(path, cv2.IMREAD_UNCHANGED).shape)
    except Exception:  # noqa: BLE001 - нечитаемый файл == группа не готова
        return None


def _size(shape: tuple[int, ...]) -> str:
    height, width, channels = shape
    return f"{width}x{height}x{channels}"


def _letter_files(data: Path) -> list[Path]:
    return [data / _LETTERS_DIR / letter / f"{font}_s{_STROKE_PX}.png" for letter in _LETTERS for font in _FONTS]


def _group_files(data: Path) -> dict[str, list[Path]]:
    return {
        "photo": [data / _PHOTO],
        "tile": [data / _TILE],
        "letters": [*_letter_files(data), data / _DISK],
    }


def _is_ready(files: list[Path]) -> bool:
    return all(_readable_shape(path) is not None for path in files)


def _preflight(fixtures: Path) -> None:
    required = [
        fixtures / _PHOTO,
        fixtures / _DISK_SNAPSHOT,
        *(_font_path(font) for font in _FONTS),
    ]
    for path in required:
        if not path.is_file():
            raise _StepError("preflight", f"{path} не найден")


def _build_photo(fixtures: Path, data: Path) -> None:
    """Фото = фикстура с бортами, выровненными медианой строки вдоль X (усечение)."""
    try:
        # Тайл строится только из этого фото: упавший прогон не должен оставить старый тайл рядом с новым фото.
        (data / _TILE).unlink(missing_ok=True)
        image = imread_unicode(fixtures / _PHOTO, cv2.IMREAD_COLOR)
        for rows in (_RAIL_TOP_ROWS, _RAIL_BOTTOM_ROWS):
            index = list(rows)
            image[index] = np.median(image[index], axis=1).astype(np.uint8)[:, None, :]
        imwrite_unicode(data / _PHOTO, image)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - любой провал = ошибка шага
        raise _StepError("photo", f"{type(exc).__name__}: {exc}") from exc


def _build_tile(data: Path) -> None:
    try:
        code = make_seamless_texture.main(
            [str(data / _PHOTO), "--out", str(data / _TILE), "--force-period", "--gap-alpha"]
        )
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        raise _StepError("tile", f"{type(exc).__name__}: {exc}") from exc
    if code:
        raise _StepError("tile", f"make_seamless_texture вернул код {code}")


def _build_letters(fixtures: Path, data: Path) -> None:
    try:
        # make_font_letters не чистит --out: лишний файл станет образцом класса (LS-014).
        if (data / _LETTERS_DIR).exists():
            shutil.rmtree(data / _LETTERS_DIR)
        for font in _FONTS:
            make_font_letters.main(
                [
                    "--letters", _LETTERS,
                    "--font", str(_font_path(font)),
                    "--stroke-px", str(_STROKE_PX),
                    "--size-px", "300",
                    "--letter-frac", "0.4763",
                    "--ink-rgb", "65,70,82",
                    "--grain-sigma", "9",
                    "--edge-blur-px", "1",
                    "--seed", "1",
                    "--disk-from-photo", str(fixtures / _DISK_SNAPSHOT),
                    "--out", str(data / _LETTERS_DIR),
                    "--disk-out", str(data / _DISK),
                ]
            )  # fmt: skip
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        raise _StepError("letters", f"{type(exc).__name__}: {exc}") from exc


def _status(verb: str, step: str, files: list[Path]) -> str:
    """Строка статуса; размеры берутся из файлов, прочитанных обратно."""
    shapes = [_readable_shape(path) for path in files]
    if any(shape is None for shape in shapes):
        raise _StepError(step, "собранный файл не читается обратно")
    if step == "photo":
        return f"{verb} {_PHOTO} {_size(shapes[0])}"  # type: ignore[arg-type]
    if step == "tile":
        return f"{verb} {_TILE} {_size(shapes[0])}"  # type: ignore[arg-type]
    return f"{verb} {_LETTERS_DIR} {len(files) - 1} files, disk {_size(shapes[-1])}"  # type: ignore[arg-type]


def _run(data: Path, fixtures: Path, force: bool) -> None:
    groups = _group_files(data)
    builders: dict[str, Callable[[], None]] = {
        "photo": lambda: _build_photo(fixtures, data),
        "tile": lambda: _build_tile(data),
        "letters": lambda: _build_letters(fixtures, data),
    }
    photo_built = False
    for step, files in groups.items():
        rebuild = force or not _is_ready(files) or (step == "tile" and photo_built)
        if rebuild:
            builders[step]()
        photo_built = photo_built or (step == "photo" and rebuild)
        print(_status("built" if rebuild else "skipped", step, files), flush=True)


def main(argv: list[str] | None = None) -> int:
    """Собрать `photo`, `tile`, `letters` в `--data-dir`; вернуть код процесса.

    Pre:
      - `FIXTURES_DIR` содержит `belt_photo_full.png` и `real_disk_snapshot.png`;
        в matplotlib есть шрифты `DejaVuSans.ttf` и `DejaVuSansMono.ttf`;
      - `--data-dir`: относительный путь считается от `preset.REPO_ROOT`, абсолютный берётся как есть.
    Post:
      - 0: в `--data-dir` все 11 файлов читаются, в stdout три строки `built|skipped ...`;
        готовая группа без `--force` не переписана (байты и mtime целы);
      - 1: в stderr `ошибка шага <имя>: <причина>`, группы после упавшей не строились;
        при провале предпроверки (`preflight`) на диск не записано ничего, каталога нет.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=_DEFAULT_DATA_DIR, help=f"каталог ассетов (дефолт {_DEFAULT_DATA_DIR})")
    parser.add_argument("--force", action="store_true", help="пересобрать все три группы")
    args = parser.parse_args(argv)

    fixtures = FIXTURES_DIR
    data = Path(preset.resolve_repo_path(args.data_dir))  # type: ignore[arg-type]
    try:
        _preflight(fixtures)
        try:
            data.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _StepError("preflight", f"каталог {data} не создан: {exc}") from exc
        _run(data, fixtures, args.force)
    except _StepError as exc:
        print(f"ошибка шага {exc.step}: {exc.reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
