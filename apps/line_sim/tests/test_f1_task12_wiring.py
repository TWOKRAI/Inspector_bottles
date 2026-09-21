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


def test_frame_door_is_wired_source_to_sink() -> None:
    """Пин: дверь кадров проведена ЯВНЫМ проводом `camera` → `mjpeg`.

    Форма выбрана арбитражем CTO 2026-09-21 (вариант «а»): у источника
    внутрипроцессной цепочки не бывает — `SourceProducer` шлёт результат
    `produce()` по IPC в `chain_targets`, а не соседнему плагину. Поэтому сток
    живёт отдельным процессом, а провод объявлен в `wires`.

    Умирает при удалении строки `wires` — проверено инъекцией: сборка падает
    `BlueprintError: Вход 'mjpeg.mjpeg_sink.frame' (image/bgr) не подключен`.
    Этот тест сторожит именно провод, а не число плагинов: прежняя его версия
    пинила одно-процессную форму, которая собиралась успешно и МОЛЧА не работала.
    """
    import yaml

    raw = yaml.safe_load((_APP_YAML.parent / "pipeline.yaml").read_text(encoding="utf-8"))
    wires = raw.get("wires") or []
    assert any(
        w.get("source") == "camera.camera_service.frame"
        and w.get("target") == "mjpeg.mjpeg_sink.frame"
        for w in wires
    ), f"провод camera.camera_service.frame → mjpeg.mjpeg_sink.frame не объявлен: wires={wires}"

    # Источник обязан адресовать сток: без chain_targets провод объявлен, но
    # рантайм ничего не шлёт — сборка при этом проходит.
    camera = next(p for p in raw["processes"] if p["process_name"] == "camera")
    assert camera.get("chain_targets") == ["mjpeg"], (
        f"camera.chain_targets = {camera.get('chain_targets')!r}; источник шлёт кадры "
        f"ТОЛЬКО в chain_targets (source_producer.py), провод в wires сам по себе "
        f"данные не гонит"
    )
    assert camera.get("chain_targets") != ["camera"], (
        "chain_targets=[camera] — отправка самому себе: кадры доходят и приёмка "
        "зеленеет, но сток pass-through возвращает item в свою же очередь "
        "(петля, замер CTO: раздача ×3.2 от темпа источника, delivery_failed в stderr)"
    )


def test_build_succeeds_with_the_declared_wiring() -> None:
    """Пин: объявленная проводка ДЕЙСТВИТЕЛЬНО собирается (валидатор блюпринта проходит)."""
    app = build_app(_APP_YAML)
    cfg = app._get_processes_config()  # noqa: SLF001 — пин внутреннего контракта сборки
    assert cfg["mjpeg"]["config"]["plugins"][0]["plugin_name"] == "mjpeg_sink"
    assert cfg["camera"]["config"]["chain_targets"] == ["mjpeg"]


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
