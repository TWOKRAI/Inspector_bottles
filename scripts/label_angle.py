"""Разметка угла диска после съёмки (задача РУ-1, plans/layer-render/task-label-angle.md).

Диск снимается как лёг. Здесь картинку доворачивают, пока буква не встанет прямо, и жмут Enter:
в папку результата пишется побайтовая копия кадра, а угол буквы записывается в имя файла.

    вход       <raw>/<БУКВА>/a<ddd>_<номер>.<расширение>   (цифры ddd ничего не значат)
    результат  <out>/<БУКВА>/a<угол:03d>_<номер>.<расширение>

Угол — на сколько градусов ПРОТИВ часовой стрелки буква повёрнута на кадре (0 — стоит прямо).
Входные файлы не меняются и не удаляются. Результат читает ``scripts/letters_baseline.py dir``.

Запуск из корня репозитория:
    python scripts/label_angle.py <папка кадров> <папка результата> [--recipe ПУТЬ] [--no-crop]
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QSlider, QVBoxLayout, QWidget

REPO_ROOT = Path(__file__).resolve().parent.parent
# Корень репозитория должен стоять ПЕРВЫМ: имя ``scripts`` занято ещё и пакетом из win32.
if sys.path[0] != str(REPO_ROOT):
    sys.path.insert(0, str(REPO_ROOT))

from scripts.letters_baseline import IMAGE_SUFFIXES, NAME_RE, RecipePipeline, read_image  # noqa: E402

DEFAULT_RECIPE = REPO_ROOT / "multiprocess_prototype" / "recipes" / "hikvision_letter_robot.yaml"
VIEW_SIZE = 600  # сторона квадрата с картинкой на экране
GUIDE_COLOR = (230, 30, 30)  # прямые вертикаль и горизонталь поверх картинки
KEYS_HINT = (
    "← → — повернуть на 1°,  ↑ ↓ — на 10°\n"
    "Enter — записать и дальше,  S — пропустить,  Backspace — назад,  Esc — закрыть"
)


@dataclass(frozen=True)
class RawFrame:
    """Один снятый кадр."""

    path: Path  # входной файл
    letter: str  # имя папки буквы, NFC
    index: str  # цифры номера, как в имени
    angle: int | None  # угол из уже записанной копии; None — ещё не размечен


# --------------------------------------------------------------------------- #
# Файлы                                                                        #
# --------------------------------------------------------------------------- #


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES and path.is_file()


def _parse(root: Path, path: Path) -> tuple[str, str] | None:
    """``<root>/<БУКВА>/a<ddd>_<номер>.<расш>`` → (буква, цифры номера); None — имя не по схеме."""
    parts = path.relative_to(root).parts
    match = NAME_RE.match(path.stem)
    if len(parts) != 2 or match is None:
        return None
    letter = unicodedata.normalize("NFC", parts[0])
    return (letter, match.group(2)) if len(letter) == 1 else None


def _fail(problems: list[str]) -> None:
    if problems:
        raise ValueError("с файлами что-то не так:\n  " + "\n  ".join(problems))


def scan(raw_dir: Path, out_dir: Path) -> list[RawFrame]:
    """Кадры из raw_dir по порядку «буква, номер» с углами из out_dir. Любая непонятность — ValueError."""
    if not raw_dir.is_dir():
        raise ValueError(f"нет папки со снятыми кадрами: {raw_dir}")
    if out_dir.exists() and not out_dir.is_dir():
        raise ValueError(f"вместо папки результата лежит файл: {out_dir}")
    raw_real, out_real = raw_dir.resolve(), out_dir.resolve()
    if out_real.is_relative_to(raw_real) or raw_real.is_relative_to(out_real):
        raise ValueError(
            f"папка результата ({out_dir}) не должна совпадать с папкой кадров ({raw_dir}), "
            "лежать внутри неё или содержать её"
        )

    problems: list[str] = []
    inputs: dict[tuple[str, int], tuple[Path, str]] = {}  # (буква, номер) → (файл, цифры номера)
    for path in sorted(raw_dir.rglob("*")):
        if not _is_image(path):
            continue
        parsed = _parse(raw_dir, path)
        if parsed is None:
            problems.append(f"имя не по схеме <БУКВА>/a000_<номер>: {path}")
            continue
        letter, index = parsed
        key = (letter, int(index))
        if key in inputs:
            problems.append(f"у двух кадров один номер: {inputs[key][0]} и {path}")
        else:
            inputs[key] = (path, index)
    _fail(problems)
    if not inputs:
        raise ValueError(f"в папке нет картинок: {raw_dir}")

    copies: dict[tuple[str, int], list[Path]] = defaultdict(list)
    for path in sorted(out_dir.rglob("*")):  # папки нет — список пуст, и она не создаётся
        if not _is_image(path):
            continue
        parsed = _parse(out_dir, path)
        if parsed is None or path.parent.name != parsed[0]:
            problems.append(f"в папке результата файл с именем не по схеме: {path}")
            continue
        key = (parsed[0], int(parsed[1]))
        if key not in inputs:
            problems.append(f"в папке кадров нет кадра для этой копии (перенесли или удалили?): {path}")
        elif path.read_bytes() != inputs[key][0].read_bytes():
            problems.append(f"копия не совпадает с кадром {inputs[key][0]}: {path}")
        else:
            copies[key].append(path)
    for paths in copies.values():
        if len(paths) > 1:
            names = ", ".join(str(p) for p in paths)
            problems.append(f"две копии одного кадра (оставьте одну, лишнюю удалите): {names}")
    _fail(problems)

    frames = []
    for key in sorted(inputs):
        path, index = inputs[key]
        angle = int(NAME_RE.match(copies[key][0].stem).group(1)) if key in copies else None
        frames.append(RawFrame(path, key[0], index, angle))
    return frames


def truth_angle(turn_deg: int) -> int:
    """Доворот вида (против часовой) → угол буквы на кадре."""
    return (-turn_deg) % 360


def rotate_view(image: np.ndarray, turn_deg: float) -> np.ndarray:
    """Повернуть картинку вокруг центра против часовой (как видно на экране); размер тот же."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D(((width - 1) / 2, (height - 1) / 2), turn_deg, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR)


