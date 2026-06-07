"""Универсальный control-core веб-камеры (OpenCV CAP_PROP).

Единственное место, где живёт знание «какие параметры физически управляемы у
вебкамеры, как их применить (`cap.set`) и как прочитать actual (`cap.get`)».
Используется backend'ом плагина камеры (плагин — единственный владелец cv2).

Чистые функции от объекта `cap` (cv2.VideoCapture) — тестируются через fake-cap
(любой объект с методами `.set(prop, value)` / `.get(prop)`).

ВАЖНО (долг ~15fps DirectShow): FOURCC=MJPG нужно ставить ДО width/height,
иначе DirectShow может проигнорировать кодек. Порядок enforce здесь, в
`apply_open_sequence`, а не в GUI.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import cv2


@dataclass(frozen=True)
class ParamSpec:
    """Описание одного управляемого параметра камеры.

    Attributes:
        name: ключ параметра (совпадает с register-полем плагина).
        prop: константа cv2.CAP_PROP_*.
        label: человекочитаемая метка для UI.
        kind: "float" | "int" | "bool".
        min/max/step: номинальный диапазон для UI-слайдера. У DirectShow реальный
            диапазон зависит от камеры — actual-readback показывает правду.
        unit: единица измерения для UI.
        on_value/off_value: для kind="bool" — значения cv2 для вкл/выкл
            (напр. авто-экспозиция на DSHOW: 0.75=auto, 0.25=manual).
    """

    name: str
    prop: int
    label: str
    kind: str = "float"
    min: float | None = None
    max: float | None = None
    step: float | None = None
    unit: str = ""
    on_value: float = 1.0
    off_value: float = 0.0


# Каталог физически-управляемых параметров (без width/height/fps/fourcc — у них
# отдельная обработка в apply_open_sequence/read_actual). Диапазоны номинальные.
WEBCAM_PARAMS: dict[str, ParamSpec] = {
    "auto_exposure": ParamSpec(
        "auto_exposure",
        cv2.CAP_PROP_AUTO_EXPOSURE,
        "Авто-экспозиция",
        kind="bool",
        on_value=0.75,
        off_value=0.25,
    ),
    "exposure": ParamSpec(
        "exposure",
        cv2.CAP_PROP_EXPOSURE,
        "Экспозиция",
        kind="int",
        min=-13,
        max=0,
        step=1,
        unit="log2",
    ),
    "gain": ParamSpec(
        "gain",
        cv2.CAP_PROP_GAIN,
        "Усиление",
        kind="int",
        min=0,
        max=255,
        step=1,
    ),
    "brightness": ParamSpec(
        "brightness",
        cv2.CAP_PROP_BRIGHTNESS,
        "Яркость",
        kind="int",
        min=0,
        max=255,
        step=1,
    ),
    "contrast": ParamSpec(
        "contrast",
        cv2.CAP_PROP_CONTRAST,
        "Контраст",
        kind="int",
        min=0,
        max=255,
        step=1,
    ),
    "saturation": ParamSpec(
        "saturation",
        cv2.CAP_PROP_SATURATION,
        "Насыщенность",
        kind="int",
        min=0,
        max=255,
        step=1,
    ),
    "hue": ParamSpec(
        "hue",
        cv2.CAP_PROP_HUE,
        "Оттенок",
        kind="int",
        min=-180,
        max=180,
        step=1,
        unit="°",
    ),
    "gamma": ParamSpec(
        "gamma",
        cv2.CAP_PROP_GAMMA,
        "Гамма",
        kind="int",
        min=0,
        max=500,
        step=1,
    ),
    "sharpness": ParamSpec(
        "sharpness",
        cv2.CAP_PROP_SHARPNESS,
        "Резкость",
        kind="int",
        min=0,
        max=255,
        step=1,
    ),
    "auto_wb": ParamSpec(
        "auto_wb",
        cv2.CAP_PROP_AUTO_WB,
        "Авто баланс белого",
        kind="bool",
        on_value=1.0,
        off_value=0.0,
    ),
    "white_balance": ParamSpec(
        "white_balance",
        cv2.CAP_PROP_WB_TEMPERATURE,
        "Баланс белого",
        kind="int",
        min=2000,
        max=10000,
        step=100,
        unit="K",
    ),
    "backlight": ParamSpec(
        "backlight",
        cv2.CAP_PROP_BACKLIGHT,
        "Компенсация засветки",
        kind="int",
        min=0,
        max=2,
        step=1,
    ),
    "autofocus": ParamSpec(
        "autofocus",
        cv2.CAP_PROP_AUTOFOCUS,
        "Автофокус",
        kind="bool",
        on_value=1.0,
        off_value=0.0,
    ),
    "focus": ParamSpec(
        "focus",
        cv2.CAP_PROP_FOCUS,
        "Фокус",
        kind="int",
        min=0,
        max=255,
        step=1,
    ),
    "zoom": ParamSpec(
        "zoom",
        cv2.CAP_PROP_ZOOM,
        "Зум",
        kind="int",
        min=0,
        max=500,
        step=1,
    ),
}

# Пресеты для UI
RESOLUTION_PRESETS: list[tuple[int, int]] = [
    (640, 480),
    (800, 600),
    (1280, 720),
    (1920, 1080),
]
FPS_PRESETS: list[int] = [5, 10, 15, 25, 30, 60]


def decode_fourcc(value: float) -> str:
    """Декодировать значение CAP_PROP_FOURCC в 4-символьный код (напр. 'MJPG')."""
    iv = int(value)
    return "".join(chr((iv >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00")


def _clamp(spec: ParamSpec, value: float) -> float:
    """Привести значение к диапазону spec (если задан)."""
    if spec.min is not None:
        value = max(spec.min, value)
    if spec.max is not None:
        value = min(spec.max, value)
    return value


def apply_param(cap, name: str, value) -> bool:
    """Применить один параметр через cap.set.

    Args:
        cap: cv2.VideoCapture (или fake с .set).
        name: ключ из WEBCAM_PARAMS.
        value: значение (для bool — truthy/falsy → on_value/off_value).

    Returns:
        True если cap.set вернул успех, иначе False (включая неизвестный параметр
        или cap=None).
    """
    spec = WEBCAM_PARAMS.get(name)
    if spec is None or cap is None:
        return False
    if spec.kind == "bool":
        cv_value = spec.on_value if value else spec.off_value
    else:
        cv_value = _clamp(spec, float(value))
    try:
        return bool(cap.set(spec.prop, cv_value))
    except Exception:
        return False


def set_mjpg(cap, on: bool) -> bool:
    """Включить/выключить MJPG-кодек (FOURCC).

    MJPG снимает потолок ~15fps DirectShow. Выкл → YUY2 (несжатый дефолт).
    """
    if cap is None:
        return False
    try:
        code = "MJPG" if on else "YUY2"
        fourcc = cv2.VideoWriter_fourcc(*code)
        return bool(cap.set(cv2.CAP_PROP_FOURCC, fourcc))
    except Exception:
        return False


def apply_open_sequence(
    cap,
    *,
    mjpg: bool = False,
    width: int | None = None,
    height: int | None = None,
    fps: int | None = None,
    params: dict | None = None,
) -> None:
    """Применить стартовую последовательность настроек к свежеоткрытому cap.

    ПОРЯДОК КРИТИЧЕН: FOURCC(MJPG) → width/height → fps → остальные параметры.
    DirectShow игнорирует MJPG, если кодек ставится после разрешения.

    Args:
        cap: cv2.VideoCapture.
        mjpg: включить MJPG-кодек до разрешения.
        width/height/fps: базовые параметры (None — не трогать).
        params: словарь {name: value} для WEBCAM_PARAMS.
    """
    if cap is None:
        return
    if mjpg:
        set_mjpg(cap, True)
    if width is not None:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
    if height is not None:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
    if fps is not None:
        cap.set(cv2.CAP_PROP_FPS, int(fps))
    for name, value in (params or {}).items():
        apply_param(cap, name, value)


def read_actual(cap, names: list[str] | None = None) -> dict:
    """Прочитать actual-значения (что камера реально применила) через cap.get.

    Args:
        cap: cv2.VideoCapture.
        names: подмножество ключей; None — все (width/height/fps/fourcc + каталог).

    Returns:
        dict {name: actual_value}. fourcc — декодированная строка.
    """
    if cap is None:
        return {}
    result: dict = {}

    base = {
        "width": cv2.CAP_PROP_FRAME_WIDTH,
        "height": cv2.CAP_PROP_FRAME_HEIGHT,
        "fps": cv2.CAP_PROP_FPS,
    }
    for name, prop in base.items():
        if names is None or name in names:
            try:
                result[name] = cap.get(prop)
            except Exception:
                pass

    if names is None or "fourcc" in names:
        try:
            result["fourcc"] = decode_fourcc(cap.get(cv2.CAP_PROP_FOURCC))
        except Exception:
            pass

    for name, spec in WEBCAM_PARAMS.items():
        if names is not None and name not in names:
            continue
        try:
            result[name] = cap.get(spec.prop)
        except Exception:
            pass

    return result


def capture_single_frame(
    device_id: int = 0,
    *,
    width: int | None = None,
    height: int | None = None,
    mjpg: bool = False,
):
    """Разовый грабер: открыть камеру, прочитать ОДИН кадр, освободить.

    Держит устройство лишь на миг → не конкурирует с pipeline-плагином при обычном
    использовании. Если устройство занято (им владеет работающий плагин) или нет —
    вернёт None (graceful). Единый cv2-путь для песочницы (вместо отдельного сервиса).

    Returns:
        BGR ndarray или None.
    """
    cap = None
    try:
        cap = cv2.VideoCapture(device_id, cv2.CAP_DSHOW) if sys.platform == "win32" else cv2.VideoCapture(device_id)
        if not cap.isOpened():
            return None
        apply_open_sequence(cap, mjpg=mjpg, width=width, height=height)
        # DSHOW: первые кадры часто пустые — берём последний из нескольких чтений.
        frame = None
        for _ in range(3):
            ok, f = cap.read()
            if ok and f is not None:
                frame = f
        return frame
    except Exception:
        return None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


__all__ = [
    "ParamSpec",
    "WEBCAM_PARAMS",
    "RESOLUTION_PRESETS",
    "FPS_PRESETS",
    "decode_fourcc",
    "apply_param",
    "set_mjpg",
    "apply_open_sequence",
    "read_actual",
    "capture_single_frame",
]
