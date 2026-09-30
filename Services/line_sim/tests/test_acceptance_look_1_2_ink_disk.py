"""RED-приёмка Task 1.2 (line-sim-belt-look) — `make_font_letters`: краска (цвет, зерно, мягкий край)
и диск из реального фото.

Независимый тест (blind): пишется ДО реализации, по критериям Task 1.2 из
`plans/line-sim-belt-look/plan.md`. Инструмент управляется только через `main([...])`, вывод — в tmp_path.

Эталонные SHA-256 без новых флагов сняты на коммите ДО реализации (1a2bba9b) и вписаны литералами:
буква `А`, DejaVuSans.ttf, --size-px 300 --letter-frac 0.6, плюс --disk-out. Они зависят от версий
matplotlib-шрифта/Pillow/OpenCV-PNG-кодера — при смене окружения побайтовый тест может покраснеть без
регресса в коде (тогда пересобрать эталон на коммите до задачи, а не подгонять под новый код).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import matplotlib
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imread_unicode, imwrite_unicode
from Services.line_sim.tools.make_font_letters import main

FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
DEJAVU_SANS = FONT_DIR / "DejaVuSans.ttf"
FIXTURE_DISK = Path(__file__).resolve().parent / "fixtures" / "real_disk_snapshot.png"

# Эталон: вывод на коммите до задачи (не считается в тесте).
GOLDEN_LETTER_SHA256 = "f65c8b62da4c39ba87b24a8ae5cd1560281c2473609fd82efaab4464ea8819b2"
GOLDEN_DISK_SHA256 = "2c082660fa7b4046cc20c6fa8f672f564489393d3ad3fb4521071e42da5e47b7"

SIZE_PX = 300
INK = (65, 70, 82)


@pytest.fixture(autouse=True)
def _inputs_exist() -> None:
    """GREEN-контроль входов: шрифт и фото-фикстура реально есть (иначе красное было бы не про фичу)."""
    assert DEJAVU_SANS.is_file(), f"шрифт не найден: {DEJAVU_SANS}"
    assert FIXTURE_DISK.is_file(), f"фикстура не найдена: {FIXTURE_DISK}"


def _run(out_dir: Path, *extra: str) -> Path:
    """Запуск инструмента для буквы А; возвращает путь к PNG буквы."""
    main(
        [
            "--letters",
            "А",
            "--font",
            str(DEJAVU_SANS),
            "--size-px",
            str(SIZE_PX),
            "--letter-frac",
            "0.6",
            "--out",
            str(out_dir),
            *extra,
        ]
    )
    return out_dir / "А" / "DejaVuSans.png"


def _read_rgba(path: Path) -> np.ndarray:
    """PNG пишется BGRA (imwrite_unicode) — для проверок цвета переводим в RGBA."""
    bgra = imread_unicode(path, cv2.IMREAD_UNCHANGED)
    assert bgra is not None and bgra.ndim == 3 and bgra.shape[2] == 4, f"{path}: не RGBA-картинка"
    return cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semi_count(rgba: np.ndarray) -> int:
    a = rgba[:, :, 3]
    return int(np.count_nonzero((a > 0) & (a < 255)))


def test_no_new_flags_output_is_byte_identical_to_golden(tmp_path: Path) -> None:
    """Без новых флагов буква и диск — байт в байт как до задачи (литералы SHA-256)."""
    disk_path = tmp_path / "disk.png"
    letter_path = _run(tmp_path / "out", "--disk-out", str(disk_path))
    assert _sha256(letter_path) == GOLDEN_LETTER_SHA256, "PNG буквы изменился без новых флагов"
    assert _sha256(disk_path) == GOLDEN_DISK_SHA256, "PNG диска изменился без новых флагов"


def test_ink_color_and_grain(tmp_path: Path) -> None:
    """--ink-rgb 65,70,82 --grain-sigma 9 --seed 1: у α=255 пикселей буквы медиана RGB в ±3 от цвета
    краски, σ по каждому каналу в [6, 12]."""
    letter_path = _run(tmp_path / "out", "--ink-rgb", "65,70,82", "--grain-sigma", "9", "--seed", "1")
    rgba = _read_rgba(letter_path)
    solid = rgba[rgba[:, :, 3] == 255][:, 0:3].astype(np.float64)
    assert solid.shape[0] > 1000, f"слишком мало непрозрачных пикселей буквы: {solid.shape[0]}"
    median = np.median(solid, axis=0)
    std = solid.std(axis=0)
    for ch, name in enumerate("RGB"):
        assert abs(median[ch] - INK[ch]) <= 3, f"медиана {name}={median[ch]}, ожидали {INK[ch]}±3"
        assert 6 <= std[ch] <= 12, f"σ по каналу {name}={std[ch]:.2f}, ожидали 6..12"


def test_seed_determinism(tmp_path: Path) -> None:
    """Тот же --seed — файл байт в байт; другой --seed — файл отличается."""
    flags = ("--ink-rgb", "65,70,82", "--grain-sigma", "9")
    a = _run(tmp_path / "a", *flags, "--seed", "1")
    b = _run(tmp_path / "b", *flags, "--seed", "1")
    c = _run(tmp_path / "c", *flags, "--seed", "2")
    assert _sha256(a) == _sha256(b), "один и тот же --seed дал разные байты"
    assert _sha256(a) != _sha256(c), "разные --seed дали одинаковые байты"


def test_edge_blur_widens_soft_band(tmp_path: Path) -> None:
    """--edge-blur-px 1: полупрозрачных пикселей (0<α<255) строго больше, чем без флага,
    непрозрачное ядро буквы (α=255) сохраняется."""
    plain = _read_rgba(_run(tmp_path / "plain"))
    blurred = _read_rgba(_run(tmp_path / "blur", "--edge-blur-px", "1"))
    assert _semi_count(blurred) > _semi_count(plain), (
        f"полупрозрачных с blur {_semi_count(blurred)}, без {_semi_count(plain)}"
    )
    assert int(np.count_nonzero(blurred[:, :, 3] == 255)) > 0, "непрозрачное ядро буквы исчезло"


def _radial_alpha_edge_width(alpha: np.ndarray) -> float:
    """Ширина перехода α 90% -> 10% по радиальному профилю вокруг центра канвы.
    Профиль — средняя α по кольцам шириной 0.25 px; пересечения ищутся снаружи внутрь от r=100."""
    h, w = alpha.shape
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - (w - 1) / 2.0, yy - (h - 1) / 2.0)
    step = 0.25
    bins = np.floor(r / step).astype(int)
    sums = np.bincount(bins.ravel(), weights=alpha.ravel().astype(np.float64))
    counts = np.bincount(bins.ravel())
    prof = sums / np.maximum(counts, 1)
    radii = (np.arange(len(prof)) + 0.5) * step
    start = int(100 / step)
    r90 = next(radii[i] for i in range(start, len(prof)) if prof[i] <= 0.9 * 255)
    r10 = next(radii[i] for i in range(start, len(prof)) if prof[i] <= 0.1 * 255)
    return float(r10 - r90)


def test_disk_from_photo_erases_print_and_is_round(tmp_path: Path) -> None:
    """--disk-from-photo real_disk_snapshot.png: RGBA 300x300; в круге r<135 печать стёрта
    (нет пикселей темнее 150, медиана яркости >= 230); угол канвы α=0; край 10->90% шире 1 и уже 5 px."""
    disk_path = tmp_path / "disk_photo.png"
    _run(tmp_path / "out", "--disk-from-photo", str(FIXTURE_DISK), "--disk-out", str(disk_path))
    rgba = _read_rgba(disk_path)
    assert rgba.shape == (SIZE_PX, SIZE_PX, 4), f"shape={rgba.shape}, ожидали (300,300,4)"

    yy, xx = np.mgrid[0:SIZE_PX, 0:SIZE_PX]
    r = np.hypot(xx - (SIZE_PX - 1) / 2.0, yy - (SIZE_PX - 1) / 2.0)
    inside = rgba[r < 135][:, 0:3].astype(np.float64)
    lum = 0.299 * inside[:, 0] + 0.587 * inside[:, 1] + 0.114 * inside[:, 2]
    assert lum.min() >= 150, f"в круге r<135 есть тёмный пиксель (яркость {lum.min():.1f}) — печать не стёрта"
    assert np.median(lum) >= 230, f"медиана яркости круга {np.median(lum):.1f} < 230"

    for y, x in ((0, 0), (0, SIZE_PX - 1), (SIZE_PX - 1, 0), (SIZE_PX - 1, SIZE_PX - 1)):
        assert rgba[y, x, 3] == 0, f"угол канвы ({y},{x}) α={rgba[y, x, 3]}, ожидали 0"

    width = _radial_alpha_edge_width(rgba[:, :, 3])
    assert 1 < width < 5, f"ширина края 10->90% = {width:.2f} px, ожидали строго в (1, 5)"


def test_disk_from_photo_without_circle_exits_with_path(tmp_path: Path) -> None:
    """Сплошное серое фото 340x340 -> SystemExit с сообщением-строкой, в котором путь фото
    (не argparse-код 2: иначе тест был бы зелёным по неверной причине)."""
    photo = tmp_path / "solid_gray.png"
    imwrite_unicode(photo, np.full((340, 340, 3), 128, dtype=np.uint8))
    assert photo.is_file(), "не удалось записать серое фото — контроль входа"

    with pytest.raises(SystemExit) as exc:
        _run(tmp_path / "out", "--disk-from-photo", str(photo), "--disk-out", str(tmp_path / "d.png"))

    code = exc.value.code
    assert isinstance(code, str), f"SystemExit.code={code!r}: ждали текст ошибки, а не код выхода"
    assert str(photo) in code or photo.as_posix() in code, f"в сообщении нет пути {photo}: {code!r}"
