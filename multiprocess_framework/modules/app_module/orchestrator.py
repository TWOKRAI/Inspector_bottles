"""``GenericProcessManagerApp`` — generic-оркестратор «рыбы» (Ф5.12).

Верхний композиционный ярус даёт не только сборку (``SystemBuilder``), но и
**generic-оркестратор** — подкласс framework-ядра ``ProcessManagerProcess``,
на котором бутится любое приложение-скелет (minimal_app) без единого хука.

Два сорта хук-точек (следствие spawn + Dict-at-Boundary):

* **build-time** (launcher-процесс, до spawn) — обычные callable в ``AppSpec``
  (:class:`StateBootstrap`, :class:`ThrottleRules`). Выполняются в родителе,
  их РЕЗУЛЬТАТ (dict) пиклится в ``orchestrator_config`` → потребляется здесь
  child-side (:meth:`_setup_state_store`).
* **runtime** (после spawn) — callable НЕ пиклится через spawn, поэтому паттерн
  ``orchestrator_class_path`` (import-path строка + dict, резолв на стороне
  ребёнка). Приложение подставляет свой подкласс и переопределяет seam'ы
  (:meth:`_configure_runtime`, :meth:`apply_topology`) — так реализован
  прототипный ``ProcessManagerProcessApp``.

**Правило против hook-взрыва** (ADR-APP-006): в ``AppSpec`` попадает только хук,
который прототип нуждается сегодня И без которого бутится minimal_app (хук
опционален). Поэтому :meth:`_setup_state_store` пропускает создание StateStore,
когда ни ``initial_state``, ни ``state_throttle_rules`` не заданы — state-plane
подключается ТОЛЬКО приложением, которое его действительно использует.

Инвариант яруса: этот модуль резолвится child-side по import-path строке
(Dict-at-Boundary), внутри framework его статически никто не импортирует.
"""

from __future__ import annotations

from typing import Any, Optional

from multiprocess_framework.modules.process_manager_module.process.process_manager_process import (
    ProcessManagerProcess,
)


class GenericProcessManagerApp(ProcessManagerProcess):
    """Generic-оркестратор яруса 2: base ``ProcessManagerProcess`` + generic-хуки.

    Даёт три config-gated generic-возможности поверх ядра:

    1. :meth:`_setup_state_store` — реактивный StateStore из ``initial_state`` +
       ``state_throttle_rules`` (результаты build-time хуков). Опционален.
    2. :meth:`_start_observability_watcher` — hot-reload observability-конфига
       (``observability_config_path``). Опционален.
    3. :meth:`_configure_runtime` — seam для runtime-хуков подкласса (no-op).

    minimal_app бутится на этом классе без единого хука: все три возможности
    выключаются пустым конфигом.
    """

    #: Хендл observability-watcher (None, пока не запущен / нет конфига).
    _observability_watcher: Optional[Any] = None

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Base-инициализация + runtime-seam подкласса + observability-watcher.

        Порядок:
        1. ``super().initialize()`` — ProcessManagerProcess (managers, topology,
           :meth:`_setup_state_store`, процессы из config, monitor).
        2. :meth:`_configure_runtime` — runtime-хуки подкласса (напр. прототипный
           topology-engine). No-op в generic. **До** watcher'а — так подкласс
           конфигурируется на «холодной» системе, до фоновых потоков.
        3. :meth:`_start_observability_watcher` — фоновый hot-reload (config-gated).
        """
        if not super().initialize():
            return False
        self._configure_runtime()
        self._start_observability_watcher()
        return True

    def _configure_runtime(self) -> None:
        """Seam для runtime-хуков подкласса (после base-init, до watcher'а).

        Generic — no-op. Прототип переопределяет: конфигурирует topology-engine
        (BlueprintAssembler + FullReplacePlanner). Это и есть runtime-хук,
        резолвимый child-side через ``orchestrator_class_path``.
        """

    def shutdown(self) -> bool:
        """Остановить watcher (нет висящих потоков), затем штатный shutdown ядра."""
        if self._observability_watcher is not None:
            try:
                self._observability_watcher.stop()
            except Exception as exc:  # noqa: BLE001 — shutdown best-effort
                self._log_error(f"[observability] watcher stop: {exc}")
            self._observability_watcher = None
        return super().shutdown()

    # ------------------------------------------------------------------
    # Generic-возможности (config-gated, опциональны)
    # ------------------------------------------------------------------

    def _start_observability_watcher(self) -> None:
        """Hot-reload observability-конфига. No-op без ``observability_config_path``."""
        config_path = self.get_config("observability_config_path") or ""
        if not config_path:
            return
        from multiprocess_framework.modules.process_module.managers.observability_reload import (
            start_observability_watcher,
        )

        self._observability_watcher = start_observability_watcher(
            config_path=config_path,
            logger=self.logger_manager,
            error=self.error_manager,
            stats=self.stats_manager,
            log_info=self._log_info,
            log_error=self._log_error,
        )

    def _setup_state_store(self) -> None:
        """Создать реактивный StateStore из build-time хуков. Опционален.

        Потребляет РЕЗУЛЬТАТ build-time хуков ``state_bootstrap`` (→ ``initial_state``)
        и ``throttle_rules`` (→ ``state_throttle_rules``), запикленный в
        ``orchestrator_config`` в родительском процессе.

        Анти-хук-взрыв (ADR-APP-006): если приложение не задало НИ ``initial_state``,
        НИ ``state_throttle_rules`` (minimal_app), state-plane не поднимается — как
        в base ``ProcessManagerProcess`` (хук опционален).
        """
        initial_state = self.get_config("initial_state") or {}
        throttle_rules = self.get_config("state_throttle_rules")

        if not initial_state and not throttle_rules:
            # Нет state-plane у приложения — не платим за пустой StateStore.
            return

        from multiprocess_framework.modules.state_store_module.manager.state_store_manager import (
            StateStoreManager,
        )

        # auto_register_ipc=False: НЕ регистрировать state.* напрямую (RAW) в
        # event_dispatcher. state.* — команды CommandManager (register_commands
        # ниже), kind-router в receive() диспатчит их туда по type=="command",
        # reply делает транспорт. RAW-копии в event_dispatcher были бы dead-path.
        # router всё равно нужен DeltaDispatcher'у (push дельт).
        self._state_store_manager = StateStoreManager(
            router=self.router_manager,
            initial_state=initial_state,
            logger=self,
            auto_register_ipc=False,
        )

        if throttle_rules:
            from multiprocess_framework.modules.state_store_module.middleware.throttle import (
                ThrottleMiddleware,
            )

            self._state_store_manager.use(ThrottleMiddleware(throttle_rules))

        self._state_store_manager.initialize()

        # Регистрация команд state.set/get/subscribe/... в CommandManager.
        # kind-router в receive() диспатчит входящие state.* (type=="command")
        # напрямую в CommandManager, reply делает транспорт по request_id.
        if self.command_manager:
            self._state_store_manager.register_commands(self.command_manager)
