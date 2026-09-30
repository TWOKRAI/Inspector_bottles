"""Авторские hazard-тесты Task 1.2 (line-sim-belt-look) — краска букв и диск из фото.

Что может сломаться именно в ЭТОМ механизме (независимая приёмка — `test_acceptance_look_1_2_ink_disk.py`):

* зерно — сумма uint8 + гауссов шум: без float/clip значение оборачивается (255 + 20 -> 19), и на
  белой краске появляются тёмные точки, на чёрной — яркие; среднее и σ почти не выдают это;
* цвет краски пишется во ВСЕ пиксели, зерно — только где «альфа > 0»: чёрный RGB прозрачных
  соседей при масштабировании (`LayeredObject._transform`, без премультипликации) затемняет кромку,
  а шум по всему массиву даёт «гало» из шумного RGB в прозрачности;
* `--disk-from-photo` без `--disk-out` должен падать разбором аргументов ДО записи чего-либо;
* вырез фото-диска: центр круга должен попасть в центр выреза (сдвиг на 0.5 px открывает кромку
  ленты под альфой), а размытая альфа не должна упираться в край канвы (ступенька на крайних строках);
* нечитаемое фото (в т.ч. пустой файл -> `cv2.error`) — отказ с путём и без единого файла в `--out`;
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
from Services.line_sim.core.layered_object import LayeredObject
from Services.line_sim.tools.make_font_letters import (
    _finish_ink,
    _render_letter,
    build_disk,
    build_disk_from_photo,
    main,
)

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


def test_grain_leaves_transparent_pixels_untouched() -> None:
    """Только зерно (без краски): пиксели с альфа == 0 сохраняют исходный RGB (10, 20, 30), шум туда не
    просачивается. Правая половина непрозрачная — контроль, что зерно вообще применилось."""
    rgba = _solid_rgba((10, 20, 30), 0)
    rgba[:, 50:, 3] = 255
    out = _finish_ink(rgba, None, 9.0, 0.0, np.random.default_rng(3))
    left = out[:, :50]
    assert (left[:, :, 0] == 10).all() and (left[:, :, 1] == 20).all() and (left[:, :, 2] == 30).all(), (
        "RGB прозрачных пикселей изменился"
    )
    assert (left[:, :, 3] == 0).all()
    assert out[:, 50:, 0:3].std() > 5, "на непрозрачной половине зерна нет — контроль не сработал"


def test_ink_fills_transparent_pixels_without_grain() -> None:
    """Краска пишется во ВСЕ пиксели (color bleed при интерполяции: у прозрачных соседей не должно быть
    чёрного RGB), альфа не трогается, а в прозрачных пикселях RGB == краска БЕЗ шума."""
    rgba = _solid_rgba((10, 20, 30), 0)
    rgba[:, 50:, 3] = 255
    out = _finish_ink(rgba, (200, 150, 100), 9.0, 0.0, np.random.default_rng(3))
    left = out[:, :50]
    assert (left[:, :, 0] == 200).all() and (left[:, :, 1] == 150).all() and (left[:, :, 2] == 100).all()
    assert (left[:, :, 3] == 0).all() and (out[:, 50:, 3] == 255).all(), "альфа изменилась"
    assert out[:, 50:, 0:3].std() > 5, "на непрозрачной половине зерна нет — контроль не сработал"


def test_blur_far_transparent_pixels_get_flat_ink() -> None:
    """С мягким краем зерно ложится по расширенной маске «альфа > 0», а далёкая прозрачность
    (>= 10 px от края) — ровный цвет краски без шума."""
    rgba = _solid_rgba((10, 20, 30), 0)
    rgba[40:60, 40:60, 3] = 255
    out = _finish_ink(rgba, (200, 150, 100), 9.0, 1.0, np.random.default_rng(3))
    corner = out[0:20, 0:20]
    assert (corner[:, :, 0] == 200).all() and (corner[:, :, 1] == 150).all() and (corner[:, :, 2] == 100).all()
    assert (corner[:, :, 3] == 0).all()
    assert out[45:55, 45:55, 3].min() == 255, "ядро квадрата после blur 1 px потеряло непрозрачность"


def test_ink_letter_edge_does_not_darken_when_scaled() -> None:
    """Реальный путь: буква с краской (65, 70, 82) и мягким краем -> `LayeredObject._transform` scale 0.9.
    Каждый видимый пиксель обязан остаться цветом краски (замер: с чёрным RGB прозрачности min R был 11)."""
    letter = _render_letter(DEJAVU_SANS, "А", 300, 0.6)
    sprite = _finish_ink(letter, (65, 70, 82), 0.0, 1.0, np.random.default_rng(0))
    out = LayeredObject._transform(sprite, 0.9, 0.0, 0.0, None)
    visible = out[:, :, 3] > 0
    rgb = out[:, :, 0:3][visible].astype(int)
    assert visible.sum() > 1000
    assert (rgb == (65, 70, 82)).all(), f"кромка потемнела: min по каналам {rgb.min(axis=0)}"


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


@pytest.mark.parametrize("bad", ["300,0,0", "1,2", "a,b,c", "-1,0,0", "0,0,-1", "1,2,3,4"])
def test_bad_ink_rgb_is_parser_error(bad: str, tmp_path: Path) -> None:
    """Неверный `--ink-rgb` -> код 2 до какой-либо записи. Форма `--ink-rgb=<v>`: значение с ведущим
    минусом (`-1,0,0`) в раздельной форме argparse принял бы за флаг и упал бы по другой причине,
    не по проверке диапазона 0..255."""
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(["--letters", "А", "--font", str(DEJAVU_SANS), "--out", str(out), f"--ink-rgb={bad}"])
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
    # Различитель padding: угол результата — реплицированный тёмный фон фото (30), а не светлый диск.
    # Без padding срез [-3:117] превращается в полоску 3 px светлого диска, и угол становится светлым.
    assert int(rgba[0, 0, 0:3].max()) < 60, f"RGB угла {rgba[0, 0, 0:3]}: не реплицированный фон"


def test_disk_from_photo_rejects_bright_non_circular_shape(tmp_path: Path) -> None:
    """Светлый прямоугольник 200x40 на тёмном фоне 340x340: радиус описанного круга ~102 px (больше
    порога 20), поэтому отсекать его может только проверка заполнения (площадь < 0.8·π·r²)."""
    photo = np.full((340, 340, 3), 30, dtype=np.uint8)
    photo[150:190, 70:270] = 235
    path = tmp_path / "bar.png"
    imwrite_unicode(path, photo)

    with pytest.raises(SystemExit) as exc:
        build_disk_from_photo(path, 64)

    assert isinstance(exc.value.code, str) and str(path) in exc.value.code, f"код выхода: {exc.value.code!r}"


@pytest.mark.parametrize("flag", ["--grain-sigma", "--edge-blur-px"])
@pytest.mark.parametrize("bad", ["-1", "inf", "nan", "-inf"])
def test_negative_or_nonfinite_sigma_is_parser_error(flag: str, bad: str, tmp_path: Path) -> None:
    """Отрицательное/inf/nan для σ зерна и размытия -> код 2 до записи (без проверки они тихо
    превращались в «без эффекта» или в мусор в PNG)."""
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        main(["--letters", "А", "--font", str(DEJAVU_SANS), "--out", str(out), f"{flag}={bad}"])
    assert exc.value.code == 2
    assert not out.exists()


def test_disk_crop_is_centered_on_circle_center(tmp_path: Path) -> None:
    """Диск с центром (60, 60), r 60 в фото 122x122: центр яркой части результата обязан лежать в центре
    канвы 31.5 (допуск 0.15 px). Замер: вырез `round(cx - r)` сдвигал его на ~1 px входа (0.5 px канвы 64) —
    открывалась кайма ленты. Плюс: пиксели с альфа >= 250 светлее 200. (Дробный центр даёт остаточную
    погрешность до 0.5 px входа из-за целочисленного x0 — тут проверяется целый, где точность достижима.)"""
    photo = np.full((122, 122, 3), 30, dtype=np.uint8)
    cv2.circle(photo, (60, 60), 60, (235, 235, 235), -1)
    path = tmp_path / "centered.png"
    imwrite_unicode(path, photo)

    rgba = build_disk_from_photo(path, 64)

    lum = rgba[:, :, 0:3].astype(np.float64).mean(axis=2)
    ys, xs = np.nonzero(lum > 130)
    assert abs(xs.mean() - 31.5) < 0.15 and abs(ys.mean() - 31.5) < 0.15, (
        f"центр яркой части ({xs.mean():.2f}, {ys.mean():.2f}), ожидали (31.5, 31.5)"
    )
    assert lum[rgba[:, :, 3] >= 250].min() >= 200, "под альфа >= 250 виден тёмный RGB ленты"


def test_photo_disk_alpha_does_not_touch_canvas_border(tmp_path: Path) -> None:
    """Размытая альфа фото-диска не упирается в край канвы: у всех пикселей крайних строк и столбцов
    альфа <= 5 (замер: при отступе 2 px было 30 — ступенька на ~22 % окружности)."""
    photo = np.full((200, 200, 3), 30, dtype=np.uint8)
    cv2.circle(photo, (100, 100), 90, (235, 235, 235), -1)
    path = tmp_path / "round.png"
    imwrite_unicode(path, photo)

    a = build_disk_from_photo(path, 300)[:, :, 3]

    edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    assert int(edge.max()) <= 5, f"альфа на краю канвы до {int(edge.max())}"
    assert a[150, 150] == 255


def test_disk_from_empty_photo_file_exits_with_path(tmp_path: Path) -> None:
    """Пустой файл (0 байт): `cv2.imdecode` бросает `cv2.error`, а не ValueError — обязан быть
    `SystemExit` с путём, не трейсбэк."""
    path = tmp_path / "empty.png"
    path.write_bytes(b"")

    with pytest.raises(SystemExit) as exc:
        build_disk_from_photo(path, 64)

    assert isinstance(exc.value.code, str) and str(path) in exc.value.code


def test_unreadable_photo_writes_no_letters(tmp_path: Path) -> None:
    """Нечитаемое фото: `main` падает ДО записи букв — в `--out` нет ни одного файла, диска тоже нет."""
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"not an image")
    out = tmp_path / "out"
    disk = tmp_path / "disk.png"

    with pytest.raises(SystemExit) as exc:
        main(
            ["--letters", "А", "--font", str(DEJAVU_SANS), "--out", str(out)]
            + ["--disk-from-photo", str(bad), "--disk-out", str(disk)]
        )

    assert isinstance(exc.value.code, str) and str(bad) in exc.value.code
    assert not out.exists() or not any(out.rglob("*.png")), "буквы записаны до чтения фото"
    assert not disk.exists()


def test_build_disk_bytes_unchanged_after_alpha_refactor() -> None:
    """`_disk_alpha` вынесен из `build_disk` — сырой массив обязан совпасть с литералами до рефакторинга."""
    assert hashlib.sha256(build_disk(300).tobytes()).hexdigest() == GOLDEN_DISK_RAW_300
    assert hashlib.sha256(build_disk(64).tobytes()).hexdigest() == GOLDEN_DISK_RAW_64
