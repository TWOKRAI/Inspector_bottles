"""Генерация QR-кодов (опционально, через segno).

segno — pure-python, без транзитивных зависимостей. Если пакет не установлен —
функции возвращают None, и сервис продолжает работать (GUI просто покажет ссылку
текстом). Установка: ``uv pip install segno``.

Важно: один QR-код умеет ЛИБО открыть URL, ЛИБО подключить к WiFi — не оба сразу
(нет такого стандарта). Поэтому две отдельные функции.
"""

from __future__ import annotations

try:
    import segno  # type: ignore

    _HAVE_SEGNO = True
except Exception:  # pragma: no cover - зависит от окружения
    segno = None  # type: ignore
    _HAVE_SEGNO = False


def have_qr() -> bool:
    """Доступна ли генерация QR (установлен ли segno)."""
    return _HAVE_SEGNO


def make_qr_svg(data: str, scale: int = 4, border: int = 2) -> str | None:
    """QR-код произвольной строки -> SVG (str). None если segno нет/ошибка."""
    if not _HAVE_SEGNO or not data:
        return None
    try:
        import io

        buf = io.BytesIO()
        segno.make(data, error="m").save(buf, kind="svg", scale=scale, border=border)
        return buf.getvalue().decode("utf-8")
    except Exception:  # pragma: no cover
        return None


def make_qr_png(data: str, scale: int = 6, border: int = 2) -> bytes | None:
    """QR-код произвольной строки -> PNG (bytes). None если segno нет/ошибка.

    Удобно для Qt: QPixmap.loadFromData(png) — без зависимости от QtSvg.
    """
    if not _HAVE_SEGNO or not data:
        return None
    try:
        import io

        buf = io.BytesIO()
        segno.make(data, error="m").save(buf, kind="png", scale=scale, border=border)
        return buf.getvalue()
    except Exception:  # pragma: no cover
        return None


def wifi_payload(ssid: str, password: str, security: str = "WPA", hidden: bool = False) -> str:
    """Сформировать строку WIFI: для QR подключения к сети.

    Формат распознают камеры iOS 11+/Android: предлагают «Подключиться к сети».
    """

    def esc(value: str) -> str:
        for ch in ("\\", ";", ",", ":", '"'):
            value = value.replace(ch, "\\" + ch)
        return value

    flag = "true" if hidden else "false"
    return f"WIFI:T:{security};S:{esc(ssid)};P:{esc(password)};H:{flag};;"


def make_wifi_qr_svg(
    ssid: str,
    password: str,
    security: str = "WPA",
    hidden: bool = False,
    scale: int = 4,
) -> str | None:
    """QR подключения к WiFi -> SVG (str). None если segno нет."""
    return make_qr_svg(wifi_payload(ssid, password, security, hidden), scale=scale)
