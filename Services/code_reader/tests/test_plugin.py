# -*- coding: utf-8 -*-
"""Контрактные тесты CodeReaderPlugin — регистрация, produce(), телеметрия.

Сквозной путь проверяется как в бою: плагин поднимает приёмник на эфемерном
порту, тест играет роль прибора (обычный сокет — ровно то, что делает
`tools/reader_sim.py`), и код должен доехать до `produce()`.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
)

from Services.code_reader.plugin.plugin import CodeReaderPlugin

LIVE_PACKET = b"QR-30MM;"


def _free_port() -> int:
    """Занять и отпустить порт — register запрещает 0, а фиксированный занят стендом."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _make_plugin(**config) -> CodeReaderPlugin:
    """Сконструировать плагин со свободным портом приёма, но без start()."""
    cfg = {"host": "127.0.0.1", "port": _free_port(), "auto_start": False, **config}
    services = MockProcessServices(name="reader", config=cfg)
    plugin = CodeReaderPlugin()
    plugin.configure(PluginContext(services=services, config=cfg))
    return plugin


@pytest.fixture()
def running_plugin():
    """Плагин с поднятым приёмом; гасится после теста."""
    plugin = _make_plugin()
    assert plugin.cmd_start_sink({})["status"] == "ok"
    try:
        yield plugin
    finally:
        plugin.cmd_stop_sink({})


def _send(plugin: CodeReaderPlugin, *payloads: bytes, pause: float = 0.1) -> None:
    """Прислать пакеты как прибор: подключиться к приёмнику и отправить."""
    port = plugin.cmd_get_status({})["port"]
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as conn:
        for i, payload in enumerate(payloads):
            if i:
                # Пауза обязательна: без неё TCP склеивает отправки в один recv,
                # и сборка разорванного пакета остаётся непроверенной.
                time.sleep(pause)
            conn.sendall(payload)
        time.sleep(pause)


def _wait_items(plugin: CodeReaderPlugin, count: int, timeout: float = 3.0) -> list[dict]:
    """Дождаться `count` items через produce() (приём асинхронный)."""
    items: list[dict] = []
    deadline = time.monotonic() + timeout
    while len(items) < count and time.monotonic() < deadline:
        items.extend(plugin.produce())
        if len(items) < count:
            time.sleep(0.02)
    return items


class TestРегистрация:
    def test_плагин_виден_реестру_как_source(self) -> None:
        from multiprocess_framework.modules.process_module.plugins.registry import (
            PluginRegistry,
        )
        import Services.code_reader.plugin.plugin  # noqa: F401 — триггерит @register_plugin

        entry = PluginRegistry.get("code_reader")
        assert entry is not None
        assert entry.category == "source"
        assert "code_reader" in {e.name for e in PluginRegistry.filter("source")}

    def test_конфиг_указывает_на_класс_плагина(self) -> None:
        from Services.code_reader.plugin.config import CodeReaderPluginConfig

        cfg = CodeReaderPluginConfig()
        assert cfg.plugin_class.endswith("CodeReaderPlugin")
        # SHM-слот не объявляется: наружу уходит строка, а не кадр.
        assert cfg.memory is None

    def test_выходной_порт_один_и_называется_code(self) -> None:
        assert [p.name for p in CodeReaderPlugin.outputs] == ["code"]
        assert CodeReaderPlugin.inputs == []


