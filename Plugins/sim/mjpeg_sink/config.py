# -*- coding: utf-8 -*-
"""Конфиг ``MjpegSinkPlugin`` — параметры HTTP-раздачи кадров.

**ЧЕСТНАЯ ИСТОРИЯ ЭТОГО ФАЙЛА — он больше не то, ради чего заводился.**

Заводился как снятый блокер: 2026-09-21 живой стенд показал, что `mjpeg_sink`
молча исчезает из процесса `camera`. Причина — во фреймворке:
``ProcessConfig.as_generic_config`` пересобирает список плагинов процесса из
``_restore_plugin_configs()`` (``process_manager_module/topology/blueprint.py:248``),
а та пропускает плагин без соседнего модуля ``config`` (``continue`` на
``ImportError``); ветка ``if plugin_configs:`` строит процесс ТОЛЬКО из
отфильтрованного списка. Замер тогда: без этого файла ``camera.config.plugins ==
['camera_service']``, порт не открывался.

**Но форма проводки потом изменилась, и замер протух В ТУ ЖЕ СЕССИЮ.** Арбитраж
CTO развёл источник и сток по разным процессам (`camera` → IPC → `mjpeg`), и
теперь в каждом процессе ПО ОДНОМУ плагину — отфильтрованный список выходит
пустым, срабатывает else-ветка, дефект не кусает. Перепроверено ревью и ведущим:
без этого файла набор даёт 3 passed, приложение собирается со всеми тремя
процессами, стенд отдаёт кадры. Формулировка «без него порт 8091 не открывается»
была верна на коммите 76f6d4b1 и НЕВЕРНА сегодня — снята.

**Чем файл является сейчас:** схемой конфига в ряд с соседями
(``camera_service``, ``modbus_sink``, ``grayscale``) и страховкой на будущее —
дефект вернётся, если в процесс ``mjpeg`` когда-нибудь добавят второй плагин
С конфигом. Сам дефект фреймворка НЕ починен и заведён в
``docs/claude/OPEN_QUESTIONS.md``; сторожа на него в этом дереве нет.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import PluginConfig
from multiprocess_framework.modules.process_module.plugins import register_schema


@register_schema("MjpegSinkPluginConfigV1")
class MjpegSinkConfig(PluginConfig):
    """Конфиг MJPEG-стока: адрес раздачи, качество JPEG, потолок частоты.

    Дефолты совпадают с ``_DEFAULT_*`` в ``plugin.py`` — плагин читает сырой
    ``ctx.config`` (правило «dict на границе»), схема нужна сборке процесса.
    """

    plugin_class: str = "Plugins.sim.mjpeg_sink.plugin.MjpegSinkPlugin"

    host: Annotated[
        str,
        FieldMeta(description="Адрес, на котором слушает HTTP-раздача"),
    ] = "127.0.0.1"

    port: Annotated[
        int,
        FieldMeta(description="Порт HTTP-раздачи MJPEG"),
    ] = 8091

    jpeg_quality: Annotated[
        int,
        FieldMeta(description="Качество JPEG (cv2.IMWRITE_JPEG_QUALITY), 1..100"),
    ] = 80

    fps_cap: Annotated[
        float,
        FieldMeta(description="Потолок частоты кодирования, кадр/с (0 — без ограничения)"),
    ] = 0.0
