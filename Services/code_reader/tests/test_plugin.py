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

from Services.code_reader.core.sink import ResultSink
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


# --------------------------------------------------------------------------- #
# Находки ревью Ф2 (2026-09-28): каждый тест ниже назван номером находки и
# падает, если снять соответствующую гарантию.
# --------------------------------------------------------------------------- #


class TestНаходкиРевью:
    def test_1_расхождение_терминатора_не_копит_память_молча(self) -> None:
        """Находка 1: поток без нашего терминатора рос в буфере без предела.

        Теперь буфер имеет потолок: он сбрасывается, а причина уходит наружу
        в `last_error` — вместо «connected, кодов нет, ошибок нет».
        """
        plugin = _make_plugin()
        assert plugin.cmd_start_sink({})["status"] == "ok"
        try:
            port = plugin.cmd_get_status({})["port"]
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as conn:
                # 200 КБ потока, в котором нашего терминатора нет вообще.
                conn.sendall(b"X" * 200_000)
                deadline = time.monotonic() + 5.0
                while not plugin._reg.last_error and time.monotonic() < deadline:
                    time.sleep(0.02)
            assert plugin._reg.last_error, "потолок буфера не сработал: приём молчит"
            assert "терминатор" in plugin._reg.last_error
            assert plugin.produce() == []
        finally:
            plugin.cmd_stop_sink({})

    def test_1_пустой_терминатор_отвергается_на_старте(self) -> None:
        """Находка 1 (вторая дорога): `terminator=""` — приём без нарезки."""
        plugin = _make_plugin(terminator="")
        result = plugin.cmd_start_sink({})
        assert result["status"] == "error"
        assert "терминатор" in result["error"]
        assert plugin._reg.sink_state == "stopped"
        assert plugin.cmd_get_status({})["running"] is False

    def test_2_после_stop_состояние_не_перезаписывается_умирающим_потоком(self) -> None:
        """Находка 2: 15 прогонов из 30 давали «слушаем» при погашенном приёме."""
        for _ in range(12):
            plugin = _make_plugin()
            plugin.cmd_start_sink({})
            port = plugin.cmd_get_status({})["port"]
            conn = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            try:
                deadline = time.monotonic() + 2.0
                while plugin._reg.sink_state != "connected" and time.monotonic() < deadline:
                    time.sleep(0.01)
                plugin.cmd_stop_sink({})
                # Никакой паузы: состояние обязано быть «stopped» сразу после
                # возврата команды и остаться таким.
                assert plugin._reg.sink_state == "stopped"
                time.sleep(0.4)
                assert plugin._reg.sink_state == "stopped", "умирающий поток переписал состояние"
            finally:
                conn.close()

    def test_2_stop_гасит_поток_живого_соединения_а_не_только_слушателя(self) -> None:
        """Находка 2, суть: после stop() приёмник обязан ОСЛЕПНУТЬ.

        Прежний `stop()` закрывал только слушающий сокет, и поток уже принятого
        соединения продолжал читать и разбирать пакеты — приём считался погашенным,
        а результаты всё ещё приходили. Проверяем наблюдаемый эффект: пакет,
        отправленный после возврата `stop_sink`, до обработчика не доходит.
        """
        received: list[str] = []
        sink = ResultSink(lambda result: received.append(result.payload), host="127.0.0.1", port=0)
        sink.start()
        try:
            with socket.create_connection(("127.0.0.1", sink.port), timeout=2.0) as conn:
                conn.sendall(b"BEFORE;")
                deadline = time.monotonic() + 2.0
                while not received and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert received == ["BEFORE"], f"до stop() приём не работал: {received}"
                sink.stop()
                assert sink.client_count == 0, "stop() вернулся, оставив соединение в счётчике"
                try:
                    conn.sendall(b"AFTER;")
                except OSError:
                    pass  # соединение уже закрыто — это и есть ожидаемое поведение
                time.sleep(0.4)
            assert received == ["BEFORE"], f"приём остался зрячим после stop(): {received}"
        finally:
            sink.stop()

    # Быстрого stop() НЕТ, и теста на него тоже: замер 2026-09-28 — 188 мс и с
    # закрытием слушающего сокета из другого потока, и без него (на Windows это
    # заблокированный accept не будит). Цена стопа — один шаг чтения 0,2 с; на
    # освобождение порта не влияет. `conn.shutdown()` в stop() оставлен как
    # гигиена и польза на POSIX, но гарантией не объявлен: инъекция его снятия не
    # роняет ни одного теста, потому что ослепление приёма держит флаг стоп.
    def test_4_на_принятом_соединении_включён_keepalive(self) -> None:
        """Находка 4: без keepalive физический обрыв невидим навсегда.

        Проверяем состояние сокета в ядре (`getsockopt`), а не имя вызова. Сам факт
        обнаружения обрыва этим тестом НЕ проверяется — выдернутый кабель на
        localhost не изобразить; проверяется единственное, что проверяемо без
        железа: механизм включён на том сокете, по которому идут коды.
        """
        sink = ResultSink(lambda _result: None, host="127.0.0.1", port=0)
        sink.start()
        try:
            with socket.create_connection(("127.0.0.1", sink.port), timeout=2.0):
                deadline = time.monotonic() + 2.0
                while sink.client_count == 0 and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert sink.client_count == 1
                accepted = [conn for _thread, conn in sink._conns]
                assert accepted, "принятого соединения не видно"
                assert accepted[0].getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
        finally:
            sink.stop()

    def test_2_колбэк_повисшего_потока_не_переписывает_состояние(self) -> None:
        """Находка 2, вторая гарантия: метка запуска.

        Обработчик держим дольше, чем `stop()` готов ждать поток, — тогда поток
        доживает до момента ПОСЛЕ возврата команды и вызывает свой колбэк «соединений
        0». Без сверки с меткой запуска он переписал бы `sink_state` на «слушаем» у
        уже погашенного приёма.
        """
        release = threading.Event()

        plugin = _make_plugin()

        def slow_handler(result: object) -> None:
            release.wait(5.0)

        plugin._on_result = slow_handler  # обработчик занят дольше дедлайна join
        plugin.cmd_start_sink({})
        try:
            port = plugin.cmd_get_status({})["port"]
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as conn:
                conn.sendall(b"SLOW;")
                deadline = time.monotonic() + 2.0
                while plugin._reg.sink_state != "connected" and time.monotonic() < deadline:
                    time.sleep(0.01)
                plugin.cmd_stop_sink({})  # вернётся по дедлайну, поток ещё жив
                assert plugin._reg.sink_state == "stopped"
                release.set()  # поток доживает и вызывает колбэк «соединений 0»
                time.sleep(0.5)
                assert plugin._reg.sink_state == "stopped", (
                    "колбэк повисшего потока переписал состояние погашенного приёма"
                )
        finally:
            release.set()
            plugin.cmd_stop_sink({})

    def test_2_stop_освобождает_порт_сразу_при_живом_соединении(self) -> None:
        """Находка 2 (следствие): порт должен быть свободен к возврату stop()."""
        plugin = _make_plugin()
        plugin.cmd_start_sink({})
        port = plugin.cmd_get_status({})["port"]
        with socket.create_connection(("127.0.0.1", port), timeout=2.0):
            plugin.cmd_stop_sink({})
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.bind(("127.0.0.1", port))  # занято → OSError
            finally:
                probe.close()

    def test_3_обрыв_связи_публикуется_без_потока_кодов(self) -> None:
        """Находка 3: дерево состояния обновлялось только вместе с кодами."""

        class RecordingProxy:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def merge(self, path: str, data: dict) -> None:
                self.calls.append((path, data))

        proxy = RecordingProxy()
        cfg = {"host": "127.0.0.1", "port": _free_port(), "auto_start": False}
        plugin = CodeReaderPlugin()
        plugin.configure(
            PluginContext(
                services=MockProcessServices(name="reader", config=cfg, state_proxy=proxy),
                config=cfg,
            )
        )
        plugin.cmd_start_sink({})
        try:
            port = plugin.cmd_get_status({})["port"]
            conn = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            deadline = time.monotonic() + 2.0
            while plugin._reg.sink_state != "connected" and time.monotonic() < deadline:
                time.sleep(0.01)
            conn.close()  # обрыв БЕЗ единого кода
            deadline = time.monotonic() + 2.0
            while plugin._reg.sink_state != "listening" and time.monotonic() < deadline:
                plugin.produce()
                time.sleep(0.01)
            states = [data["sink_state"] for _path, data in proxy.calls]
            assert "connected" in states, f"подключение не опубликовано: {states}"
            assert states[-1] == "listening", f"обрыв не опубликован: {states}"
            last = proxy.calls[-1][1]
            # dropped/last_error/pending раньше в дерево не попадали вовсе.
            assert {"dropped", "last_error", "pending"} <= set(last)
        finally:
            plugin.cmd_stop_sink({})

    def test_3_пустой_produce_не_публикует_повторно(self) -> None:
        """Цена находки 3: на 20 Гц пустой проход не имеет права шуметь."""

        class CountingProxy:
            def __init__(self) -> None:
                self.count = 0

            def merge(self, path: str, data: dict) -> None:
                self.count += 1

        proxy = CountingProxy()
        cfg = {"host": "127.0.0.1", "port": _free_port(), "auto_start": False}
        plugin = CodeReaderPlugin()
        plugin.configure(
            PluginContext(
                services=MockProcessServices(name="reader", config=cfg, state_proxy=proxy),
                config=cfg,
            )
        )
        plugin.cmd_start_sink({})
        try:
            before = proxy.count
            for _ in range(50):
                plugin.produce()
            assert proxy.count == before, f"пустые проходы опубликовали {proxy.count - before} дельт"
        finally:
            plugin.cmd_stop_sink({})

    def test_6_счётчики_не_теряются_при_двух_потоках_соединений(self) -> None:
        """Находка 6: инкременты вне замка терялись (175 из 160 000)."""
        import sys

        plugin = _make_plugin()
        plugin.cmd_start_sink({})
        old_interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)  # провоцируем переключения между потоками
        try:
            port = plugin.cmd_get_status({})["port"]
            per_thread, threads_count = 2000, 4

            def sender() -> None:
                with socket.create_connection(("127.0.0.1", port), timeout=2.0) as conn:
                    conn.sendall(b"A;" * per_thread)

            threads = [threading.Thread(target=sender) for _ in range(threads_count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(10.0)
            expected = per_thread * threads_count
            deadline = time.monotonic() + 10.0
            while plugin._reg.total_reads < expected and time.monotonic() < deadline:
                plugin.produce()
                time.sleep(0.01)
            assert plugin._reg.total_reads == expected, (
                f"потеряно {expected - plugin._reg.total_reads} инкрементов из {expected}"
            )
            assert plugin._seq == expected
        finally:
            sys.setswitchinterval(old_interval)
            plugin.cmd_stop_sink({})

    def test_9_обрыв_по_ошибке_сокета_называет_причину(self) -> None:
        """Находка 9, дорога OSError: прибор оборвал связь грубо (RST).

        Прежний `except OSError: break` не говорил ничего. Отдельный тест нужен
        потому, что чистое закрытие (`recv` вернул b"") идёт ДРУГОЙ ветвью — и
        инъекция это показала: снятие отчёта из ветви OSError не ронялo тест на
        чистое закрытие.
        """
        import struct

        plugin = _make_plugin()
        plugin.cmd_start_sink({})
        try:
            port = plugin.cmd_get_status({})["port"]
            conn = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            # SO_LINGER с нулевым таймаутом: close() шлёт RST вместо FIN, и на стороне
            # приёма recv падает с ошибкой, а не возвращает пустоту.
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("hh", 1, 0))
            conn.sendall(b"QR-10MM;")
            deadline = time.monotonic() + 2.0
            while not plugin.produce() and time.monotonic() < deadline:
                time.sleep(0.01)
            conn.close()  # RST
            deadline = time.monotonic() + 3.0
            while not plugin._reg.last_error and time.monotonic() < deadline:
                time.sleep(0.02)
            assert plugin._reg.last_error, "грубый обрыв прошёл молча"
            assert "обрыв" in plugin._reg.last_error, plugin._reg.last_error
        finally:
            plugin.cmd_stop_sink({})

    def test_9_потеря_хвоста_при_чистом_закрытии_называется_в_ошибке(self) -> None:
        """Находка 9, дорога чистого закрытия: недособранный пакет потерян."""
        plugin = _make_plugin()
        plugin.cmd_start_sink({})
        try:
            port = plugin.cmd_get_status({})["port"]
            conn = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            conn.sendall("QR-НЕДОСОБРАН".encode())  # без терминатора
            time.sleep(0.2)
            conn.close()
            deadline = time.monotonic() + 3.0
            while not plugin._reg.last_error and time.monotonic() < deadline:
                time.sleep(0.02)
            assert plugin._reg.last_error, "обрыв с потерей хвоста прошёл молча"
            assert "хвост" in plugin._reg.last_error
        finally:
            plugin.cmd_stop_sink({})

    def test_12_приёмник_соответствует_объявленному_контракту(self) -> None:
        """Находка 12: Protocol в interfaces.py не проверял никто."""
        from Services.code_reader.interfaces import CodeReaderSinkProtocol

        plugin = _make_plugin()
        plugin.cmd_start_sink({})
        try:
            assert isinstance(plugin._sink, CodeReaderSinkProtocol)
        finally:
            plugin.cmd_stop_sink({})

    # Находка 13 (сокет закрывается при отказе `bind`) остаётся БЕЗ теста: в CPython
    # локальный сокет закрывается подсчётом ссылок сразу после выхода из `start()`,
    # поэтому разницы «закрыли сами» и «закрыл GC» тест не видит — инъекция это
    # подтвердила (снятие `server.close()` не уронило ни одного теста). Правка
    # оставлена как гигиена, её отсутствие теста названо в STATUS.md.
