"""Авторские hazard-тесты Task 1.2 (line-sim-belt-look) — краска букв и диск из фото.

Что может сломаться именно в ЭТОМ механизме (независимая приёмка — `test_acceptance_look_1_2_ink_disk.py`):

* зерно — сумма uint8 + гауссов шум: без float/clip значение оборачивается (255 + 20 -> 19), и на
  белой краске появляются тёмные точки, на чёрной — яркие; среднее и σ почти не выдают это;
* зерно и цвет применяются по маске «альфа > 0»: сдвиг маски или шум по всему массиву даёт «гало»
  из шумного RGB в прозрачности (в файле его не видно, но при наложении на ленту оно всплывает);
* `--disk-from-photo` без `--disk-out` должен падать разбором аргументов ДО записи чего-либо;
* круг у самого края фото — вырез квадрата `[c-r, c+r]` уходит за массив: срез numpy молча
  обрезался бы (и размер вырезки поплыл бы) либо дал IndexError;
* `_disk_alpha` вынесен из `build_disk` рефакторингом — вывод обязан остаться байт в байт прежним
  (SHA-256 сырого массива снят ДО рефакторинга, литералы ниже).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import matplotlib
import numpy as np
import pytest

from Services.dataset_gen.core.catalog import imwrite_unicode
from Services.line_sim.tools.make_font_letters import _finish_ink, build_disk, build_disk_from_photo, main

DEJAVU_SANS = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"

# SHA-256 `build_disk(N).tobytes()`, снят на 36823b82 (до выноса `_disk_alpha`).
GOLDEN_DISK_RAW_300 = "55598e38898b83cc3584343843fa8235bdffe28fbea2386896a48fb129b6bd40"
GOLDEN_DISK_RAW_64 = "c5a97c033cfab7e7481f28f44467765303e317a21c1f9eac063165b65766c14b"


def _solid_rgba(color: tuple[int, int, int], alpha: int, size: int = 100) -> np.ndarray:
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    rgba[:, :, 0:3] = color
    rgba[:, :, 3] = alpha
    return rgba


def test_grain_clips_instead_of_wrapping_on_white_ink() -> None:
    """Белая краска + σ 50: положительный шум обязан прижаться к 255 (~половина пикселей), а не
    обернуться в малые значения. Обёртка дала бы долю ==255 около 1 % и мелкие «чёрные» точки."""
    out = _finish_ink(_solid_rgba((0, 0, 0), 255), (255, 255, 255), 50.0, 0.0, np.random.default_rng(1))
    rgb = out[:, :, 0:3]
    assert np.mean(rgb == 255) > 0.45, f"доля 255 = {np.mean(rgb == 255):.3f}, ожидали > 0.45 (клип)"
    assert np.median(rgb) >= 250, f"медиана {np.median(rgb)}: положительный шум не прижат к 255"


def test_grain_clips_instead_of_wrapping_on_black_ink() -> None:
    """Чёрная краска + σ 50: отрицательный шум прижимается к 0, обёртка дала бы яркие точки (~250)."""
    out = _finish_ink(_solid_rgba((255, 255, 255), 255), (0, 0, 0), 50.0, 0.0, np.random.default_rng(1))
    rgb = out[:, :, 0:3]
    assert np.mean(rgb == 0) > 0.45, f"доля 0 = {np.mean(rgb == 0):.3f}, ожидали > 0.45 (клип)"
    assert int(np.percentile(rgb, 50)) <= 5, f"медиана {np.median(rgb)}: отрицательный шум не прижат к 0"
    # обёртка -1..-30 -> 226..255: ~23 % пикселей; честный шум > 4.5 σ (225) — доли процента.
    assert np.mean(rgb > 225) < 0.005, f"доля ярких {np.mean(rgb > 225):.3f} на чёрной краске — признак обёртки"


def test_grain_and_ink_leave_transparent_pixels_untouched() -> None:
    """Пиксели с альфа == 0 сохраняют исходный RGB (10, 20, 30): ни цвет краски, ни зерно туда не
    просачиваются. Правая половина непрозрачная — контроль, что зерно вообще применилось."""
    rgba = _solid_rgba((10, 20, 30), 0)
    rgba[:, 50:, 3] = 255
    out = _finish_ink(rgba, (200, 200, 200), 9.0, 0.0, np.random.default_rng(3))
    left = out[:, :50]
    assert (left[:, :, 0] == 10).all() and (left[:, :, 1] == 20).all() and (left[:, :, 2] == 30).all(), (
        "RGB прозрачных пикселей изменился"
    )
    assert (left[:, :, 3] == 0).all()
    assert out[:, 50:, 0:3].std() > 5, "на непрозрачной половине зерна нет — контроль не сработал"


def test_blur_leaves_far_transparent_pixels_untouched() -> None:
    """С мягким краем маска «альфа > 0» расширяется на пару пикселей, но далёкая прозрачность
    (>= 10 px от края) остаётся с исходным RGB (10, 20, 30)."""
    rgba = _solid_rgba((10, 20, 30), 0)
    rgba[40:60, 40:60, 3] = 255
    out = _finish_ink(rgba, (200, 200, 200), 9.0, 1.0, np.random.default_rng(3))
    corner = out[0:20, 0:20]
    assert (corner[:, :, 0] == 10).all() and (corner[:, :, 1] == 20).all() and (corner[:, :, 2] == 30).all()
    assert (corner[:, :, 3] == 0).all()
    assert out[45:55, 45:55, 3].min() == 255, "ядро квадрата после blur 1 px потеряло непрозрачность"


def test_finish_ink_defaults_return_array_untouched() -> None:
    """Без опций — тот же объект и те же байты (иначе побайтовая совместимость с прежним выводом)."""
    rgba = _solid_rgba((0, 0, 0), 255)
    snapshot = rgba.copy()
    assert _finish_ink(rgba, None, 0.0, 0.0, np.random.default_rng(0)) is rgba
    assert np.array_equal(rgba, snapshot)


def test_disk_from_photo_without_disk_out_is_parser_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--disk-from-photo` без `--disk-out` -> argparse-выход с кодом 2, каталог `--out` не создан."""
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--letters",
                "А",
                "--font",
                str(DEJAVU_SANS),
                "--out",
                str(out),
                "--disk-from-photo",
                str(tmp_path / "any.png"),
            ]
        )
    assert exc.value.code == 2
    assert "--disk-out" in capsys.readouterr().err
    assert not out.exists(), "при ошибке разбора аргументов что-то уже записано на диск"