class TestProduce:
    def test_без_кода_пусто_а_не_ошибка(self, running_plugin) -> None:
        assert running_plugin.produce() == []

    def test_живой_пакет_доходит_до_produce(self, running_plugin) -> None:
        _send(running_plugin, LIVE_PACKET)
        items = _wait_items(running_plugin, 1)
        assert len(items) == 1
        item = items[0]
        assert item["code"] == "QR-30MM"
        assert item["status"] == "ok"
        assert item["raw_hex"] == "51 52 2D 33 30 4D 4D 3B"
        assert item["reader_id"] == "id3013"
        assert item["seq_id"] == 1

    def test_seq_id_растёт_а_не_стоит(self, running_plugin) -> None:
        _send(running_plugin, b"A;", b"B;")
        items = _wait_items(running_plugin, 2)
        assert [i["code"] for i in items] == ["A", "B"]
        assert [i["seq_id"] for i in items] == [1, 2]

    def test_два_кода_в_одном_сегменте_дают_два_item(self, running_plugin) -> None:
        _send(running_plugin, b"A;B;")
        items = _wait_items(running_plugin, 2)
        assert [i["code"] for i in items] == ["A", "B"]

    def test_код_разорванный_на_два_сегмента_собирается_в_один(self, running_plugin) -> None:
        _send(running_plugin, b"QR-30", b"MM;")
        items = _wait_items(running_plugin, 1)
        assert [i["code"] for i in items] == ["QR-30MM"]

    def test_produce_не_блокирует_когда_данных_нет(self, running_plugin) -> None:
        start = time.monotonic()
        for _ in range(5):
            running_plugin.produce()
        # Контракт source-плагина: управление возвращается быстрее двух интервалов
        # кадра. Пять пустых вызовов не имеют права занять даже 150 мс.
        assert time.monotonic() - start < 0.15

    def test_produce_очищает_очередь(self, running_plugin) -> None:
        _send(running_plugin, b"A;")
        assert _wait_items(running_plugin, 1)
        assert running_plugin.produce() == []


class TestТелеметрия:
    def test_счётчики_исходов_растут_отдельно(self, running_plugin) -> None:
        _send(running_plugin, b"A;", b"NoRead;")
        _wait_items(running_plugin, 2)
        reg = running_plugin._reg
        assert (reg.total_reads, reg.no_reads, reg.bad_reads) == (1, 1, 0)
        # «Кода нет» не затирает последний удачный код — иначе на экране линии
        # пропадало бы то, что реально прочиталось.
        assert reg.last_code == "A"
        assert reg.last_status == "no_code"

    def test_состояние_связи_отличает_слушаем_от_подключён(self, running_plugin) -> None:
        assert running_plugin._reg.sink_state == "listening"
        port = running_plugin.cmd_get_status({})["port"]
        with socket.create_connection(("127.0.0.1", port), timeout=2.0):
            deadline = time.monotonic() + 2.0
            while running_plugin._reg.sink_state != "connected" and time.monotonic() < deadline:
                time.sleep(0.02)
            assert running_plugin._reg.sink_state == "connected"
            assert running_plugin.cmd_get_status({})["clients"] == 1
        deadline = time.monotonic() + 2.0
        while running_plugin._reg.sink_state != "listening" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert running_plugin._reg.sink_state == "listening"

    def test_сброс_счётчиков(self, running_plugin) -> None:
        _send(running_plugin, b"A;")
        _wait_items(running_plugin, 1)
        running_plugin.cmd_reset_stats({})
        status = running_plugin.cmd_get_status({})
        assert status["total_reads"] == 0
        assert status["last_code"] == ""
        assert status["history"] == []

    def test_переполнение_очереди_считается_а_не_растёт_память(self, running_plugin) -> None:
        from Services.code_reader.plugin.plugin import _QUEUE_LIMIT
        from Services.code_reader.core.result import ReadResult, ReadStatus

        for i in range(_QUEUE_LIMIT + 5):
            running_plugin._on_result(ReadResult(raw=b"X;", payload=f"X{i}", status=ReadStatus.OK))
        assert len(running_plugin._queue) == _QUEUE_LIMIT
        assert running_plugin._reg.dropped == 5


