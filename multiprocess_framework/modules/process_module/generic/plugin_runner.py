"""PluginRunner — единый шов вызова plugin.process()/produce() + pre/post-хуки.

Все вызовы плагинов в data-плоскости (PipelineExecutor.chain, SourceProducer.loop)
идут ЧЕРЕЗ этот раннер. Это даёт ОДНУ точку наблюдения за in/out плагина —
io-debug (Этап 5: summary входа/выхода в карточку ноды), метрики, диагностика —
вместо дублирования логики в двух воркерах.

Что раннер НЕ делает (намеренно):
- НЕ ловит исключения plugin.process/produce — error policy остаётся у вызывающего
  (circuit breaker в PipelineExecutor; обработка NotImplementedError в SourceProducer).
  Раннер прозрачен: исключение плагина пробрасывается как раньше.
- НЕ дублирует frame_trace — process/produce уже обёрнуты на бутe плагина
  (PluginOrchestrator.boot → frame_trace.install_tracing). Раннер добавляет только
  hook-семантику.

Хуки опциональны. Пустой набор → overhead = два прохода по пустым спискам (наносекунды,
требование Этапа 4: < 0.1 мс на hot path). Хук, бросивший исключение, изолируется
(try/except + log) — кривой наблюдатель не должен ронять data-плоскость.

Семантика хуков:
    pre-hook(plugin, method, inputs)           — до вызова (inputs до мутации плагином)
    post-hook(plugin, method, inputs, outputs) — после успешного вызова

``method`` — "process" | "produce". Для produce ``inputs`` = None (источник без входа).
io-debug снимает summary входа в pre-hook (плагины часто мутируют item in-place),
выхода — в post-hook.

FW_PORT_VALIDATE (Ф4.3): dev-only sanity-check items на границе плагина против его
Port-деклараций (``plugin.inputs``/``plugin.outputs``, см. ``..plugins.port``).
OFF по умолчанию (``os.environ`` не читается на hot path, если явно не запрошено) —
прод-путь бит-в-бит прежний. Включается env-флагом или явным ``validate_ports=True``
(DI для тестов). Несоответствие -> ``PortValidationError`` (та же error-policy, что и
исключение самого плагина — пробрасывается вызывающему, не глотается раннером).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ...config_module.feature_flags import resolve
from ..plugins.port import validate_items_against_ports

if TYPE_CHECKING:
    from ..plugins.base import ProcessModulePlugin

# pre-hook:  (plugin, method, inputs) -> None
PreHook = Callable[["ProcessModulePlugin", str, "list[dict] | None"], None]
# post-hook: (plugin, method, inputs, outputs) -> None
PostHook = Callable[["ProcessModulePlugin", str, "list[dict] | None", "list[dict]"], None]

# Ф7 G.6 ревью 2026-07-13, F2 (HIGH, CONFIRMED, решение владельца — «универсальный
# конверт кадра»): системные поля, которые ДОЛЖНЫ пережить plugin.process(), даже
# если плагин строит СВЕЖИЙ выходной dict вместо мутации входного (stitcher,
# renderer_compositor, line_filter, center_crop и т.п.). Плагин может их
# переопределить (setdefault-семантика — плагин выигрывает), но не может потерять.
_CARRIED_SYSTEM_FIELDS = ("trace_id", "capture_ts", "frame_hops")


def _carry_system_fields(inputs: "list[dict] | None", outputs: "list[dict]") -> None:
    """Перенести системные поля кадра из входа в каждый выход, если плагин их не поставил.

    Единое место в движке (не по одному фиксу в каждом плагине — решение
    владельца, ADR «универсальный конверт кадра», 2026-07-13): раньше плагины,
    пересобирающие item как свежий dict, молча теряли ``trace_id``/``capture_ts``/
    ``frame_hops`` — по trace_id перестаёт восстанавливаться путь кадра ровно на
    той ноде, что решила собрать новый dict.

    Соответствие вход → выход:
      - 1:1 (``len(inputs) == len(outputs)``, самый частый случай — трансформация
        батча независимых items) — донор для ``outputs[i]`` это ``inputs[i]``
        (позиционное соответствие, каждый item несёт СВОИ поля, не соседские);
      - иначе (fan-in N:1, fan-out 1:N, пустой выход) — донор для ВСЕХ выходов —
        ``inputs[0]`` («первичная»/«победившая» ветка; тот же fallback, что уже
        использует ``stitcher`` для ``capture_ts``, когда trace-трассировка
        выключена — см. ``StitcherPlugin.process``: ``next(..., items[0])``).

    ``call_produce`` (нет входа) сюда не попадает — trace_id уже назначается в
    ``SourceProducer`` явно (``frame_trace.ensure_trace_id``), донора для produce нет.
    """
    if not inputs or not outputs:
        return
    same_length = len(inputs) == len(outputs)
    primary = inputs[0] if isinstance(inputs[0], dict) else None
    for idx, output in enumerate(outputs):
        if not isinstance(output, dict):
            continue
        donor = inputs[idx] if same_length and isinstance(inputs[idx], dict) else primary
        if donor is None or donor is output:
            continue  # плагин вернул тот же объект (мутация на месте) — поля уже там
        for key in _CARRIED_SYSTEM_FIELDS:
            if key not in output and key in donor:
                output[key] = donor[key]


class PluginRunner:
    """Единый вызыватель плагинов с pre/post-хуками наблюдения.

    Args:
        log_error: callback для изоляции ошибок хуков (хук не роняет data-плоскость).
        validate_ports: явно включить/выключить FW_PORT_VALIDATE (см. модульный
            docstring). None (default) — читать env ``FW_PORT_VALIDATE``
            (значения "1"/"true"/"True" включают). Явное значение перекрывает env
            (используется тестами/DI).
    """

    def __init__(
        self,
        log_error: Callable[[str], None] | None = None,
        validate_ports: bool | None = None,
    ) -> None:
        self._pre_hooks: list[PreHook] = []
        self._post_hooks: list[PostHook] = []
        self._log_error = log_error or (lambda msg: None)
        self._validate_ports = resolve("FW_PORT_VALIDATE", validate_ports)

    # ------------------------------------------------------------------ #
    #  Регистрация наблюдателей (Этап 5: io-debug publisher)              #
    # ------------------------------------------------------------------ #

    def add_pre_hook(self, hook: PreHook) -> None:
        """Зарегистрировать pre-хук (вызывается до plugin.process/produce)."""
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: PostHook) -> None:
        """Зарегистрировать post-хук (вызывается после успешного вызова)."""
        self._post_hooks.append(hook)

    # ------------------------------------------------------------------ #
    #  Вызовы плагина (единственная точка в data-плоскости)              #
    # ------------------------------------------------------------------ #

    def call_process(self, plugin: "ProcessModulePlugin", items: list[dict]) -> list[dict]:
        """Вызвать plugin.process(items) с хуками. Исключение плагина пробрасывается.

        Bypass: если plugin.enabled == False — process() НЕ вызывается, кадр идёт
        насквозь (outputs = входные items). Хуки наблюдения всё равно срабатывают
        (io-debug видит ноду как pass-through). Нужно, чтобы выключить «тяжёлую»/
        зависающую ноду (напр. circle_detector) и спокойно тюнить остальную цепочку.

        F2 (ревью 2026-07-13): после получения outputs системные поля кадра
        (trace_id/capture_ts/frame_hops) переносятся из items в каждый output, если
        плагин их не поставил сам — см. модульную ``_carry_system_fields``. Плагины
        НЕ трогаем по одному — перенос в этом единственном месте покрывает всех.
        """
        self._run_pre(plugin, "process", items)
        if getattr(plugin, "enabled", True):
            if self._validate_ports:
                validate_items_against_ports(plugin.name, "input", getattr(plugin, "inputs", []), items)
            outputs = plugin.process(items)
            if self._validate_ports:
                validate_items_against_ports(plugin.name, "output", getattr(plugin, "outputs", []), outputs)
        else:
            outputs = items  # bypass: кадр без обработки (свои Port-декларации не проверяем)
        _carry_system_fields(items, outputs)
        self._run_post(plugin, "process", items, outputs)
        return outputs

    def call_produce(self, plugin: "ProcessModulePlugin") -> list[dict]:
        """Вызвать plugin.produce() с хуками. Исключение плагина пробрасывается."""
        self._run_pre(plugin, "produce", None)
        outputs = plugin.produce()
        if self._validate_ports:
            validate_items_against_ports(plugin.name, "output", getattr(plugin, "outputs", []), outputs)
        self._run_post(plugin, "produce", None, outputs)
        return outputs

    # ------------------------------------------------------------------ #
    #  Внутреннее: изоляция хуков                                         #
    # ------------------------------------------------------------------ #

    def _run_pre(self, plugin: "ProcessModulePlugin", method: str, inputs: list[dict] | None) -> None:
        for hook in self._pre_hooks:
            try:
                hook(plugin, method, inputs)
            except Exception as e:  # noqa: BLE001 — наблюдатель не должен ронять pipeline
                self._log_error(f"PluginRunner pre-hook error ({plugin.name}.{method}): {e}")

    def _run_post(
        self,
        plugin: "ProcessModulePlugin",
        method: str,
        inputs: list[dict] | None,
        outputs: list[dict],
    ) -> None:
        for hook in self._post_hooks:
            try:
                hook(plugin, method, inputs, outputs)
            except Exception as e:  # noqa: BLE001 — наблюдатель не должен ронять pipeline
                self._log_error(f"PluginRunner post-hook error ({plugin.name}.{method}): {e}")
