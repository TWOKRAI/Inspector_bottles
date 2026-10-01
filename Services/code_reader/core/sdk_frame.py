# -*- coding: utf-8 -*-
"""Модель кадра прибора, полученного через MvCodeReader SDK.

Чистый модуль: DLL не грузит, фреймворк не знает. ``frame_from_raw`` переводит
``RawFrame`` слоя ``sdk/`` (копии C-структур) в неизменяемые Python-объекты
(``CodeQuality.grades`` — ``MappingProxyType`` над копией; из-за него ``hash()`` кадра
по-прежнему ``TypeError`` — объекты неизменяемы, но не хэшируемы);
``decode_image`` — отдельная функция, её зовёт потребитель, которому нужна картинка
(решение 5 плана: сессия не платит за декод).

Статус кадра выводится из списка кодов (решение 3): любой код с ``nLen > 0`` → OK;
иначе есть хоть одна запись → BAD_CODE; иначе → NO_CODE.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

from Services.code_reader.core.result import ReadStatus
from Services.code_reader.sdk.api import RawFrame
from Services.code_reader.sdk.structures import BCR_INFO_EX2, PIXEL_JPEG, PIXEL_MONO8, code_bytes

# Ключ grades → поле MV_CODEREADER_CODE_INFO (уточнение контракта §5).
_GRADE_FIELDS = {
    "decode": "nDeCode",
    "contrast": "nSCGrade",
    "modulation": "nModGrade",
    "fixed_pattern_damage": "nFPDGrade",
    "axial_nonuniformity": "nANGrade",
    "grid_nonuniformity": "nGNGrade",
    "unused_error_correction": "nUECGrade",
}

_PIXEL_NAMES = {PIXEL_JPEG: "jpeg", PIXEL_MONO8: "mono8"}


@dataclass(frozen=True)
class CodeQuality:
    """Оценки качества кода, как их отдал прибор (сырые числа, без перевода в буквы)."""

    overall: int
    grades: Mapping[str, int]  # MappingProxyType над копией: frozen-объект не меняется через grades
    score: int

    def to_dict(self) -> dict[str, Any]:
        return {"overall": self.overall, "grades": dict(self.grades), "score": self.score}


@dataclass(frozen=True)
class CodeRead:
    """Одна запись кода в кадре. ``status`` — OK при ``nLen > 0``, иначе BAD_CODE."""

    text: str
    status: ReadStatus
    bar_type: int
    corners: tuple[tuple[int, int], ...]
    angle_deg: float
    ppm: float
    algo_ms: int
    quality: CodeQuality | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "status": self.status.value,
            "bar_type": self.bar_type,
            "corners": [list(p) for p in self.corners],
            "angle_deg": self.angle_deg,
            "ppm": self.ppm,
            "algo_ms": self.algo_ms,
            "quality": None if self.quality is None else self.quality.to_dict(),
        }


@dataclass(frozen=True)
class SdkFrame:
    """Кадр прибора: метаданные, байты изображения и прочитанные коды."""

    trigger_index: int
    frame_num: int
    width: int
    height: int
    pixel_format: str
    image: bytes
    codes: tuple[CodeRead, ...]
    no_read_num: int
    status: ReadStatus

    def to_dict(self) -> dict[str, Any]:
        """Dict at Boundary: без байтов изображения (только ``image_len``), статусы — строки."""
        return {
            "trigger_index": self.trigger_index,
            "frame_num": self.frame_num,
            "width": self.width,
            "height": self.height,
            "pixel_format": self.pixel_format,
            "image_len": len(self.image),
            "codes": [c.to_dict() for c in self.codes],
            "no_read_num": self.no_read_num,
            "status": self.status.value,
        }


def _pixel_format(pixel_type: int) -> str:
    return _PIXEL_NAMES.get(pixel_type, f"unknown:0x{pixel_type & 0xFFFFFFFF:08X}")


def _quality(rec: BCR_INFO_EX2) -> CodeQuality | None:
    # Флаг решает, а не числа: нулевые оценки при bIsGetQuality — это оценка, не «нет оценки».
    if not rec.bIsGetQuality:
        return None
    q = rec.stCodeQuality
    return CodeQuality(
        overall=int(q.nOverQuality),
        grades=MappingProxyType({key: int(getattr(q, name)) for key, name in _GRADE_FIELDS.items()}),
        score=int(rec.nIDRScore),  # nIDRScore — поле записи кода, не CODE_INFO
    )


def _code(rec: BCR_INFO_EX2) -> CodeRead:
    length = int(rec.nLen)
    # code_bytes — ровно nLen байт, нули внутри кода сохраняются (срез c_char-массива обрывался бы на них).
    text = code_bytes(rec).decode("utf-8", "replace") if length > 0 else ""
    return CodeRead(
        text=text,
        status=ReadStatus.OK if length > 0 else ReadStatus.BAD_CODE,
        bar_type=int(rec.nBarType),
        corners=tuple((int(p.x), int(p.y)) for p in rec.pt),
        angle_deg=rec.nAngle / 10,
        ppm=rec.sPPM / 10,
        algo_ms=int(rec.sAlgoCost),
        quality=_quality(rec),
    )


def frame_from_raw(raw: RawFrame) -> SdkFrame:
    """Перевести сырой кадр SDK в ``SdkFrame``. Чистая функция, DLL не нужна."""
    codes = tuple(_code(rec) for rec in raw.codes)
    if any(c.status is ReadStatus.OK for c in codes):
        status = ReadStatus.OK
    elif codes:
        status = ReadStatus.BAD_CODE
    else:
        status = ReadStatus.NO_CODE
    return SdkFrame(
        trigger_index=int(raw.trigger_index),
        frame_num=int(raw.frame_num),
        width=int(raw.width),
        height=int(raw.height),
        pixel_format=_pixel_format(int(raw.pixel_type)),
        image=bytes(raw.image),
        codes=codes,
        no_read_num=int(raw.no_read_num),
        status=status,
    )


def decode_image(frame: SdkFrame) -> np.ndarray:
    """Картинка кадра как серое ``uint8`` ``height × width``.

    JPEG → ``cv2.imdecode`` в оттенки серого; mono8 → reshape байтов. Иной формат,
    битый JPEG или длина mono8, не совпавшая с размером, → ``ValueError``.
    """
    # Импорт здесь: interfaces.py реэкспортирует модуль, и без этого OpenCV тянул бы
    # каждый потребитель code_reader, включая TCP-плагин (ревью 6.2).
    import cv2
    import numpy as np

    if frame.pixel_format == "jpeg":
        img = cv2.imdecode(np.frombuffer(frame.image, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"JPEG не декодируется ({len(frame.image)} байт)")
        return img
    if frame.pixel_format == "mono8":
        # copy(): frombuffer над bytes даёт массив только для чтения — потребитель может рисовать по нему.
        return np.frombuffer(frame.image, np.uint8).reshape(frame.height, frame.width).copy()
    raise ValueError(f"формат изображения не поддерживается: {frame.pixel_format}")
