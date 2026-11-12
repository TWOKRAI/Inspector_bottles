"""Task 1.9 (system-run-state): PAUSED режет поток — PluginRunner.call_process обходит плагин.

Контракт (DESIGN tasks/1.9.md, вердикт cto К6):
  1. ``call_process`` при ``plugin.state == PluginState.PAUSED`` — bypass как при ``enabled == False``:
     ``process()`` не вызывается, ``outputs is items``, хуки наблюдения идут, порты не проверяются;
  2. ``call_produce`` не меняется (источник гейтится run_event в SourceProducer, Task 1.1);
  3. тег ``inspection_status`` на bypass по PAUSED НЕ ставится (решение лида 2026-11-13,
     как у bypass по ``enabled == False``).

Тесты написаны слепо, до реализации. Состояние плагина ставится присваиванием ``plugin.state`` — именно его
читает раннер; хуки pause/resume и наблюдатель — Task 1.2, вне этого файла.

Парные guard-тесты (зелёные и до реализации, ловят порчу соседнего поведения):
``test_running_plugin_process_called``, ``test_paused_source_call_produce_unchanged``.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.plugins.base import PluginState, ProcessModulePlugin
from multiprocess_framework.modules.process_module.plugins.port import Port


class _FakePlugin:
    """Плагин-двойник с состоянием: считает вызовы process()/produce(), отдаёт НОВЫЙ список (не входной)."""

    name = "fake"

    def __init__(self, state: PluginState) -> None:
        self.state = state
        self.enabled = True
        self.process_calls = 0
        self.produce_calls = 0

    def process(self, items):
        self.process_calls += 1
        return [{"processed": True}]

    def produce(self):
        self.produce_calls += 1
        return [{"frame": 1}]


class _CountingPlugin(ProcessModulePlugin):
    """Настоящий ProcessModulePlugin (для PipelineExecutor): считает process(), мутацию входа не делает."""

    name = "counting"
    category = "processing"

    def __init__(self) -> None:
        super().__init__()
        self.process_calls = 0

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        self.process_calls += 1
        return [{**it, "processed": True} for it in items]


class _RaisingPlugin(ProcessModulePlugin):
    """process() бросает: если раннер его вызовет, breaker засчитает фейл."""

    name = "raising"
    category = "processing"

    def __init__(self) -> None:
        super().__init__()
        self.process_calls = 0

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def process(self, items):
        self.process_calls += 1
        raise ValueError("must not be called while PAUSED")


def _executor(plugins: list[ProcessModulePlugin], max_fails: int = 5) -> PipelineExecutor:
    return PipelineExecutor(
        plugins=plugins,
        chain_targets=["out"],
        shm_middleware=None,
        send_fn=lambda target, msg: None,
        max_consecutive_fails=max_fails,
    )


# ---------------------------------------------------------------------------
#  Ядро: PAUSED = bypass
# ---------------------------------------------------------------------------


def test_paused_plugin_process_not_called_outputs_pass_through():
    runner = PluginRunner()
    plugin = _FakePlugin(PluginState.PAUSED)
    items = [{"frame": 7}]

    out = runner.call_process(plugin, items)

    assert plugin.process_calls == 0  # process() не вызывался
    assert out is items  # тот же список: кадр без обработки
    assert out[0]["frame"] == 7  # кадр дошёл
    assert "processed" not in out[0]  # без обработки


def test_running_plugin_process_called():
    """Guard (зелёный и до реализации): RUNNING обрабатывает как раньше, пауза не залипает на всех."""
    runner = PluginRunner()
    plugin = _FakePlugin(PluginState.RUNNING)
    items = [{"frame": 7}]

    out = runner.call_process(plugin, items)

    assert plugin.process_calls == 1
    assert out == [{"processed": True}]  # _FakePlugin.process отдаёт именно это
    assert out is not items


def test_paused_source_call_produce_unchanged():
    """Guard (зелёный и до реализации): call_produce не меняется — источник в PAUSED по-прежнему зовёт produce()."""
    runner = PluginRunner()
    plugin = _FakePlugin(PluginState.PAUSED)

    out = runner.call_produce(plugin)

    assert plugin.produce_calls == 1
    assert out == [{"frame": 1}]


def test_resumed_plugin_processes_again():
    """Bypass следует за состоянием, а не залипает: PAUSED -> 0 вызовов, после возврата в RUNNING -> 1."""
    runner = PluginRunner()
    plugin = _FakePlugin(PluginState.PAUSED)

    runner.call_process(plugin, [{"frame": 1}])
    assert plugin.process_calls == 0

    plugin.state = PluginState.RUNNING
    out = runner.call_process(plugin, [{"frame": 2}])

    assert plugin.process_calls == 1
    assert out == [{"processed": True}]


# ---------------------------------------------------------------------------
#  Бок о бок с enabled == False: хуки идут, порты не проверяются, EMA не копится
# ---------------------------------------------------------------------------


def test_paused_plugin_still_runs_observation_hooks():
    """Bypass не слепит наблюдателей (как у enabled=False): pre и post срабатывают, outputs is inputs."""
    runner = PluginRunner()
    seen: list[tuple] = []
    runner.add_pre_hook(lambda p, m, inp: seen.append(("pre", m, inp)))
    runner.add_post_hook(lambda p, m, inp, out: seen.append(("post", m, inp, out)))
    plugin = _FakePlugin(PluginState.PAUSED)
    items = [{"frame": 1}]

    runner.call_process(plugin, items)

    assert len(seen) == 2
    assert seen[0][:2] == ("pre", "process")
    assert seen[0][2] is items  # pre-хук видит входной список
    assert seen[1][:2] == ("post", "process")
    assert seen[1][2] is items
    assert seen[1][3] is items  # выход = вход (проходной кадр), а не результат process()


def test_paused_plugin_skips_port_validation():
    """validate_ports=True: у плагина в PAUSED свои порты не проверяются (как у enabled=False)."""
    runner = PluginRunner(validate_ports=True)
    plugin = _FakePlugin(PluginState.PAUSED)
    plugin.inputs = [Port(name="frame", dtype="image/bgr")]  # в проходном item поля frame нет
    plugin.outputs = [Port(name="mask", dtype="image/gray")]  # и mask нет
    items = [{"other": 1}]

    out = runner.call_process(plugin, items)  # не должен бросить PortValidationError

    assert out is items
    assert plugin.process_calls == 0


def test_paused_plugin_not_counted_in_plugin_ms():
    """plugin_ms() считает только сам вызов плагина; bypass (в т.ч. по PAUSED) в цифру не попадает."""
    runner = PluginRunner()
    plugin = _FakePlugin(PluginState.PAUSED)

    runner.call_process(plugin, [{"frame": 1}])

    assert runner.plugin_ms() == {}


# ---------------------------------------------------------------------------
#  Путь через PipelineExecutor (TRAPS: раннер — единственный шов, но тест обязан пройти настоящий исполнитель)
# ---------------------------------------------------------------------------


def test_paused_plugin_in_executor_chain_skipped_and_breaker_untouched():
    """Через настоящий PipelineExecutor: process() PAUSED-плагина не зовётся, фейлом для breaker это не считается.

    max_fails=2 и process(), бросающий исключение: если раннер его вызовет, после двух батчей плагин
    уйдёт в bypass предохранителя. Пауза — не поломка: is_bypassed остаётся False.
    """
    plugin = _RaisingPlugin()
    plugin.state = PluginState.PAUSED
    executor = _executor([plugin], max_fails=2)

    for n in range(4):
        executor._execute_chain([{"frame": n}])

    assert plugin.process_calls == 0
    assert executor.is_bypassed("raising") is False