def save_label(frame: RawFrame, out_dir: Path, angle: int) -> Path:
    """Записать копию кадра с углом в имени и убрать свою прежнюю копию под другим углом."""
    data = frame.path.read_bytes()
    folder = out_dir / frame.letter
    if folder.exists() and not folder.is_dir():
        raise NotADirectoryError(f"вместо папки буквы лежит файл: {folder}")
    old = []
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            match = NAME_RE.match(path.stem)
            if match is None or int(match.group(2)) != int(frame.index) or not _is_image(path):
                continue
            if path.read_bytes() != data:
                raise FileExistsError(f"под этим номером уже лежит другой файл, он не тронут: {path}")
            old.append(path)

    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"a{angle % 360:03d}_{frame.index}{frame.path.suffix}"
    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, target)  # под целевым именем файл появляется только целиком
    finally:
        tmp.unlink(missing_ok=True)
    for path in old:
        # samefile: на Windows имя в другом регистре — это тот же только что записанный файл
        if not os.path.samefile(path, target):
            path.unlink()
    return target


# --------------------------------------------------------------------------- #
# Окно                                                                         #
# --------------------------------------------------------------------------- #


def _wrap_turn(deg: int) -> int:
    """Привести доворот к (-180, 180]."""
    deg %= 360
    return deg - 360 if deg > 180 else deg


def _load_pipeline(recipe_path: Path) -> RecipePipeline:
    try:
        return RecipePipeline(recipe_path)
    except Exception as exc:  # нет файла, испорченный YAML, нет нужного плагина — для владельца это одно
        raise ValueError(
            f"не получилось прочитать рецепт {recipe_path}: {type(exc).__name__}: {exc}\n"
            "Без вырезки диска можно запустить с ключом --no-crop."
        ) from exc


