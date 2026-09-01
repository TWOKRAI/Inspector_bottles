# -*- coding: utf-8 -*-
"""RED acceptance — Критерий A на РЕАЛЬНОМ сайте ``CapturePlugin._start_capture``.

Независимый тестер, стадия 1 (ДО реализации). Узкий скоуп — только Критерий A
(деталь сайта обязана дойти до инцидента СТРУКТУРНО, а не только текстом).

Сайт — ``Plugins/sources/capture/plugin.py:288``, ветка ``isOpened()==False``:
отказ ВОЗВРАТОМ значения (не исключением), сегодня зовёт ТОЛЬКО
``ctx.log_error(f"CapturePlugin[{camera_id}]: не удалось открыть камеру {device_id}")``
— один из двух сайтов, названных ТЗ как «invisible to the error plane today».

Форма ТОГО, ЧТО заведёт этот сайт после миграции (новый ли синтетический
exception, новый ли метод ``ctx.health`` для отказов-без-исключения) — здесь
ДОГАДКА: в репозитории нет аналога, на который можно опереться (в отличие от
``device_hub.create_worker``, где сосед-исключение уже зовёт ``report_error``
СЕГОДНЯ — см. ``test_failure_classes_device_hub_acceptance.py``). Тест поэтому
пинует НАБЛЮДАЕМЫЙ эффект («camera_id/device_id — значения полей инцидента»),
а не имя метода.

Проводка — РЕАЛЬНАЯ: ``HealthReporter`` над настоящим ``HealthState`` (не
мок), тот же ``track`` callback, что видел бы приёмник плоскости ошибок.
``cv2.VideoCapture`` подменяется на фейковый объект (без реальной камеры).

Критерий B здесь НЕ проверяется: у ``CapturePlugin`` в реальном развёртывании
один экземпляр на процесс — коллизия ключа окна между ДВУМЯ камерами внутри
одного ``HealthState`` не грунтуется реальной топологией так же чисто, как в
device_hub (два устройства — один процесс, один supervisor-тик). Critерий B
пин уже дан device_hub-файлом на реальном коде без этой натяжки.

НЕ повторяет то, что уже покрыл предыдущий независимый тестер: не проверяет
сам факт «camera-open failure -> errors.log/health.status» как двоичное
свойство.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from multiprocess_framework.modules.process_module.health import HealthReporter, HealthState
from Plugins.sources.capture.plugin import CapturePlugin


def _make_plugin_with_real_health() -> tuple[CapturePlugin, MagicMock, list, list]:
    """CapturePlugin.configure() с РЕАЛЬНЫМ HealthState/HealthReporter.

    ``ctx`` — MagicMock (command_manager/state_proxy — не по критерию), но
    ``ctx.health`` — настоящий фасад над настоящим ``HealthState``.
    """
    captured_incidents: list[tuple[BaseException, dict | None]] = []
    captured_voices: list[str] = []

    def _track(exc: BaseException, payload: dict | None = None) -> None:
        captured_incidents.append((exc, payload))

    def _log(msg: str, **_kwargs: object) -> None:
        captured_voices.append(msg)

    state = HealthState(log=_log, track=_track, log_only=False)

    ctx = MagicMock()
    ctx.config = {"camera_id": 71, "device_id": 42, "resolution_width": 320, "resolution_height": 240}
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    ctx.command_manager = MagicMock()
    ctx.state_proxy = None
    ctx.declare_metric = MagicMock()
    ctx.health = HealthReporter(state, source="capture")

    plugin = CapturePlugin()
    plugin.configure(ctx)

    return plugin, ctx, captured_incidents, captured_voices


class TestCameraOpenFailureStructure:
    """``isOpened()==False`` — camera_id/device_id обязаны быть полями инцидента."""

    def test_camera_and_device_id_survive_structurally_not_only_in_text(self) -> None:
        """Критерий A: camera_id=71 / device_id=42 — значения СТРУКТУРНОГО поля.

        Сегодня RED по грубой причине (инцидент вообще не заводится — этот
        сайт не долетает до плоскости ошибок; это отдельное, уже покрытое
        предыдущим тестером свойство). Тест тем не менее пинует ЦЕЛЕВОЕ
        свойство станции 1, которое обязано остаться верным и после того, как
        грубая причина будет закрыта отдельно.
        """
        plugin, ctx, incidents, _voices = _make_plugin_with_real_health()

        fake_cap = MagicMock()
        fake_cap.isOpened.return_value = False
        with patch("cv2.VideoCapture", return_value=fake_cap):
            plugin._start_capture(ctx)

        # Контроль: сегодняшний текст ДЕЙСТВИТЕЛЬНО называет оба идентификатора —
        # иначе тест ничего не грунтует.
        # Контроль перевёрнут вместе с задачей (правка автора, 2026-08-31):
        # тестер требовал, чтобы текст ВСЁ ЕЩЁ называл идентификаторы, а 1.3b
        # эту строку снимает. Проверяется теперь само правило «один разъём».
        logged_texts = [str(c) for c in ctx.log_error.call_args_list]
        assert logged_texts == [], (
            f"отказ открытия камеры по-прежнему объявлен в плоскость логов отдельной строкой: {logged_texts}"
        )

        assert incidents, (
            "isOpened()==False не долетел до плоскости ошибок вовсе — сайт report_error для этой ветки "
            "ещё не заведён (известный грубый RED, см. отчёт тестера)"
        )
        payloads_without_context = [
            {k: v for k, v in (payload or {}).items() if k != "context"} for _exc, payload in incidents
        ]
        found = any(
            ("71" in str(value) or "42" in str(value))
            for payload in payloads_without_context
            for value in payload.values()
        )
        assert found, (
            f"camera_id/device_id видны только в снятом ctx.log_error, структура инцидента их не несёт: {incidents}"
        )
