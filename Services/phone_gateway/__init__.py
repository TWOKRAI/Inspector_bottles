"""Services.phone_gateway -- приём фото и текста с телефона по WiFi.

Назначение: телефон в той же локальной сети открывает страницу в браузере,
отправляет фотографию (снять или выбрать из галереи) и/или слово. ПК принимает
их и отдаёт дальше: фото -> в pipeline как кадр источника, слово -> в state store
(для режима распознавания букв).

Архитектура (зеркалит Services.hikvision_camera):
    gateway.py  -- PhoneGateway: HTTP-сервер + хранилище latest_frame/latest_word (core)
    imaging.py  -- decode (EXIF-поворот) + letterbox (core)
    netinfo.py  -- определение локального IP (core)
    qr.py       -- генерация QR (опционально, через segno) (core)
    web.py      -- HTML-страница для телефона (core)

Source-плагин-мост -- в Plugins/sources/phone_camera (импортирует это ядро).

Публичный API:
    PhoneGateway -- сервер приёма (core, без зависимости от framework)
"""

from __future__ import annotations

from Services.phone_gateway.gateway import PhoneGateway
from Services.phone_gateway.imaging import decode_image, letterbox
from Services.phone_gateway.netinfo import local_ip

__all__ = [
    "PhoneGateway",
    "decode_image",
    "letterbox",
    "local_ip",
]
