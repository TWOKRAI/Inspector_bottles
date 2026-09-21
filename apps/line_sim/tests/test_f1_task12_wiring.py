# -*- coding: utf-8 -*-
"""Проводка сим-приложения собирается ЦЕЛИКОМ — тест на настоящих объектах.

**Зачем отдельный файл.** Все тесты ``mjpeg_sink`` (и приёмочные, и hazard) строят
плагин руками поверх mock-контекста. Это доказывает плагин, но не доказывает, что
приложение его ПОДНИМАЕТ. Живой стенд Task 1.2 (2026-09-21) показал разрыв: 175
тестов зелёные, а в реальном процессе ``camera`` плагин был ОДИН
(``PluginOrchestrator[camera]: 1 плагин(ов)``), порт 8091 не открывался, и в
``errors.log`` — пусто. Ровно случай «тест на фальшивом харнессе доказывает харнесс».

Причина была во фреймворке: ``ProcessConfig.as_generic_config`` пересобирает список
плагинов из ``_restore_plugin_configs()``
(``process_manager_module/topology/blueprint.py:248``), а та молча пропускает плагин
без соседнего модуля ``config`` — и ветка ``if plugin_configs:`` строит процесс только
из отфильтрованного списка. Блокер снят добавлением ``Plugins/sim/mjpeg_sink/config.py``;
сам дефект фреймворка заведён в ``docs/claude/OPEN_QUESTIONS.md``.

Этот тест сторожит СЛЕДСТВИЕ, а не причину: сколько бы ни менялся механизм внутри,
объявленные в ``pipeline.yaml`` плагины обязаны доезжать до конфига процесса.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from multiprocess_framework.modules.app_module import build_app

_APP_YAML = Path(__file__).resolve().parents[1] / "app.yaml"


@pytest.fixture(scope="module")
def processes_config() -> dict:
    """Собрать НАСТОЯЩЕЕ приложение и отдать конфиг процессов."""
    app = build_app(_APP_YAML)
    return app._get_processes_config()  # noqa: SLF001 — пин внутреннего контракта сборки


def test_camera_process_carries_both_declared_plugins(processes_config: dict) -> None:
    """Пин: процесс `camera` несёт ОБА объявленных плагина, в порядке цепочки.

    Умирает при удалении `Plugins/sim/mjpeg_sink/config.py` — проверено инъекцией:
    без него сборка отдаёт ['camera_service'], порт 8091 не открывается.
    """
    camera = processes_config["camera"]
    names = [p.get("plugin_name") for p in camera["config"]["plugins"]]
    assert names == ["camera_service", "mjpeg_sink"], (
        f"процесс camera собран с плагинами {names}, ожидались оба объявленных в "
        f"pipeline.yaml в порядке цепочки — сток, потерянный здесь, не открывает "
        f"порт 8091 и не сообщает об этом ни строкой"
    )


def test_every_declared_plugin_reaches_its_process(processes_config: dict) -> None:
    """Общий сторож: ни один плагин из pipeline.yaml не теряется по дороге.

    Сравнение идёт с САМИМ pipeline.yaml (литерал не дублируем — источником
    правды здесь является декларация, а тест ловит РАСХОЖДЕНИЕ сборки с ней).
    """
    import yaml

    declared_raw = yaml.safe_load((_APP_YAML.parent / "pipeline.yaml").read_text(encoding="utf-8"))
    declared = {
        proc["process_name"]: [p["plugin_name"] for p in proc.get("plugins", [])]
        for proc in declared_raw["processes"]
    }
    built = {
        name: [p.get("plugin_name") for p in proc["config"]["plugins"]]
        for name, proc in processes_config.items()
    }
    assert built == declared, (
        f"сборка разошлась с pipeline.yaml.\n  объявлено: {declared}\n  собрано:   {built}"
    )
