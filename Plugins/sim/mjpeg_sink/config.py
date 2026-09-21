# -*- coding: utf-8 -*-
"""Конфиг ``MjpegSinkPlugin`` — параметры HTTP-раздачи кадров.

**Этот файл обязателен не ради красоты схемы, а потому что без него плагин молча
исчезает из процесса.** Найдено живым стендом Task 1.2 (2026-09-21), диагноз
воспроизведён: ``ProcessConfig.as_generic_config`` пересобирает список плагинов
процесса из ``_restore_plugin_configs()``
(``process_manager_module/topology/blueprint.py:248``), а та пропускает плагин,
рядом с которым нет модуля ``config`` (``continue`` на ``ImportError``, там же
строка ~850). Дальше ветка ``if plugin_configs:`` строит процесс ТОЛЬКО из
отфильтрованного списка — и сосед без конфига пропадает без единой строки в логе.

Замер, доказывающий механизм: процесс ``camera`` объявляет ``camera_service``
(конфиг есть) и ``mjpeg_sink``. БЕЗ этого файла сборка даёт
``camera.config.plugins == ['camera_service']`` и порт 8091 не открывается;
С ним — ``['camera_service', 'mjpeg_sink']``. Тест, который это сторожит:
``apps/line_sim/tests/test_f1_task12_wiring.py``.

``robot_host`` конфига не имеет и работает — потому что в своём процессе он ОДИН:
отфильтрованный список выходит пустым, срабатывает else-ветка и берёт всех.
Дефект проявляется только при СМЕШЕНИИ в одном процессе плагинов с конфигом и без.
Заведён отдельно (``docs/claude/OPEN_QUESTIONS.md``) — чинить надо во фреймворке,
здесь лишь снят блокер задачи.
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