def _pad_to_square(image: np.ndarray) -> np.ndarray:
    """Дополнить чёрным до квадрата со стороной не меньше диагонали: при повороте ничего не уезжает за край."""
    height, width = image.shape[:2]
    side = math.ceil(math.hypot(height, width))
    canvas = np.zeros((side, side, 3), dtype=image.dtype)
    top, left = (side - height) // 2, (side - width) // 2
    canvas[top : top + height, left : left + width] = image
    return canvas


def _pixmap_with_guides(bgr: np.ndarray) -> QPixmap:
    """Картинка для экрана с прямыми вертикалью и горизонталью. В файлы эти линии не попадают."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    height, width = rgb.shape[:2]
    pixmap = QPixmap.fromImage(QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888))
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor(*GUIDE_COLOR), 2))
    painter.drawLine(width // 2, 0, width // 2, height)
    painter.drawLine(0, height // 2, width, height // 2)
    painter.end()
    return pixmap


class LabelWindow(QWidget):
    """Окно разметки: картинка, доворот клавишами, Enter — записать."""

    def __init__(self, raw_dir: Path, out_dir: Path, recipe_path: Path | None = None) -> None:
        super().__init__()
        self.frames = scan(raw_dir, out_dir)
        self._out_dir = out_dir
        self._pipeline = None if recipe_path is None else _load_pipeline(recipe_path)
        self._position = 0  # номер текущего кадра в frames; len(frames) — кадры кончились
        self._turn = 0
        self._letter: str | None = None  # буква последнего показанного кадра
        self._base: np.ndarray | None = None  # картинка кадра без поворота; None — показывать нечего

        self.setWindowTitle("Разметка угла диска")
        self.setStyleSheet("QLabel { font-size: 15px; }")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)

        def label(text: str = "") -> QLabel:
            widget = QLabel(text)
            widget.setTextFormat(Qt.TextFormat.PlainText)
            widget.setWordWrap(True)
            layout.addWidget(widget)
            return widget

        self._title = label()
        self._view = QLabel()
        self._view.setFixedSize(VIEW_SIZE, VIEW_SIZE)
        layout.addWidget(self._view)
        self._note = label()
        self._angles = label()
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(-180, 180)
        self._slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._slider)
        self._message = label()
        self._message.setStyleSheet("color: #c00000; font-weight: bold;")
        label(KEYS_HINT)
        self._slider.valueChanged.connect(self.set_turn)
        self._slider.installEventFilter(self)  # клавиши на ползунке обрабатывает окно

        unlabelled = (i for i, frame in enumerate(self.frames) if frame.angle is None)
        self._go(next(unlabelled, len(self.frames)))
        self.setFocus()

    @property
    def current(self) -> RawFrame | None:
        return self.frames[self._position] if self._position < len(self.frames) else None

    @property
    def turn_deg(self) -> int:
        return self._turn

    def set_turn(self, deg: int) -> None:
        self._turn = _wrap_turn(int(deg))
        # -180 на ползунке и 180 — одно и то же: ручку из-под мыши на другой край не перекидываем
        if _wrap_turn(self._slider.value()) != self._turn:
            self._slider.setValue(self._turn)
        self._render()

    def _go(self, position: int) -> None:
        self._position = position
        self._message.setText("")
        frame = self.current
        turn = self._turn
        if frame is not None:
            if frame.angle is not None:
                turn = -frame.angle
            elif frame.letter != self._letter:
                turn = 0
            self._letter = frame.letter
        self._load(frame)
        self.set_turn(turn)

    def _load(self, frame: RawFrame | None) -> None:
        """Прочитать кадр и приготовить картинку VIEW_SIZE x VIEW_SIZE без поворота."""
        self._base = None
        if frame is None:
            self._note.setText("Кадры кончились. Backspace — вернуться к последнему, Esc — закрыть.")
            return
        image = read_image(frame.path)
        if image is None:
            self._note.setText(f"Файл не читается: {frame.path}\nЗаписать его нельзя. S — пропустить.")
            return
        note = "Вырезка диска выключена: показан весь кадр, уменьшенный."
        crop = None
        if self._pipeline is not None:
            note = "Круг диска не найден: показан весь кадр, уменьшенный."
            try:
                crop = self._pipeline.crop(image)
            except Exception as exc:  # плагин рецепта упал на этом кадре: показываем кадр целиком
                note = f"Вырезка диска не получилась ({exc}): показан весь кадр, уменьшенный."
                print(f"{frame.path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        if crop is not None:
            self._base = cv2.resize(crop, (VIEW_SIZE, VIEW_SIZE), interpolation=cv2.INTER_CUBIC)
            note = ""
        else:
            self._base = cv2.resize(_pad_to_square(image), (VIEW_SIZE, VIEW_SIZE), interpolation=cv2.INTER_AREA)
        self._note.setText(note)

    def _render(self) -> None:
        if self._base is None:
            self._view.clear()
        else:
            self._view.setPixmap(_pixmap_with_guides(rotate_view(self._base, self._turn)))

        frame = self.current
        total = len(self.frames)
        done = sum(1 for f in self.frames if f.angle is not None)
        if frame is None:
            self._title.setText(f"Все кадры пройдены: кадров {total}, размечено {done}")
            self._angles.setText("")
            return
        self._title.setText(
            f"Буква {frame.letter}, номер {frame.index} — кадр {self._position + 1} из {total}, размечено {done}"
        )
        side = "" if self._turn in (0, 180) else (" против часовой" if self._turn > 0 else " по часовой")
        self._angles.setText(f"Доворот: {abs(self._turn)}°{side}.   Запишется угол: {truth_angle(self._turn)}°")

    def _save(self) -> None:
        frame = self.current
        if frame is None or self._base is None:
            return
        angle = truth_angle(self._turn)
        try:
            save_label(frame, self._out_dir, angle)
        except OSError as exc:
            self._message.setText(f"НЕ ЗАПИСАНО: {exc}")
            print(f"не записано: {exc}", file=sys.stderr)
            return
        self.frames[self._position] = replace(frame, angle=angle)
        self._go(self._position + 1)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 — имя задано Qt
        key = event.key()
        steps = {Qt.Key.Key_Left: 1, Qt.Key.Key_Right: -1, Qt.Key.Key_Up: 10, Qt.Key.Key_Down: -10}
        if key in steps:
            self.set_turn(self._turn + steps[key])
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():  # зажатый Enter не должен размечать кадры не глядя
                self._save()
        elif key == Qt.Key.Key_S or event.text().lower() == "ы":
            if self.current is not None:
                self._go(self._position + 1)
        elif key == Qt.Key.Key_Backspace:
            if self._position > 0:
                self._go(self._position - 1)
        elif key == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.KeyPress:
            self.keyPressEvent(event)
            return True
        return super().eventFilter(watched, event)


# --------------------------------------------------------------------------- #
# Запуск                                                                       #
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="label_angle",
        description="Разметка угла диска: доверните картинку, пока буква не встанет прямо, и нажмите Enter.",
    )
    parser.add_argument("raw", help="папка снятых кадров: <raw>/<БУКВА>/a000_<номер>.png")
    parser.add_argument("out", help="папка результата (создаётся сама)")
    parser.add_argument(
        "--recipe", default=str(DEFAULT_RECIPE), help="рецепт для вырезки диска; по умолчанию %(default)s"
    )
    parser.add_argument("--no-crop", action="store_true", help="не вырезать диск, показывать весь кадр")
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    try:
        window = LabelWindow(Path(args.raw), Path(args.out), None if args.no_crop else Path(args.recipe))
    except (ValueError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    window.show()
    app.exec()

    for letter in dict.fromkeys(f.letter for f in window.frames):
        frames = [f for f in window.frames if f.letter == letter]
        angles = [f.angle for f in frames if f.angle is not None]
        print(f"{letter}: кадров {len(frames)}, размечено {len(angles)}, разных углов {len(set(angles))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