@pytest.mark.parametrize("bad", ["300,0,0", "1,2", "a,b,c", "-1,0,0", "1,2,3,4"])
def test_bad_ink_rgb_is_parser_error(bad: str, tmp_path: Path) -> None:
    """Неверный `--ink-rgb` -> код 2 до какой-либо записи."""
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(["--letters", "А", "--font", str(DEJAVU_SANS), "--out", str(out), "--ink-rgb", bad])
    assert exc.value.code == 2
    assert not out.exists()


def test_disk_from_photo_pads_circle_touching_border(tmp_path: Path) -> None:
    """Диск радиусом 60 ровно вписан в фото 121x121 (касается всех четырёх краёв): вырез квадрата
    доходит до границы массива. Не IndexError, размер результата == size_px, углы прозрачны, центр непрозрачен."""
    photo = np.full((121, 121, 3), 30, dtype=np.uint8)
    cv2.circle(photo, (60, 60), 60, (235, 235, 235), thickness=-1)
    path = tmp_path / "tight.png"
    imwrite_unicode(path, photo)

    rgba = build_disk_from_photo(path, 64)

    assert rgba.shape == (64, 64, 4)
    assert rgba[0, 0, 3] == 0 and rgba[63, 63, 3] == 0, "углы канвы должны быть прозрачны"
    assert rgba[32, 32, 3] == 255
    assert abs(int(rgba[32, 32, 0]) - 235) <= 3, f"центр диска {rgba[32, 32, 0:3]} не похож на светлое фото"


def test_disk_from_photo_pads_when_crop_leaves_the_array(tmp_path: Path) -> None:
    """Диск (центр 58, r 60) в фото 100x100 срезан краем: найденный круг ~(56.7, 56.7, r 59.8), вырез
    `[c-r, c+r]` начинается с x0 = y0 = -3 (замер зонда) — за массивом слева/сверху. Обязано собраться
    без IndexError и без отказа: 64x64, центр непрозрачный и светлый, углы прозрачны."""
    photo = np.full((100, 100, 3), 30, dtype=np.uint8)
    cv2.circle(photo, (58, 58), 60, (235, 235, 235), thickness=-1)
    path = tmp_path / "clipped.png"
    imwrite_unicode(path, photo)

    rgba = build_disk_from_photo(path, 64)

    assert rgba.shape == (64, 64, 4)
    assert rgba[32, 32, 3] == 255 and abs(int(rgba[32, 32, 0]) - 235) <= 3
    assert rgba[0, 0, 3] == 0 and rgba[63, 63, 3] == 0


def test_build_disk_bytes_unchanged_after_alpha_refactor() -> None:
    """`_disk_alpha` вынесен из `build_disk` — сырой массив обязан совпасть с литералами до рефакторинга."""
    assert hashlib.sha256(build_disk(300).tobytes()).hexdigest() == GOLDEN_DISK_RAW_300
    assert hashlib.sha256(build_disk(64).tobytes()).hexdigest() == GOLDEN_DISK_RAW_64