class TestУправлениеПриёмом:
    def test_повторный_старт_идемпотентен(self, running_plugin) -> None:
        port = running_plugin.cmd_get_status({})["port"]
        assert running_plugin.cmd_start_sink({})["port"] == port

    def test_стоп_освобождает_порт_и_повторный_стоп_безопасен(self) -> None:
        plugin = _make_plugin()
        plugin.cmd_start_sink({})
        port = plugin.cmd_get_status({})["port"]
        plugin.cmd_stop_sink({})
        assert plugin.cmd_stop_sink({})["running"] is False
        assert plugin._reg.sink_state == "stopped"
        # Порт свободен: значит его можно занять снова.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
        finally:
            probe.close()

    def test_порт_занятый_таким_же_приёмником_не_делится_молча(self) -> None:
        """Второй приёмник на том же порту обязан получить отказ.

        На Windows `SO_REUSEADDR` разрешает двум слушателям делить порт: bind
        проходит, а пакеты уходят чужому — ровно это сорвало живой прогон
        2026-09-28. Предыдущий тест этого не ловил: его держатель порта флага не
        ставил, и отказ приходил по другой причине.
        """
        first = _make_plugin()
        assert first.cmd_start_sink({})["status"] == "ok"
        port = first.cmd_get_status({})["port"]
        second = _make_plugin(port=port)
        try:
            result = second.cmd_start_sink({})
            assert result["status"] == "error", "порт разделён молча — приём слепой"
            assert second._reg.last_error
        finally:
            second.cmd_stop_sink({})
            first.cmd_stop_sink({})

    def test_занятый_порт_не_роняет_процесс_а_пишет_причину(self) -> None:
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        busy_port = holder.getsockname()[1]
        plugin = _make_plugin(port=busy_port)
        try:
            result = plugin.cmd_start_sink({})
            assert result["status"] == "error"
            assert plugin._reg.sink_state == "stopped"
            assert plugin._reg.last_error
            # Процесс жив, produce() продолжает работать.
            assert plugin.produce() == []
        finally:
            plugin.cmd_stop_sink({})
            holder.close()

    def test_auto_start_поднимает_приём_на_старте(self) -> None:
        plugin = _make_plugin(auto_start=True)
        try:
            plugin.start(plugin._ctx)
            assert plugin._reg.sink_state == "listening"
        finally:
            plugin.shutdown(plugin._ctx)
        assert plugin._reg.sink_state == "stopped"


class TestФорматИзКонфига:
    def test_терминатор_и_тексты_берутся_из_конфига(self) -> None:
        plugin = _make_plugin(
            terminator="\r\n",
            prefix="<",
            no_code_text="__NONE__",
            bad_code_text="__BAD__",
            reader_id="stand",
        )
        plugin.cmd_start_sink({})
        try:
            _send(plugin, b"<CODE1\r\n", b"<__NONE__\r\n", b"<__BAD__\r\n")
            items = _wait_items(plugin, 3)
            assert [i["code"] for i in items] == ["CODE1", "__NONE__", "__BAD__"]
            assert [i["status"] for i in items] == ["ok", "no_code", "bad_code"]
            assert items[0]["reader_id"] == "stand"
        finally:
            plugin.cmd_stop_sink({})


def test_публикация_состояния_в_state_proxy() -> None:
    """produce() публикует телеметрию в реактивное дерево (живой GUI)."""

    class RecordingProxy:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def merge(self, path: str, data: dict) -> None:
            self.calls.append((path, data))

    proxy = RecordingProxy()
    cfg = {"host": "127.0.0.1", "port": _free_port(), "auto_start": False}
    services = MockProcessServices(name="reader", config=cfg, state_proxy=proxy)
    plugin = CodeReaderPlugin()
    plugin.configure(PluginContext(services=services, config=cfg))
    plugin.cmd_start_sink({})
    try:
        _send(plugin, LIVE_PACKET)
        assert _wait_items(plugin, 1)
    finally:
        plugin.cmd_stop_sink({})

    assert proxy.calls, "телеметрия не опубликована"
    path, data = proxy.calls[-1]
    assert path == "processes.reader.state.code_reader"
    assert data["last_code"] == "QR-30MM"
    assert data["history"][-1]["code"] == "QR-30MM"


def test_симулятор_прибора_совпадает_с_форматом_плагина() -> None:
    """`tools/reader_sim.py` шлёт ровно то, что плагин разбирает."""
    from Services.code_reader.tools.reader_sim import packets, run

    plugin = _make_plugin()
    plugin.cmd_start_sink({})
    try:
        port = plugin.cmd_get_status({})["port"]
        payloads = packets(["QR-10MM", "QR-20MM"], 4, no_read_every=2)
        thread = threading.Thread(target=run, args=("127.0.0.1", port, payloads, 0.05), kwargs={"verbose": False})
        thread.start()
        items = _wait_items(plugin, 4)
        thread.join(3.0)
    finally:
        plugin.cmd_stop_sink({})

    assert [i["code"] for i in items] == ["QR-10MM", "NoRead", "QR-10MM", "NoRead"]
    assert [i["status"] for i in items] == ["ok", "no_code", "ok", "no_code"]
