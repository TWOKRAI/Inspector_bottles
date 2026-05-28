"""RuntimeDeps -- frozen-контейнер runtime-зависимостей для create() табов.

Решение Q-F1 = вариант B: runtime-объекты (IPC-мосты, hot-reload менеджер,
bindings) НЕ входят в AppServices (editor-state). Вместо этого передаются
отдельным frozen dataclass вторым параметром в ``Tab.create(services, runtime)``.

Это by design разделение «editor-state (AppServices) vs runtime-state (RuntimeDeps)».
AppServices -- каталоги, конфиги, реестры (data-layer).
RuntimeDeps  -- IPC-прокси, discovery-менеджеры, Qt-bindings (runtime-layer).

Поля Optional с дефолтами None: табы, не использующие runtime, зовут
``Tab.create(services)`` (RuntimeDeps() по умолчанию).

NB: ``bindings`` живёт здесь, а не в AppServices — это закрывает Q4 Phase D
(«GuiStateBindings → AppServices»): bindings — runtime-объект (зависит от
DataReceiverBridge), поэтому его место в runtime-layer, не в editor-state.

Refs: plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md (Q-F1),
      plans/2026-05-27_cross-tab-architecture/phase-g.md (G.0.4, Q4 Phase D resolved)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_framework.modules.registers_module import RegistersManager
    from multiprocess_prototype.frontend.auth_context import AuthContext
    from multiprocess_prototype.frontend.bridge.command_sender import CommandSender
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge
    from multiprocess_prototype.frontend.state.bindings import GuiStateBindings


@dataclass(frozen=True)
class RuntimeDeps:
    """Frozen-контейнер runtime-зависимостей для фабрик табов.

    Передаётся вторым параметром в ``Tab.create(services, runtime)``
    (по умолчанию ``RuntimeDeps()`` -- все поля None).

    Поля:
        command_sender: IPC-отправка команд процессам (ProcessesTab).
        topology_bridge: GUI<->Runtime мост для field_set/state_delta (ProcessesTab).
        bindings: реактивные Qt-bindings к StateStore (ProcessesTab).
        plugin_manager: discovery/hot-reload плагинов (PluginsTab).
        registers_manager: live-регистры (FieldInfo-схемы + значения) для inspector-карточек
            Pipeline/Plugins. Runtime-объект (live-инстансы + observers), не editor-state →
            живёт здесь, а не в AppServices. domain RegistersBackend Protocol покрывает только
            value-семантику (FieldSpec), но forms-слой строит виджеты из framework FieldInfo,
            который domain не может экспонировать (запрет импорта framework). G.2 / Q-F1=B.
        auth_ctx: AuthContext (manager+state+audit) для admin-панелей (SettingsTab).
    """

    command_sender: "CommandSender | None" = None
    topology_bridge: "TopologyBridge | None" = None
    bindings: "GuiStateBindings | None" = None
    plugin_manager: Any = None
    registers_manager: "RegistersManager | None" = None
    auth_ctx: "AuthContext | None" = None
