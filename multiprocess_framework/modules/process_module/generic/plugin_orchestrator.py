"""PluginOrchestrator — управление lifecycle плагинов через IProcessServices.

Извлечён из GenericProcess (Task 3, refactor/t1.1-plugin-composition).
Не зависит от ProcessModule напрямую — работает через Protocol.
Тестируется с MockProcessServices.

Lifecycle:
    load_and_configure_managers(plugin_defs) — загрузка + early init
    boot() — IDLE -> READY -> RUNNING + registers
    shutdown() — * -> STOPPED (обратный порядок)

Task 1.2 (system-run-state): оркестратор ещё и считает снимок готовности процесса
(:meth:`PluginOrchestrator.readiness_snapshot`) и сверяет цель ``run_event`` с
состоянием плагинов (:meth:`PluginOrchestrator.reconcile_run_event`); потоки для
обоих заводит ``ProcessModule`` (воркеры ``WorkerType.SYSTEM``).
"""

from __future__ import annotations

import importlib
import threading
import time
from typing import Any

from . import frame_trace
from ..plugins.base import PluginContext, PluginState, ProcessModulePlugin
from ..plugins.interfaces import IProcessServices
from ..plugins.manifest import PLUGIN_API_VERSION, api_version_major_mismatch, check_requires

#: Словарь ``severity`` в элементе ``readiness()`` плагина (контракт хука).
_SEVERITIES: tuple[str, ...] = ("failure", "check_function", "out_of_spec", "maintenance")
#: Эти два уровня блокируют готовность процесса (``out_of_spec``/``maintenance`` — нет).
_BLOCKING_SEVERITIES: tuple[str, ...] = ("failure", "check_function")
#: Потолок текста причины, символов (длиннее — обрезается).
_REASON_MAX_LEN = 200
#: Потолок числа причин на процесс, включая маркер «причин больше 32».
_REASONS_MAX = 32
#: Не чаще раза в это время сверка повторяет упавший ``pause()/resume()`` одного плагина, сек.
_HOOK_RETRY_SEC = 1.0
#: Сколько ``shutdown()`` ждёт замок сверки (медленный хук наблюдателя), сек.
_SHUTDOWN_LOCK_SEC = 2.0


