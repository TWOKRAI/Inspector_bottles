# -*- coding: utf-8 -*-
"""Task 2.0 — независимый RED (тестер, worktree на a0edf74a, ДО реализации).

Контракт взят из Acceptance criteria/REDS плана (``plans/line-sim/phase-2-belt-truth.md``,
Task 2.0), НЕ из подсмотренной реализации: плагин в процессе на голом
``GenericProcess`` обязан видеть ``ctx.state_proxy is not None`` и в
``configure_managers(ctx)``, и в ``configure(ctx)``; останов процесса обязан
отправить ровно один ``state.unsubscribe_all`` с ``subscriber == <имя процесса>``.

Один процесс, БЕЗ спавна (``multiprocessing.Process`` не участвует) — плагин
и ``GenericProcess`` живут в этом же интерпретаторе. ``RouterManager`` — НАСТОЯЩИЙ
объект (``multiprocess_framework.modules.router_module.RouterManager``), тем же
приёмом, что и ``test_process_communication.py::TestSendToProcessRoutesThroughRouter``:
фейковый только ``queue_registry`` (транспортный сток), не сам роутер и не
``StateProxy``. ``_init_queues`` подменён no-op'ом (ставит фейковый registry
напрямую в атрибут) — обходит инфраструктуру shared_resources/multiprocessing.Queue,
не участвующую в проверяемом контракте.

Сегодня (до Task 2.0): ``GenericProcess._init_custom_managers`` не создаёт
``_state_proxy`` вовсе (это делает только прототипный ``GenericProcessApp``,
carve-out ещё не влит) — оба теста ниже красные по AssertionError, не по
ошибке импорта/коллекции.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.generic.generic_process import GenericProcess
from multiprocess_framework.modules.process_module.plugins import PluginContext, ProcessModulePlugin

#: Плагин создаётся оркестратором внутри (``cls()`` без аргументов, dotted-path
#: import) — у теста нет прямой ссылки на инстанс, поэтому результат кладётся
#: в module-level словарь и читается после boot. Сбрасывается в начале каждого
#: теста, не через фикстуру: единственный источник записи — сам плагин, гонки
#: между тестами нет (один процесс, один boot за тест).
_CAPTURE: dict[str, object] = {}


class _StateProxyProbePlugin(ProcessModulePlugin):
    """Тестовый плагин: фиксирует ``ctx.state_proxy`` на обоих хуках lifecycle."""

    name = "state_proxy_probe"
    category = "utility"
    inputs: list = []
    outputs: list = []

    def configure_managers(self, ctx: PluginContext) -> None:
        _CAPTURE["configure_managers"] = ctx.state_proxy

    def configure(self, ctx: PluginContext) -> None:
        _CAPTURE["configure"] = ctx.state_proxy
        # Подписка (fire-and-forget, sync=False — сервера в этом тесте нет,
        # ждать sub_id от него нечего) — единственный способ довести
        # StateProxy._sub_ids до непустого множества, от которого зависит
        # state.unsubscribe_all на shutdown (proxy/state_proxy.py:1256).
        if ctx.state_proxy is not None:
            ctx.state_proxy.subscribe("sim.belt.*", lambda _deltas: None, sync=False)

    def shutdown(self, ctx: PluginContext) -> None:
        pass


class _FakeQueueRegistry:
    """Захватывает исходящие сообщения — тот же приём, что ``test_process_communication.py``.

    Роутер настоящий; фейковый только транспортный сток, куда он складывает
    сообщения при fallback-адресации по ``targets`` (см. ``RouterManager._do_send``,
    ветка U1).
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, dict]] = []

    def send_to_queue(self, target: str, qtype: str, msg: dict) -> bool:
        self.sent.append((target, qtype, msg))
        return True

    def register_process_queues(self, *_a: object, **_kw: object) -> None:
        """No-op — communication-слой зовёт это при боте; фейку не нужны реальные очереди."""


def _make_probe_process(process_name: str) -> tuple[GenericProcess, _FakeQueueRegistry]:
    """Собрать один ``GenericProcess`` с ``_StateProxyProbePlugin``, без спавна."""
    plugin_class_path = f"{_StateProxyProbePlugin.__module__}._StateProxyProbePlugin"
    proc = GenericProcess(
        name=process_name,
        config={
            "config": {
                "plugins": [
                    {"plugin_class": plugin_class_path, "plugin_name": "state_proxy_probe"},
                ]
            }
        },
    )
    fake_qr = _FakeQueueRegistry()

    def _init_queues_stub() -> None:
        proc.queues = {}
        proc.queue_registry = fake_qr
        proc.memory_manager = None

    proc._init_queues = _init_queues_stub  # type: ignore[method-assign]
    return proc, fake_qr


class TestBareGenericProcessPluginSeesStateProxy:
    def test_bare_generic_process_plugin_sees_state_proxy(self) -> None:
        """Acceptance: ctx.state_proxy is not None и в configure_managers, и в configure."""
        _CAPTURE.clear()
        proc, _fake_qr = _make_probe_process("proc_probe_a")
        try:
            ok = proc.initialize()
            assert ok is True, "GenericProcess.initialize() не дошёл до конца"

            assert "configure_managers" in _CAPTURE, "плагин не получил configure_managers(ctx)"
            assert _CAPTURE["configure_managers"] is not None, (
                "ctx.state_proxy is None в configure_managers(ctx) — голый GenericProcess "
                "не создаёт state_proxy (Task 2.0 ещё не влита)"
            )

            assert "configure" in _CAPTURE, "плагин не получил configure(ctx)"
            assert _CAPTURE["configure"] is not None, (
                "ctx.state_proxy is None в configure(ctx) — голый GenericProcess "
                "не создаёт state_proxy (Task 2.0 ещё не влита)"
            )
        finally:
            proc.shutdown()


class TestShutdownUnsubscribesAll:
    def test_shutdown_unsubscribes_all(self) -> None:
        """Acceptance: останов процесса шлёт ровно 1 state.unsubscribe_all,
        subscriber == имя процесса."""
        _CAPTURE.clear()
        proc, fake_qr = _make_probe_process("proc_probe_b")
        try:
            ok = proc.initialize()
            assert ok is True, "GenericProcess.initialize() не дошёл до конца"

            proc.shutdown()

            # send_async уходит в фоновый AsyncSender — короткий опрос вместо
            # фиксированного sleep (дедлайн 2.0 с, как в остальных REDS плана).
            deadline = time.monotonic() + 2.0
            unsub_msgs: list[dict] = []
            while time.monotonic() < deadline:
                unsub_msgs = [
                    m
                    for (_t, _q, m) in fake_qr.sent
                    if isinstance(m, dict) and m.get("command") == "state.unsubscribe_all"
                ]
                if unsub_msgs:
                    break
                time.sleep(0.05)

            assert len(unsub_msgs) == 1, (
                f"ожидался ровно 1 state.unsubscribe_all, получено {len(unsub_msgs)}: "
                f"{[m for (_t, _q, m) in fake_qr.sent]!r}"
            )
            assert unsub_msgs[0].get("data", {}).get("subscriber") == "proc_probe_b"
        finally:
            pass  # proc.shutdown() уже вызван выше — сценарий теста, не teardown
