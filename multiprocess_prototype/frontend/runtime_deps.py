"""RuntimeDeps -- двухслойный контейнер runtime-зависимостей для create() табов.

Решение Q-F1 = вариант B: runtime-объекты (IPC-мосты, hot-reload менеджер,
bindings) НЕ входят в AppServices (editor-state). Вместо этого передаются
отдельным frozen dataclass вторым параметром в ``Tab.create(services, runtime)``.

Это by design разделение «editor-state (AppServices) vs runtime-state (RuntimeDeps)».
AppServices -- каталоги, конфиги, реестры (data-layer).
RuntimeDeps  -- IPC-прокси, discovery-менеджеры, Qt-bindings (runtime-layer).

**Два слоя (Ф5.8):** runtime-контракт расслоён на framework-generic плумбинг и
app-специфичные extras — подготовка к ``app_module`` (Ф5.11) и minimal_app:

  - ``FrameworkRuntime`` -- runtime-плумбинг, нужный ЛЮБОМУ приложению-оболочке
    (IPC command_sender, topology/state-мосты, reactive bindings, data_bridge,
    control-proxy, restart-callback). minimal_app обходится только этим слоем.
  - ``RuntimeDeps(FrameworkRuntime)`` -- + app-extras конкретного приложения
    (плагин-discovery, live-регистры, auth, панель кадров, persist рецепта).
    minimal_app эти поля не задаёт (все Optional, дефолт None).

Расслоение через наследование frozen-dataclass (все поля с дефолтами): потребители
читают ``runtime.command_sender`` как раньше (поле унаследовано, ноль правок),
а ``RuntimeDeps`` IS-A ``FrameworkRuntime`` — фабрика/оболочка типизируется по
базовому контракту, приложение передаёт расширение. Физический переезд
``FrameworkRuntime`` во framework/``app_module`` (через Protocol'ы для мостов,
чтобы framework не знал прототипных типов) — Ф5.11; сейчас оба слоя здесь.

NB: ``bindings`` живёт в framework-слое, а не в AppServices — это закрывает Q4
Phase D («GuiStateBindings → AppServices»): bindings — runtime-объект (зависит от
DataReceiverBridge), поэтому его место в runtime-layer, не в editor-state.

Refs: plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md (Q-F1),
      plans/2026-05-27_cross-tab-architecture/phase-g.md (G.0.4, Q4 Phase D resolved),
      plans/2026-07-06_constructor-master/plan.md (Ф5.8), app-template-idea.md §3.2
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from multiprocess_framework.modules.registers_module import RegistersManager
    from multiprocess_prototype.frontend.auth_context import AuthContext
    from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
    from multiprocess_prototype.frontend.bridge.process_manager_proxy import ProcessManagerProxy
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings
    from multiprocess_prototype.domain.topology_session import TopologySession


@dataclass(frozen=True)
class FrameworkRuntime:
    """Framework-generic runtime-плумбинг: базовый слой контракта (Ф5.8).

    Всё, что нужно ЛЮБОЙ GUI-оболочке независимо от предметной области —
    IPC-отправка, мосты состояния, reactive bindings, control-proxy. minimal_app
    поднимается только на этом слое (без app-extras). Все поля Optional (дефолт
    None): оболочка без backend'а получает graceful no-op, не падает.

    Поля:
        command_sender: IPC-отправка команд процессам (ProcessesTab и др.).
        topology_bridge: GUI<->Runtime мост для field_set/state_delta.
        bindings: реактивные Qt-bindings к StateStore.
        process_manager_proxy: IPC-фасад управления живым ProcessManagerProcess
            (apply_topology / start / stop / restart). Тонкая обёртка над
            command_sender; None → кнопки управления дают понятный статус
            «backend недоступен», не падают. Этап 1 pipeline-live-control.
        request_ui_restart: узкий callback «перезапустить UI» для InterfaceSection
            (G.5.2). Заменяет прямой доступ к GuiProcess._restart_ui (Interface
            Segregation — секция знает только «перезапусти UI», не GuiProcess).
            None → кнопка «Обновить UI» = graceful no-op.
        data_bridge: DataReceiverBridge процесса — нужен вкладкам наблюдаемости
            (Ф5.20b) для подписки на observability_received (живой хвост
            Логи/Ошибки/Статистика). None → вкладки работают только на истории
            из стора, без живого хвоста.
    """

    command_sender: "CommandSender | None" = None
    topology_bridge: "TopologyBridge | None" = None
    bindings: "GuiStateBindings | None" = None
    process_manager_proxy: "ProcessManagerProxy | None" = None
    request_ui_restart: "Callable[[], None] | None" = None
    data_bridge: Any = None


@dataclass(frozen=True)
class RuntimeDeps(FrameworkRuntime):
    """App-слой контракта: FrameworkRuntime + app-extras конкретного приложения (Ф5.8).

    Передаётся вторым параметром в ``Tab.create(services, runtime)``
    (по умолчанию ``RuntimeDeps()`` -- все поля None). Поскольку наследует
    ``FrameworkRuntime``, плоские поля базового слоя (``command_sender`` и т.д.)
    доступны напрямую — потребители не различают слои, а ``app_module``/оболочка
    могут принимать узкий ``FrameworkRuntime``.

    App-extras (minimal_app их НЕ задаёт):
        plugin_manager: discovery/hot-reload плагинов (PluginsTab).
        registers_manager: live-регистры (FieldInfo-схемы + значения) для inspector-карточек
            Pipeline/Plugins. Runtime-объект (live-инстансы + observers), не editor-state →
            живёт здесь, а не в AppServices. domain RegistersBackend Protocol покрывает только
            value-семантику (FieldSpec), но forms-слой строит виджеты из framework FieldInfo,
            который domain не может экспонировать (запрет импорта framework). G.2 / Q-F1=B.
        auth_ctx: AuthContext (manager+state+audit) для admin-панелей (SettingsTab).
        image_panel: главная панель кадров (ImagePanelWidget) — runtime-объект. Нужен
            DisplaysTab для снимка дисплея (grab_frame). None → кнопка «Снимок» даёт
            статус «нет кадра».
        persist_active_recipe: persist активного рецепта в манифест (app.yaml →
            pipeline) при активации. Закрывает loop: активация в GUI → app.yaml
            обновлён → следующий старт восстанавливает рецепт (см. app.py restore).
            None → no-op (persist отключён). Запись через ruamel round-trip —
            комментарии app.yaml сохраняются.
    """

    plugin_manager: Any = None
    registers_manager: "RegistersManager | None" = None
    auth_ctx: "AuthContext | None" = None
    image_panel: Any = None
    persist_active_recipe: "Callable[[str], None] | None" = None
    # RS-4 dirty-контур: сессия редактора топологии (dirty/diverged + уведомления).
    # Runtime-объект (mutable, callbacks, живёт с работающим приложением) → место в
    # runtime-layer, не в AppServices (editor-state catalogs). Презентеры Pipeline/
    # Recipes читают его для confirm-перед-активацией и mark_saved/applied/loaded.
    # None → dirty-контур выключен (graceful: активация/сохранение как раньше).
    topology_session: "TopologySession | None" = None
    # Локальный read-model телеметрии (TelemetryViewModel, frontend_module.state).
    # Питается wildcard-потоком дельт, читается вкладками локально
    # (get/snapshot/history) без похода на сервер; он же — источник late-binding-
    # снимка для GuiStateBindings (единый read-model). None → живой телеметрии
    # нет (метрики «—»). Runtime-объект (Qt-сигналы, живёт с приложением).
    telemetry: Any = None
