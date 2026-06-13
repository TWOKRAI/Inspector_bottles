"""Интерактивное ручное выравнивание эталонов диска к вертикали (0°).

Зачем: при съёмке от руки буква на «0°»-кадре стоит не строго вертикально —
систематический сдвиг переедет во ВСЕ синтетические метки угла. Этот
инструмент даёт довернуть каждый вырезанный эталон к точному 0° глазами,
по вертикальной гайд-линии, и перезаписать спрайт «выпрямленным».

Порядок:
    1) python -m Services.dataset_gen.tools.cut_real_disks --input ... --out <sprites>
    2) python -m Services.dataset_gen.tools.align_sprites --sprites <sprites>   ← этот шаг
    3) обучение по пресету real_letters_disk.yaml

Управление (окно OpenCV):
    A / D  или  ← / →   доворот -1° / +1°
    , / .               тонко -0.2° / +0.2°
    трекбар «angle»     грубо (-45°..+45°)
    R                   сброс в 0
    Enter / S           СОХРАНИТЬ (перезаписать спрайт выпрямленным) → следующий
    N / →двойной        пропустить без сохранения → следующий
    P / Backspace       предыдущий
    Esc / Q             выход

Эталон — RGBA (вне диска прозрачно); поворот вокруг центра сохраняет размер.
Применённый офсет пишется в align_log.json (аудит, не влияет на обучение).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from Services.dataset_gen.core.catalog import imread_unicode

_BG_GRAY = 128  # фон под прозрачностью при показе
_WIN = "align_sprites"
_TRACK = "angle (x10, -450..450)"


def rotate_rgba(rgba: np.ndarray, deg: float) -> np.ndarray:
    """Повернуть RGBA вокруг центра на deg° (CCW>0), сохранив размер кадра."""
    h, w = rgba.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), deg, 1.0)
    return cv2.warpAffine(
        rgba,
        m,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )


def _preview(rgba: np.ndarray, deg: float, caption: str) -> np.ndarray:
    """Композит спрайта на серый фон + гайд-линии + подпись (для показа)."""
    rot = rotate_rgba(rgba, deg)
    rgb = rot[:, :, :3].astype(np.float32)
    a = (rot[:, :, 3:4].astype(np.float32)) / 255.0
    comp = (rgb * a + _BG_GRAY * (1.0 - a)).astype(np.uint8)
    bgr = cv2.cvtColor(comp, cv2.COLOR_RGB2BGR)
    bgr = cv2.resize(bgr, (384, 384), interpolation=cv2.INTER_NEAREST)
    h, w = bgr.shape[:2]
    cv2.line(bgr, (w // 2, 0), (w // 2, h), (0, 220, 0), 1)  # вертикаль (цель)
    cv2.line(bgr, (0, h // 2), (w, h // 2), (60, 60, 60), 1)  # горизонталь
    cv2.rectangle(bgr, (0, 0), (w, 22), (0, 0, 0), -1)
    cv2.putText(bgr, caption, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return bgr


def _collect(sprites_root: Path) -> list[Path]:
    """Все PNG-эталоны в каталоге классов (подпапка на класс), отсортированы."""
    files = sorted(p for p in sprites_root.rglob("*.png") if p.parent.name[0] not in "._")
    if not files:
        raise SystemExit(f"Нет эталонов *.png в {sprites_root}")
    return files


def run(sprites_root: Path) -> None:
    files = _collect(sprites_root)
    log_path = sprites_root / "align_log.json"
    log: dict[str, float] = json.loads(log_path.read_text(encoding="utf-8")) if log_path.is_file() else {}

    cv2.namedWindow(_WIN, cv2.WINDOW_AUTOSIZE)
    cv2.createTrackbar(_TRACK, _WIN, 450, 900, lambda v: None)  # 450 == 0°

    i = 0
    base = imread_unicode(files[i], cv2.IMREAD_UNCHANGED)
    base = cv2.cvtColor(base, cv2.COLOR_BGRA2RGBA) if base.shape[2] == 4 else base
    angle = 0.0
    cv2.setTrackbarPos(_TRACK, _WIN, 450)
    last_track = 450

    def load(idx: int):
        nonlocal base, angle, last_track
        b = imread_unicode(files[idx], cv2.IMREAD_UNCHANGED)
        base = cv2.cvtColor(b, cv2.COLOR_BGRA2RGBA) if b.ndim == 3 and b.shape[2] == 4 else b
        angle = 0.0
        cv2.setTrackbarPos(_TRACK, _WIN, 450)
        last_track = 450

    while True:
        rel = files[i].relative_to(sprites_root).as_posix()
        cap = f"[{i + 1}/{len(files)}] {files[i].parent.name}/{files[i].name}  off={angle:+.1f} deg"
        cv2.imshow(_WIN, _preview(base, angle, cap))
        key = cv2.waitKey(30) & 0xFF

        track = cv2.getTrackbarPos(_TRACK, _WIN)
        if track != last_track:  # трекбар сдвинут — он ведущий
            angle = (track - 450) / 10.0
            last_track = track

        def sync_track():
            nonlocal last_track
            t = int(round(angle * 10)) + 450
            t = max(0, min(900, t))
            cv2.setTrackbarPos(_TRACK, _WIN, t)
            last_track = t

        if key in (ord("d"), 83):  # → / D : +1
            angle += 1.0
            sync_track()
        elif key in (ord("a"), 81):  # ← / A : -1
            angle -= 1.0
            sync_track()
        elif key == ord("."):
            angle += 0.2
            sync_track()
        elif key == ord(","):
            angle -= 0.2
            sync_track()
        elif key == ord("r"):
            angle = 0.0
            sync_track()
        elif key in (13, ord("s")):  # Enter / S : сохранить
            out = rotate_rgba(base, angle)
            Image.fromarray(out, mode="RGBA").save(files[i])  # PIL: unicode-safe
            log[rel] = round(angle, 2)
            log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[save] {rel}  off={angle:+.1f}")
            if i < len(files) - 1:
                i += 1
                load(i)
            else:
                print("Готово — все эталоны пройдены.")
                break
        elif key in (ord("n"),):  # пропустить
            if i < len(files) - 1:
                i += 1
                load(i)
        elif key in (ord("p"), 8):  # предыдущий
            if i > 0:
                i -= 1
                load(i)
        elif key in (27, ord("q")):
            break

    cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ручное выравнивание эталонов к 0°")
    parser.add_argument("--sprites", required=True, help="каталог эталонов (выход cut_real_disks)")
    args = parser.parse_args()
    root = Path(args.sprites)
    if not root.is_dir():
        raise SystemExit(f"Каталог не найден: {root}")
    run(root)


if __name__ == "__main__":
    main()
