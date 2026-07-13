"""Контракт-тесты chain-движка PipelineExecutor (C6d инкремент 1).

Два инварианта НОВОГО механизма (исполнение поверх ChainRunnable):

1. Риск №2 дизайна §6 — плагины исполняются СТРОГО через PluginRunner, а не
   ``plugin.process()`` напрямую: pre/post-хуки наблюдения (io-debug) и
   FW_PORT_VALIDATE обязаны срабатывать на chain-исполняемом плагине.

2. Бюджет границ процесса (перф-ревью 2026-07-12 п.1) — многозвенная
   processing-цепочка (≥3 плагинов) исполняется ЦЕЛИКОМ внутри ОДНОГО вызова
   ``ChainRunnable.execute()`` без IPC между звеньями (0 вызовов send_fn до конца
   цепочки). Evidence «CV-цепочка внутри одного воркера»; runtime-счётчик хопов
   на кадр — отдельная задача Ф7 G.6, не здесь.
"""

from __future__ import annotations

from multiprocess_framework.modules.chain_module.core import chain as chain_mod
from multiprocess_framework.modules.process_module.generic.pipeline_executor import (
    PipelineExecutor,
)
from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.base import (
    ProcessModulePlugin,
)


class TagPlugin(ProcessModulePlugin):
    """Помечает каждый item своим именем — прослеживаемость прохода цепочки."""

    def __init__(self, name: str, observer=None):
        super().__init__()
        self.name = name
        self.category = "processing"
        self._observer = observer

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        if self._observer is not None:
            self._observer(self.name)
        return [{**it, self.name: True} for it in items]


# --------------------------------------------------------------------------- #
#  Контракт 1: io-debug hook срабатывает на chain-исполняемом плагине          #
# --------------------------------------------------------------------------- #


def test_iodebug_hooks_fire_on_chain_executed_plugins():
    """pre/post-хуки PluginRunner срабатывают на КАЖДОМ плагине chain-цепочки.

    Доказывает, что _execute_chain делегирует через PluginRunner.call_process,
    а не вызывает plugin.process() напрямую (иначе хуки молча бы отключились —
    риск №2 дизайна §6).
    """
    pre_calls: list[str] = []
    post_calls: list[str] = []

    runner = PluginRunner()
    runner.add_pre_hook(lambda plugin, method, inputs: pre_calls.append(plugin.name))
    runner.add_post_hook(lambda plugin, method, inputs, outputs: post_calls.append(plugin.name))

    executor = PipelineExecutor(
        plugins=[TagPlugin("p1"), TagPlugin("p2")],
        chain_targets=["out"],
        shm_middleware=None,
        send_fn=lambda t, m: None,
        plugin_runner=runner,
    )
    executor._execute_chain([{"v": 1}])

    # Оба плагина прошли через раннер: pre и post по разу на каждого, в порядке цепочки.
    assert pre_calls == ["p1", "p2"]
    assert post_calls == ["p1", "p2"]


def test_iodebug_hook_sees_chain_output():
    """post-хук видит ВЫХОД плагина (доказывает, что раннер вернул результат в цепочку)."""
    seen: list[tuple[str, bool]] = []

    runner = PluginRunner()
    runner.add_post_hook(
        lambda plugin, method, inputs, outputs: seen.append((plugin.name, bool(outputs) and plugin.name in outputs[0]))
    )
    executor = PipelineExecutor(
        plugins=[TagPlugin("tagger")],
        chain_targets=["out"],
        shm_middleware=None,
        send_fn=lambda t, m: None,
        plugin_runner=runner,
    )
    executor._execute_chain([{"v": 1}])
    assert seen == [("tagger", True)]


# --------------------------------------------------------------------------- #
#  Контракт 2: многозвенная цепочка — 1 execute(), 0 IPC между звеньями        #
# --------------------------------------------------------------------------- #


def test_multilink_chain_runs_in_single_execute_without_ipc(monkeypatch):
    """≥3 плагинов исполняются в ОДНОМ ChainRunnable.execute(), 0 send_fn до конца."""
    execute_calls = {"n": 0}
    orig_execute = chain_mod.ChainRunnable.execute

    def counting_execute(self, payload, metadata=None):
        execute_calls["n"] += 1
        return orig_execute(self, payload, metadata)

    monkeypatch.setattr(chain_mod.ChainRunnable, "execute", counting_execute)

    sent: list = []
    send_count_at_plugin: list[int] = []
    invoked: list[str] = []

    def observe(name: str):
        invoked.append(name)
        # Число IPC-отправок, наблюдаемое ВНУТРИ каждого звена цепочки.
        send_count_at_plugin.append(len(sent))

    executor = PipelineExecutor(
        plugins=[TagPlugin("a", observe), TagPlugin("b", observe), TagPlugin("c", observe)],
        chain_targets=["out"],
        shm_middleware=None,
        send_fn=lambda t, m: sent.append((t, m)),
    )

    result = executor._execute_chain([{"v": 1}])

    # Вся 3-звенная цепочка прошла в ОДНОМ execute().
    assert execute_calls["n"] == 1
    # Все 3 плагина вызваны по разу, в порядке цепочки.
    assert invoked == ["a", "b", "c"]
    # 0 IPC-хопов МЕЖДУ звеньями: ни одно звено не видело отправок.
    assert send_count_at_plugin == [0, 0, 0]
    # Данные протекли через все 3 звена (каждое пометило item).
    assert result[0]["a"] and result[0]["b"] and result[0]["c"]
    # До _send_results IPC не было вовсе.
    assert sent == []


def test_send_results_is_the_single_egress_after_chain():
    """IPC происходит ТОЛЬКО в _send_results (после цепочки), fan-out по targets."""
    sent: list = []
    executor = PipelineExecutor(
        plugins=[TagPlugin("a"), TagPlugin("b"), TagPlugin("c")],
        chain_targets=["t1", "t2"],
        shm_middleware=None,
        send_fn=lambda t, m: sent.append((t, m)),
    )
    items = executor._execute_chain([{"v": 1}])
    assert sent == []  # цепочка не шлёт
    executor._send_results(items)
    # Один выход после цепочки → fan-out в оба target'а.
    assert [t for t, _ in sent] == ["t1", "t2"]
