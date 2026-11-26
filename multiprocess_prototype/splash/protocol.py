"""Посылка прогресса «лончер/PM -> заставка» и шкала заставки. Только stdlib.

Посылка — одна UDP-датаграмма на 127.0.0.1, JSON ``{"id", "percent", "label", "done"}``.

Веса шкалы и правило монотонности — копия ``ProgressTracker`` фреймворка, а не импорт: модуль грузится
в процессе заставки, а импорт фреймворка стоит ~1 с. Совпадение чисел сторожит тест.
"""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Mapping

#: Выключатель заставки: ``INSPECTOR_SPLASH=0``.
SPLASH_ENV = "INSPECTOR_SPLASH"
#: Порт заставки; ставит только ``SplashLink.publish_port``, читают PM и GUI.
SPLASH_PORT_ENV = "INSPECTOR_SPLASH_PORT"
#: Доли этапов в общей шкале.
SPLASH_WEIGHTS: dict[str, int] = {"launch": 10, "boot": 50, "gui": 40}
#: Заставка уходит сама, если сигнала от GUI так и не было.
SPLASH_TIMEOUT_S = 60.0
#: Сколько (от запуска процесса) лончер ждёт строку порта.
SPLASH_PORT_WAIT_S = 0.3
#: Лончер умер, а Qt-поток заставки не отвечает: через столько процесс выходит принудительно.
SPLASH_ORPHAN_EXIT_S = 3.0

_LABEL_LIMIT = 200


def splash_enabled(environ: Mapping[str, str]) -> bool:
    """``False`` только при ``INSPECTOR_SPLASH`` == ``"0"`` (после ``strip``)."""
    return str(environ.get(SPLASH_ENV, "")).strip() != "0"


def parse_port(value: object) -> int | None:
    """Номер порта из строки цифр; иначе ``None``."""
    text = str(value or "").strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 5:
        return None
    port = int(text)
    return port if 0 < port <= 65535 else None


def encode(progress_id: str, leaf: Mapping) -> bytes:
    """Лист прогресса -> датаграмма. Pre: в листе есть ``percent``; ``label`` обрезается до 200."""
    message = {
        "id": progress_id,
        "percent": leaf["percent"],
        "label": str(leaf.get("label", ""))[:_LABEL_LIMIT],
        "done": bool(leaf.get("done", False)),
    }
    return json.dumps(message).encode("utf-8")


def decode(data: bytes) -> dict | None:
    """Датаграмма -> ровно ``{id, percent, label, done}``; чужое и битое -> ``None``."""
    try:
        raw = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(raw, dict):
        return None
    progress_id = raw.get("id")
    percent = raw.get("percent")
    label = raw.get("label", "")
    done = raw.get("done", False)
    if not isinstance(progress_id, str) or not progress_id:
        return None
    if type(percent) is not int or not 0 <= percent <= 100:  # bool — подкласс int, не процент
        return None
    if not isinstance(label, str) or not isinstance(done, bool):
        return None
    return {"id": progress_id, "percent": percent, "label": label[:_LABEL_LIMIT], "done": done}


def send_leaf(progress_id: str, leaf: Mapping, environ: Mapping[str, str] = os.environ) -> bool:
    """Отправить лист заставке. Не бросает; ``False`` — порта нет или отправка не удалась.

    Слушателя на порту может уже не быть (заставка ушла) — это норма, а не ошибка.
    """
    try:
        port = parse_port(environ.get(SPLASH_PORT_ENV))
        if port is None:
            return False
        payload = encode(progress_id, leaf)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setblocking(False)
            sock.sendto(payload, ("127.0.0.1", port))
    except Exception:  # noqa: BLE001 — прогресс не имеет права уронить или задержать писателя
        return False
    return True


def is_close_signal(message: Mapping) -> bool:
    """GUI сообщил «первое окно появилось»."""
    return message.get("id") == "gui" and message.get("done") is True


class SplashScale:
    """Общий процент заставки: сумма «вес этапа x доля этапа», монотонный.

    Неизвестный ``id`` шкалу не двигает. НЕ потокобезопасен: владелец — Qt-поток заставки.
    """

    def __init__(self) -> None:
        self._fractions: dict[str, float] = dict.fromkeys(SPLASH_WEIGHTS, 0.0)
        self._percent = 0

    @property
    def percent(self) -> int:
        return self._percent

    def feed(self, message: Mapping) -> int:
        """Pre: ``message`` — выход ``decode``. Post: возвращён новый общий процент (не меньше прошлого)."""
        progress_id = message["id"]
        if progress_id in self._fractions:
            fraction = min(1.0, max(0.0, message["percent"] / 100))
            self._fractions[progress_id] = max(self._fractions[progress_id], fraction)
            total = sum(weight * self._fractions[name] for name, weight in SPLASH_WEIGHTS.items())
            # Монотонность держит max по доле этапа: веса положительны, сумма и round не убывают.
            self._percent = min(100, round(total))
        return self._percent