class PluginOrchestrator:
    """Управляет lifecycle плагинов через IProcessServices.

    Не зависит от ProcessModule — работает через Protocol.
    Тестируется с MockProcessServices.

    Lifecycle:
        load_and_configure_managers(plugin_defs) — загрузка + early init
        boot() — IDLE -> READY -> RUNNING + registers
        shutdown() — * -> STOPPED (обратный порядок)
    """

    def __init__(self, services: IProcessServices, io: Any | None = None) -> None:
        self._services = services
        self._io = io
        self._plugins: list[ProcessModulePlugin] = []
        self._contexts: list[PluginContext] = []
        self._early_plugins: list[tuple[ProcessModulePlugin, PluginContext]] = []
        self._registers_manager: Any | None = None
        # Task 1.2 (Д6): флаг «процесс останавливается». Ставится request_stop() ПЕРВЫМ
        # действием и БЕЗ замка (контракт C-60: хук стопа не ждёт); сверка смотрит его
        # перед каждым хуком паузы/возобновления.
        self._stopping = False
        # Замок сверки: держит поток ``run_watch`` на время обхода плагинов; shutdown()
        # ждёт его не дольше ``_SHUTDOWN_LOCK_SEC``. Снимок готовности замок НЕ берёт
        # (зависший ``pause()`` одного плагина не должен замораживать снимок).
        self._reconcile_lock = threading.Lock()
        # Упавшие pause()/resume(): ``id(plugin) -> {"pause": bool, "type": str, "retry_at": float}``.
        # Пишет сверка, читает снимок готовности (другой поток) — доступ под коротким замком.
        self._hook_failures: dict[int, dict[str, Any]] = {}
        self._hook_failures_lock = threading.Lock()
        # Последний залогированный отказ readiness() плагина (id -> ключ): лог один раз на серию.
        self._readiness_logged: dict[int, str] = {}

    # --- Публичный API ---

    def load_and_configure_managers(self, plugin_defs: list[dict]) -> None:
        """Загрузить плагины, вызвать configure_managers().

        Выполняется ДО boot() (и до configure/start).
        Позволяет плагинам создать framework-менеджеры (SQLManager и т.д.),
        которые должны существовать до основного plugin lifecycle.
        """
        base_ctx = PluginContext(
            services=self._services,
            config={},
            io=self._io,
        )

        # StateProxy (заводит GenericProcess._init_custom_managers, ADR-PM-049)
        state_proxy = getattr(self._services, "_state_proxy", None)
        if state_proxy is not None:
            base_ctx.state_proxy = state_proxy

        self._early_plugins = []
        for pdef in plugin_defs:
            plugin_class_path = pdef.get("plugin_class", "")
            plugin_name = pdef.get("plugin_name", "unknown")
            # Short-name resolution: если plugin_class пуст или это короткое имя
            # (без точки) — резолвим через PluginRegistry по plugin_name.
            resolved_class_path = self._resolve_plugin_class(
                plugin_class_path,
                plugin_name,
            )
            if not resolved_class_path:
                continue
            try:
                plugin = self._load_plugin(resolved_class_path, plugin_name)
                plugin_config = self._extract_plugin_config(pdef)
                ctx = base_ctx.with_config(plugin_config, plugin_name=plugin_name)
                plugin.configure_managers(ctx)
                self._early_plugins.append((plugin, ctx))
            except Exception as e:
                self._services.log_error(
                    f"PluginOrchestrator[{self._services.name}]: configure_managers '{plugin_name}': {e}"
                )

    @staticmethod
    def _extract_plugin_config(pdef: dict) -> dict:
        """Извлечь плоский конфиг плагина из его определения (pdef).

        pdef встречается в двух форматах:
          - плоский (старые рецепты): параметры на верхнем уровне pdef
            (``{"plugin_name": ..., "camera_id": 0, "auto_start": true}``);
          - вложенный (GUI-нормализованный): параметры под ключом ``config``
            (``{"plugin_name": ..., "category": ..., "config": {"camera_id": 0, ...}}``).

        Нормализуем к плоскому ЗДЕСЬ (единая граница) — чтобы ``ctx.config`` всегда был
        плоским для ВСЕХ плагинов, и плагинам не нужно знать про два формата.

        Мета-поля PluginConfig (``plugin_class``/``plugin_name``/``category``) — НЕ параметры
        плагина, отбрасываем (иначе ``category`` и т.п. утекают в ``ctx.config`` как мусор).
        """
        meta_keys = ("plugin_class", "plugin_name", "category")
        cfg = {k: v for k, v in pdef.items() if k not in meta_keys}
        nested = cfg.pop("config", None)
        if isinstance(nested, dict):
            cfg.update(nested)  # вложенный config разворачиваем поверх (он — источник истины)
        return cfg

    def boot(self) -> None:
        """IDLE -> READY -> RUNNING + registers bootstrap.

        Плагины уже загружены в load_and_configure_managers().
        Здесь только configure -> start lifecycle + registers.
        """
        if not self._early_plugins:
            self._services.log_info(f"PluginOrchestrator[{self._services.name}]: нет плагинов")
            return

        self._plugins = []
        self._contexts = []

        # Фаза 0: Registers bootstrap (до configure, чтобы ctx.registers был доступен)
        registers_manager = self._init_registers(self._early_plugins)

        # Фаза 1: IDLE -> READY (configure + авторегистрация команд)
        for plugin, ctx in self._early_plugins:
            try:
                # Обновить ctx с registers
                if registers_manager is not None:
                    ctx.registers = registers_manager
                # frame-trace: имя процесса-узла для process-спанов плагина.
                plugin._trace_node = self._services.name
                # C6 рычаг 2: обёртка process/produce в traced (idempotent) — раньше
                # стояла в ProcessModulePlugin.__init_subclass__ (домен в фундаменте),
                # теперь на бутe инстанса, оркестратор — легитимный дом инструментовки.
                frame_trace.install_tracing(type(plugin))
                # health (Ф2 Task 2.1): имя плагина — дефолтный context для ctx.health.
                ctx._plugin_name = plugin.name

                # Манифест (Ф4 Task 4.4): API_VERSION mismatch по major — громкий
                # WARNING, boot ПРОДОЛЖАЕТСЯ (план: «boot mismatch → WARNING», не
                # отказ — несовместимость контракта не гарантирована, только вероятна).
                if api_version_major_mismatch(plugin.API_VERSION):
                    self._services.log_warning(
                        f"PluginOrchestrator[{self._services.name}]: '{plugin.name}' "
                        f"API_VERSION={plugin.API_VERSION!r} расходится по major с текущим "
                        f"контрактом плагин-фреймворк {PLUGIN_API_VERSION!r}"
                    )

                # REQUIRES (Ф4 Task 4.4): недостающий manager/service/shm — fail-fast ДО
                # configure(), той же строгостью, что и провал самого configure() (skip
                # + громкий лог, процесс жив) — вместо позднего немого AttributeError
                # из getattr(ctx, ..., None) внутри плагина.
                missing = check_requires(ctx, plugin.REQUIRES)
                if missing:
                    self._services.log_error(
                        f"PluginOrchestrator[{self._services.name}]: '{plugin.name}' REQUIRES не "
                        f"удовлетворены, плагин пропущен: {'; '.join(missing)}"
                    )
                    continue

                # H-2: append ДО _do_configure — если configure() бросит, плагин уже
                # успел захватить ресурсы (ONNX/CUDA-сессия, камера), и без этого
                # shutdown() его не увидит (итерирует только self._plugins/self._contexts,
                # см. shutdown() ниже). _do_shutdown коротко замыкается ТОЛЬКО на состоянии
                # PluginState.STOPPED (plugins/base.py:_do_shutdown) — для плагина,
                # оставшегося в IDLE из-за брошенного configure(), это НЕ no-op: shutdown()
                # реально вызовется и получит шанс освободить захваченное до броска.
                self._plugins.append(plugin)
                self._contexts.append(ctx)
                plugin._do_configure(ctx)
                self._services.log_info(
                    f"PluginOrchestrator[{self._services.name}]: '{plugin.name}' "
                    f"[{plugin.category}] {plugin.state.value}"
                )
            except Exception as e:
                # НЕ убираем плагин из self._plugins/self._contexts — иначе shutdown()
                # снова его не увидит (см. комментарий выше про H-2).
                self._services.log_error(f"PluginOrchestrator[{self._services.name}]: configure '{plugin.name}': {e}")

        # Фаза 2: READY -> RUNNING (start)
        #
        # H-2 (дополнение Ф0 Task 0.2, правка 4): плагин, чей configure() бросил,
        # ОСТАЁТСЯ в self._plugins/self._contexts — ровно ради shutdown, как
        # сказано выше; отсюда он никуда не убирается. Но стартовать ему нечем:
        # он в IDLE, ресурсы не разложены. Раньше _do_start звался всем подряд,
        # и защита срабатывала на этаж ниже (plugins/base.py:_do_start требует
        # READY) — ценой лживой строки в журнале «start() в состоянии idle,
        # ожидается READY» на каждый упавший плагин, то есть отказ configure()
        # выглядел вторым, независимым отказом старта. Решение «этот плагин не
        # поднимается» принимается ЗДЕСЬ, где известна причина.
        for plugin, ctx in zip(self._plugins, self._contexts):
            if plugin.state != PluginState.READY:
                continue
            try:
                plugin._do_start(ctx)
                self._services.log_info(
                    f"PluginOrchestrator[{self._services.name}]: '{plugin.name}' {plugin.state.value}"
                )
            except Exception as e:
                self._services.log_error(f"PluginOrchestrator[{self._services.name}]: start '{plugin.name}': {e}")
                continue
            self._boot_pause(plugin, ctx)

        self._services.log_info(f"PluginOrchestrator[{self._services.name}]: {len(self._plugins)} плагин(ов)")

        # Фаза 3.5: control-команды (bypass ноды) — независимо от наличия регистров.
        self._register_control_commands()

        # Фаза 4: Registers boot — отправить schemas в PM + handler
        if registers_manager is not None:
            self._boot_registers(registers_manager)

    def shutdown(self) -> None:
        """* -> STOPPED для всех плагинов (в обратном порядке).

        Task 1.2 (Д6): сначала замок сверки ``run_watch`` с таймаутом ``_SHUTDOWN_LOCK_SEC``
        (медленный ``pause()/resume()`` на потоке наблюдателя не должен пересечься с
        ``shutdown()`` плагина); по таймауту — ``log_error`` и идём дальше без замка (+≤ 2 с
        к закрытию). Присваивание ``PAUSED`` поверх ``STOPPED`` закрыто в ``base.py``.
        """
        self._stopping = True
        locked = self._reconcile_lock.acquire(timeout=_SHUTDOWN_LOCK_SEC)
        if not locked:
            self._services.log_error(
                f"PluginOrchestrator[{self._services.name}]: замок сверки run_event не освободился "
                f"за {_SHUTDOWN_LOCK_SEC} с (хук pause/resume завис) — shutdown плагинов идёт без него"
            )
        try:
            for plugin, ctx in reversed(list(zip(self._plugins, self._contexts))):
                try:
                    plugin._do_shutdown(ctx)
                    self._services.log_info(
                        f"PluginOrchestrator[{self._services.name}]: '{plugin.name}' {plugin.state.value}"
                    )
                except Exception as e:
                    self._services.log_error(
                        f"PluginOrchestrator[{self._services.name}]: shutdown '{plugin.name}': {e}"
                    )
        finally:
            if locked:
                self._reconcile_lock.release()

    def request_stop(self) -> None:
        """Весть о стопе процесса всем плагинам (C-60), в обратном порядке загрузки.

        Зовётся записью ``plugins-stop`` сегмента ``work`` первой в фазе 2 —
        до ожидания воркеров и исполнителей и до :meth:`shutdown`. Исключение
        одного плагина логируется и не отменяет хук соседа; наружу не выходит.
        Фильтр состояний — в ``ProcessModulePlugin._do_request_stop``.

        Первым действием ставит ``_stopping`` БЕЗ замка (Task 1.2, Д6): после этого
        сверка ``run_event`` не зовёт новых ``pause()/resume()``.
        """
        self._stopping = True
        for plugin, ctx in reversed(list(zip(self._plugins, self._contexts))):
            try:
                plugin._do_request_stop(ctx)
            except Exception as e:
                self._services.log_error(
                    f"PluginOrchestrator[{self._services.name}]: request_stop '{plugin.name}': {e}"
                )

    def config_of(self, plugin: ProcessModulePlugin) -> dict:
        """Копия плоского ``ctx.config`` загруженного плагина (Task 1.1 плана system-run-state).

        Поиск по тождеству (``p is plugin``) среди плагинов после ``boot()``. Плагина нет в
        списке → ``{}``. Живой словарь контекста наружу не отдаётся: каждый вызов — свежая копия.
        """
        for p, ctx in zip(self._plugins, self._contexts):
            if p is plugin:
                return dict(ctx.config)
        return {}

    # --- Готовность и событие работы (Task 1.2 плана system-run-state) ---

    def readiness_snapshot(self, announced: bool | None = None) -> dict:
        """Снимок готовности процесса: ``{"ready", "reasons", "paused", "at"}``.

        Считает отдельный поток-снимок процесса (≤ 2 Гц); heartbeat только читает
        готовый результат. ``announced`` — защёлка «процесс объявил готовность»
        (держит вызывающий); ``None`` → читаем статус процесса сами:
        ``_current_process_status in ("running", "paused")``.

        * ``reasons`` — по плагину: причины его ``readiness()`` (под собственным ``try``),
          «плагин не поднят (<состояние>)» для плагина вне ``RUNNING/PAUSED``
          (``readiness()`` у такого плагина не зовётся), причина упавшего
          ``pause()/resume()``. Элемент — ровно ``node, severity, reason, source``.
        * ``ready`` — процесс объявил готовность и нет ``failure``/``check_function``;
          считается ДО обрезки списка причин.
        * ``paused`` — цель «пауза» (``run_event`` снято) и ни один плагин, к которому
          применимо :meth:`_should_pause`, не в ``RUNNING``. До Task 1.9 это состояние
          ярлыков: воркеры плагинов идут.
        * ``at`` — ``time.time()`` расчёта: PM судит «молчание» по нему, а не по heartbeat.

        Замок сверки не берёт: зависший хук одного плагина снимок не замораживает.
        """
        if announced is None:
            announced = getattr(self._services, "_current_process_status", None) in ("running", "paused")
        target_pause = self._target_pause()
        process_name = self._services.name
        plugins = list(self._plugins)
        contexts = list(self._contexts)

        reasons: list[dict] = []
        for plugin, ctx in zip(plugins, contexts):
            node = f"{process_name}.{plugin.name}"
            state = plugin.state
            if state not in (PluginState.RUNNING, PluginState.PAUSED):
                # IDLE после упавшего configure, READY после упавшего start (design.md §3.3).
                reasons.append(self._reason(node, "failure", f"плагин не поднят ({state.value})"))
                continue
            reasons.extend(self._plugin_reasons(plugin, ctx, node))
            hook_reason = self._hook_failure_reason(plugin, state, target_pause)
            if hook_reason is not None:
                reasons.append(self._reason(node, "failure", hook_reason))

        ready = bool(announced) and not any(r["severity"] in _BLOCKING_SEVERITIES for r in reasons)
        paused = target_pause is True and not any(
            p.state is PluginState.RUNNING and self._should_pause(p) for p in plugins
        )
        return {
            "ready": ready,
            "reasons": self._cap_reasons(reasons, process_name),
            "paused": paused,
            "at": time.time(),
        }

    def reconcile_run_event(self) -> None:
        """Один проход сверки: цель (``run_event``) против состояния плагинов, по УРОВНЮ.

        Зовёт воркер ``run_watch`` (0,05 с). Событие снято → ``_do_pause`` каждому ``RUNNING``
        плагину, для которого :meth:`_should_pause`; взведено → ``_do_resume`` каждому
        ``PAUSED``. Не по фронту: событие, изменившееся пока хук блокирован, сходится
        следующим проходом; мигание ``clear()→set()`` быстрее опроса не вызывает хуков.
        Исключение хука плагина не обрывает обход соседей: оно становится причиной
        ``failure`` в снимке, повтор — не чаще ``_HOOK_RETRY_SEC`` на плагин.
        Событие читается заново перед каждым плагином. Нет события — ничего не делает.
        """
        event = self._run_event()
        if event is None:
            return
        with self._reconcile_lock:
            for plugin, ctx in zip(self._plugins, self._contexts):
                # Перед КАЖДЫМ хуком и под замком: request_stop() ставит флаг без замка.
                if self._stopping:
                    return
                pause = not event.is_set()
                state = plugin.state
                if pause:
                    due = state is PluginState.RUNNING and self._should_pause(plugin)
                else:
                    due = state is PluginState.PAUSED
                if not due:
                    # Состояние совпало с целью (или к плагину цель не применима):
                    # прежний отказ хука больше не актуален.
                    self._clear_hook_failure(plugin)
                    continue
                if self._hook_retry_pending(plugin, pause):
                    continue
                self._apply_hook(plugin, ctx, pause)

    def _run_event(self) -> Any | None:
        """Событие работы системы процесса (``_run_event`` кладёт раннер) или ``None``."""
        return getattr(self._services, "_run_event", None)

    def _target_pause(self) -> bool | None:
        """Цель наблюдателя: ``True`` — «пауза» (событие снято), ``False`` — «работа», ``None`` — события нет."""
        event = self._run_event()
        if event is None:
            return None
        return not event.is_set()

    def _run_watch_enabled(self) -> bool:
        """Есть ли у процесса наблюдатель события (предикат процесса; нет предиката → нет наблюдателя)."""
        predicate = getattr(self._services, "_run_watch_enabled", None)
        return bool(predicate()) if callable(predicate) else False

    def _should_pause(self, plugin: ProcessModulePlugin) -> bool:
        """Применима ли к плагину цель «пауза» — ОДНА функция для сверки и первой паузы в boot().

        Ложь для источника с ``run_gated: false`` (превью живёт при снятом событии, как в
        ``generic_process.py``: ``is_source`` и ``config_of(plugin).get("run_gated", True) is False``).
        """
        return not (plugin.is_source and self.config_of(plugin).get("run_gated", True) is False)

    def _boot_pause(self, plugin: ProcessModulePlugin, ctx: PluginContext) -> None:
        """Первая пауза в boot() (К5): ребёнок, рождённый при снятом событии, объявляет готовность в ``PAUSED``.

        Устройство не должно успеть отдать кадр до START. Только при наблюдателе
        (``_run_watch_enabled()``), который эту паузу снимет, — иначе плагины остаются ``RUNNING``.
        """
        if plugin.state is not PluginState.RUNNING or not self._run_watch_enabled():
            return
        if self._target_pause() is not True or not self._should_pause(plugin):
            return
        self._apply_hook(plugin, ctx, True)

    def _apply_hook(self, plugin: ProcessModulePlugin, ctx: PluginContext, pause: bool) -> bool:
        """``_do_pause``/``_do_resume`` под своим ``try``. Отказ — запись в ``_hook_failures`` (причина ``failure``)."""
        name = "pause" if pause else "resume"
        key = id(plugin)
        try:
            (plugin._do_pause if pause else plugin._do_resume)(ctx)
        except Exception as exc:  # noqa: BLE001 — сосед не должен пострадать от чужого хука
            with self._hook_failures_lock:
                previous = self._hook_failures.get(key)
                first_of_series = previous is None or previous["pause"] != pause
                self._hook_failures[key] = {
                    "pause": pause,
                    "type": type(exc).__name__,
                    "retry_at": time.monotonic() + _HOOK_RETRY_SEC,
                }
            if first_of_series:  # один лог на серию отказов, не на каждый повтор
                self._services.log_error(
                    f"PluginOrchestrator[{self._services.name}]: {name}() '{plugin.name}': {type(exc).__name__}: {exc}"
                )
            return False
        self._clear_hook_failure(plugin)
        return True

    def _hook_retry_pending(self, plugin: ProcessModulePlugin, pause: bool) -> bool:
        """Идёт ли ещё интервал до повтора упавшего хука ТОГО ЖЕ направления для плагина."""
        with self._hook_failures_lock:
            entry = self._hook_failures.get(id(plugin))
        return entry is not None and entry["pause"] == pause and time.monotonic() < entry["retry_at"]

    def _clear_hook_failure(self, plugin: ProcessModulePlugin) -> None:
        if self._hook_failures:  # быстрый путь: отказов нет — замок не берём
            with self._hook_failures_lock:
                self._hook_failures.pop(id(plugin), None)

    def _hook_failure_reason(
        self, plugin: ProcessModulePlugin, state: PluginState, target_pause: bool | None
    ) -> str | None:
        """Текст причины упавшего ``pause()/resume()`` или ``None``.

        Причина снимается, когда состояние плагина совпало с целью наблюдателя ИЛИ цель
        сменилась (иначе ``pause()`` упал при уже взведённом событии — плагин ``RUNNING`` = цель,
        перехода нет, причина висела бы вечно).
        """
        with self._hook_failures_lock:
            entry = self._hook_failures.get(id(plugin))
        if entry is None or target_pause is None or entry["pause"] != target_pause:
            return None
        if state is (PluginState.PAUSED if entry["pause"] else PluginState.RUNNING):
            return None
        return f"{'pause' if entry['pause'] else 'resume'}() упал: {entry['type']}"

    def _plugin_reasons(self, plugin: ProcessModulePlugin, ctx: PluginContext, node: str) -> list[dict]:
        """Причины ``plugin.readiness(ctx)``; сбой и неверная форма — ``failure`` без текста исключения."""
        key = id(plugin)
        try:
            raw = plugin.readiness(ctx)
        except Exception as exc:  # noqa: BLE001 — хук плагина не роняет снимок
            self._log_readiness_once(
                key, f"{type(exc).__name__}: {exc}", f"readiness() '{plugin.name}': {type(exc).__name__}: {exc}"
            )
            return [self._reason(node, "failure", f"readiness() упал: {type(exc).__name__}")]
        valid = isinstance(raw, list) and all(
            isinstance(item, dict) and item.get("severity") in _SEVERITIES and isinstance(item.get("reason"), str)
            for item in raw
        )
        if not valid:
            self._log_readiness_once(
                key, "malformed", f"readiness() '{plugin.name}' вернул неверную форму: {type(raw).__name__}"
            )
            return [self._reason(node, "failure", "readiness() вернул неверную форму")]
        self._readiness_logged.pop(key, None)  # серия отказов кончилась — следующий отказ снова в лог
        return [self._reason(node, item["severity"], item["reason"]) for item in raw]

    def _log_readiness_once(self, key: int, series_id: str, message: str) -> None:
        """Лог отказа ``readiness()`` — один раз на серию (снимок считается 2 раза в секунду)."""
        if self._readiness_logged.get(key) == series_id:
            return
        self._readiness_logged[key] = series_id
        self._services.log_error(f"PluginOrchestrator[{self._services.name}]: {message}")

    @staticmethod
    def _reason(node: str, severity: str, reason: str) -> dict:
        """Элемент ``reasons``: ровно ``node, severity, reason, source``; текст не длиннее ``_REASON_MAX_LEN``."""
        return {"node": node, "severity": severity, "reason": reason[:_REASON_MAX_LEN], "source": "readiness"}

    def _cap_reasons(self, reasons: list[dict], process_name: str) -> list[dict]:
        """Не больше ``_REASONS_MAX`` причин (с маркером): лишние отбрасываются, блокирующие — последними.

        ``ready`` к этому моменту уже посчитан по полному списку.
        """
        if len(reasons) <= _REASONS_MAX:
            return reasons
        ordered = sorted(
            reasons, key=lambda r: r["severity"] not in _BLOCKING_SEVERITIES
        )  # устойчиво: блокирующие первыми
        kept = ordered[: _REASONS_MAX - 1]
        kept.append(self._reason(process_name, "out_of_spec", f"причин больше {_REASONS_MAX}"))
        return kept

    # --- Properties ---

    @property
    def plugins(self) -> list[ProcessModulePlugin]:
        """Список загруженных плагинов."""
        return self._plugins

    @property
    def registers_manager(self) -> Any | None:
        """RegistersManager или None."""
        return self._registers_manager

    # --- Приватные методы ---

    def _load_plugin(self, class_path: str, plugin_name: str) -> ProcessModulePlugin:
        """Загрузить класс плагина по dotted path."""
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)

        if not (isinstance(cls, type) and issubclass(cls, ProcessModulePlugin)):
            raise TypeError(f"'{class_path}' не является ProcessModulePlugin")

        instance = cls()
        # Имя экземпляра берём из рецепта (plugin_name = instance id), а НЕ классовый
        # атрибут name. Позволяет несколько экземпляров одного класса с уникальными
        # именами (text_main/text_name — оба TextVectorPlugin). Конвенция
        # register_name == plugin_name (registers_backend) требует, чтобы instance.name
        # совпадал с plugin_name из топологии — иначе регистры экземпляров коллизятся.
        if plugin_name and plugin_name != "unknown":
            instance.name = plugin_name
        elif not instance.name:
            instance.name = plugin_name
        return instance

    @staticmethod
    def _resolve_plugin_class(class_path: str, plugin_name: str) -> str:
        """Резолв коротких имён плагинов через PluginRegistry.

        YAML может содержать либо полный dotted path
        (``Plugins.sources.camera_service.plugin.CameraServicePlugin``),
        либо короткое имя (``camera_service``) — тогда категория и путь
        вычисляются через PluginRegistry (discover был выполнен на старте).

        Если class_path пуст — резолвим по plugin_name.
        """
        from ..plugins.registry import PluginRegistry

        candidate = class_path or plugin_name
        if not candidate:
            return ""
        if "." in candidate:
            return candidate  # full dotted path
        entry = PluginRegistry.get(candidate)
        if entry is None:
            return ""
        return entry.class_path

    def _init_registers(
        self,
        early: list[tuple[ProcessModulePlugin, PluginContext]],
    ) -> Any | None:
        """Собрать register schemas от плагинов, создать RegistersManager.

        V3_MY_PURE: register_schema() — classmethod, возвращает list[type[SchemaBase]].
        Для обратной совместимости поддерживает и старый формат (SchemaBase instance).

        Единое правило имени (4.1, R6/Н-7): ``reg_name = SchemaBase.REGISTER_NAME or
        plugin_name`` — регистр владеет своим именем через classvar ``REGISTER_NAME``;
        пусто → конвенция register_name == plugin_name (обратная совместимость адресации
        GUI/live-write для одиночного регистра). Несколько регистров одного экземпляра
        ОБЯЗАНЫ объявить distinct ``REGISTER_NAME``. Коллизия ключа (multi без имён ИЛИ
        дубликат plugin_name между плагинами) — громкий лог + пропуск (выживает ПЕРВЫЙ),
        молча не теряем.
        """
        schemas: dict[str, Any] = {}

        def _put(reg_name: str, instance: Any, source: str) -> None:
            # Н-7: не затираем существующий регистр молча. Конфликт имени (несколько
            # регистров одного экземпляра ИЛИ два плагина с одинаковым plugin_name)
            # логируется громко, выживает ПЕРВЫЙ (fail-loud: «терять можно — молчать нельзя»).
            # Раньше `schemas[plugin.name] = instance` в цикле молча терял все регистры,
            # кроме последнего (R6 multi-register overwrite).
            if reg_name in schemas:
                self._services.log_error(
                    f"PluginOrchestrator[{self._services.name}]: конфликт имени регистра "
                    f"'{reg_name}' ({source}) — имя уже занято, регистр ПРОПУЩЕН (Н-7); "
                    f"дубликат plugin_name или несколько регистров под одним именем"
                )
                return
            schemas[reg_name] = instance
            self._services.log_info(
                f"PluginOrchestrator[{self._services.name}]: register '{reg_name}' schema loaded ({source})"
            )

        for plugin, _ctx in early:
            try:
                result = plugin.register_schema()
                # Нормализуем в список (V3_MY_PURE: list классов; legacy: одиночный instance).
                reg_items = result if isinstance(result, list) else ([result] if result is not None else [])
                for reg_item in reg_items:
                    instance = reg_item() if isinstance(reg_item, type) else reg_item
                    # Единое правило: имя регистра — СОБСТВЕННОЕ имя регистра
                    # (classvar `REGISTER_NAME`), если объявлено; иначе конвенция
                    # register_name == plugin_name (адресация GUI/live-write/топологии).
                    # Несколько регистров одного экземпляра ОБЯЗАНЫ объявить distinct
                    # `REGISTER_NAME` — без этого оба падают на plugin.name и второй
                    # ловится как коллизия в _put (loud-fail, не молча теряем — R6/Н-7).
                    reg_name = getattr(type(instance), "REGISTER_NAME", "") or plugin.name
                    _put(reg_name, instance, type(instance).__name__)
            except Exception as e:
                self._services.log_error(
                    f"PluginOrchestrator[{self._services.name}]: register_schema '{plugin.name}': {e}"
                )

        if not schemas:
            return None

        try:
            from multiprocess_framework.modules.registers_module import RegistersManager

            # logger=реальный LoggerManager, а НЕ self._services (Task Т.1):
            # RegistersManager — носитель ObservableMixin и зовёт слот каноничным
            # протоколом warning()/error()/…, которого у процесса-сервисов нет
            # (только log_warning()/…). Раньше весь его лог исчезал молча.
            # Момент безопасен: _init_custom_managers — шаг 6 initialize(),
            # менеджеры процесса созданы на шаге 3.
            rm = RegistersManager(registers=schemas, logger=self._services.logger_manager)
            self._registers_manager = rm
            return rm
        except Exception as e:
            self._services.log_error(f"PluginOrchestrator[{self._services.name}]: RegistersManager init: {e}")
            return None

    def _boot_registers(self, registers_manager: Any) -> None:
        """Boot-time: регистрация handler'а register_update от GUI/других процессов.

        (Раньше здесь же слались register_schemas в PM «для broadcast» — мёртвый
        relay: приёмника msg_type register_schemas нет нигде, dead letter. Удалён
        по плану comm-system §11.7.)
        """
        # P4.4.1 (B2): register_update — обычная команда CommandManager (kind-router
        # по type=command зовёт CM). Авто-reply транспорта (reply_to_request) — no-op
        # без request_id, поэтому GUI-путь остаётся fire-and-forget, а инициатор
        # с request_id (backend_ctl driver, Ф1.6 verify-probe) получает честный ack.
        cm = getattr(self._services, "command_manager", None)
        if cm is not None:
            cm.register_command(
                "register_update",
                self._on_register_update,
                expects_full_message=True,
                metadata={"description": "GUI/процесс обновляет значение регистра"},
                tags=["registers"],
            )
        else:  # fallback (нет CommandManager) — прежний прямой путь
            router = getattr(self._services, "router_manager", None)
            if router:
                router.register_message_handler("register_update", self._on_register_update)

    def _register_control_commands(self) -> None:
        """Регистрация control-команд плагинов (bypass). Не зависит от регистров.

        ``set_enabled`` — GUI/другой процесс включает/выключает ноду по имени плагина.
        Выключенная нода пропускает кадр без обработки (PluginRunner.call_process).
        """
        cm = getattr(self._services, "command_manager", None)
        if cm is None:
            return
        try:
            cm.register_command(
                "set_enabled",
                self._on_set_enabled,
                expects_full_message=True,
                metadata={"description": "Включить/выключить ноду (bypass)", "manages_own_reply": True},
                tags=["control"],
            )
        except Exception as e:  # noqa: BLE001 — регистрация команды не должна валить boot
            self._services.log_error(f"PluginOrchestrator[{self._services.name}]: register set_enabled: {e}")

    def _on_set_enabled(self, msg: dict) -> None:
        """Handler: переключить bypass плагина по имени (data: {plugin_name, enabled})."""
        data = msg.get("data", {})
        plugin_name = data.get("plugin_name")
        enabled = bool(data.get("enabled", True))
        if not plugin_name:
            return
        for plugin in self._plugins:
            if plugin.name == plugin_name:
                plugin.enabled = enabled
                self._services.log_info(
                    f"PluginOrchestrator[{self._services.name}]: нода '{plugin_name}' "
                    f"{'включена' if enabled else 'ВЫКЛЮЧЕНА (bypass)'}"
                )
                return
        self._services.log_error(
            f"PluginOrchestrator[{self._services.name}]: set_enabled — плагин '{plugin_name}' не найден"
        )

    def _on_register_update(self, msg: dict) -> dict:
        """Handler: GUI/другой процесс обновляет значение регистра.

        Контракт data: ``{"register", "field", "value"}`` (канон — тот же, что шлёт
        GUI через routing_map/CommandSender). Возвращает результат — авто-reply
        транспорта доставит его инициатору с request_id (fire-and-forget без
        request_id остаётся no-op'ом), некорректные ключи больше не тонут молча.
        """
        rm = self._registers_manager
        data = msg.get("data", {})
        register_name = data.get("register")
        field_name = data.get("field")
        value = data.get("value")

        if rm is None:
            return {"success": False, "error": "нет RegistersManager (плагины без register_schema)"}

        if not register_name or not field_name:
            return {
                "success": False,
                "error": "нужны data.register и data.field",
                "data_keys": sorted(data) if isinstance(data, dict) else [],
            }

        success, error = rm.set_field_value(register_name, field_name, value)
        if success:
            self._services.log_info(
                f"PluginOrchestrator[{self._services.name}]: register_update {register_name}.{field_name} = {value}"
            )
            # (Раньше тут был relay register_changed -> PM «для broadcast» — мёртвое
            # письмо: приёмника msg_type register_changed нет. Удалён по плану §11.7/8.)
            return {"success": True, "register": register_name, "field": field_name, "value": value}
        self._services.log_error(
            f"PluginOrchestrator[{self._services.name}]: register_update failed {register_name}.{field_name}: {error}"
        )
        return {"success": False, "register": register_name, "field": field_name, "error": str(error)}
