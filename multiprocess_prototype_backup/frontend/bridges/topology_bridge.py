"""TopologyBridge — единый bridge для отправки SystemTopology на бэкенд.

Координирует три транспорта:
  - IPC Commands → processes/workers (lifecycle через ProcessManager)
  - Register Writes → cameras/regions/pipeline (параметры через FieldRouting)
  - Direct API → displays (UI-виджеты через DisplayWindowManager)

Гарантирует порядок: сначала create процессов (IPC), потом параметры (Register),
потом displays (Direct API).

Guard-паттерн (_writing) предотвращает рекурсию при register writes.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Callable, Optional, TYPE_CHECKING

from multiprocess_prototype.registers.system_topology.converters import (
    extract_display_diff,
    extract_process_commands,
    extract_source_commands,
    extract_wire_commands,
)
from multiprocess_prototype.registers.system_topology.schemas import (
    ALL_SECTIONS,
    SECTION_DISPLAYS,
    SECTION_PIPELINE,
    SECTION_PROCESSES,
    SECTION_SOURCES,
    SECTION_WIRES,
)

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor

logger = logging.getLogger(__name__)


class TopologyBridge:
    """Единый bridge: координирует три транспорта для отправки SystemTopology.

    Заменяет три отдельных bridge-а:
    - ProcessConfigBridge (374 строки → удалён)
    - TopologyRegisterBridge (120 строк → удалён)
    - Direct API calls в DisplayTabWidget

    Все три транспорта остаются — каждый оптимален для своего типа данных.
    Унифицируем модель, не транспорт.
    """

    def __init__(
        self,
        editor: SystemTopologyEditor,
        command_handler: Any = None,
        registers_manager: Any = None,
        window_manager: Any = None,
        display_router: Any = None,
    ) -> None:
        """Инициализация bridge.

        Args:
            editor: SystemTopologyEditor — единая модель конфигурации.
            command_handler: GuiCommandHandler для IPC commands (может быть None в тестах).
            registers_manager: RegistersManager для register writes (может быть None).
            window_manager: DisplayWindowManager для direct API (может быть None).
            display_router: DisplayRouter для подписок на кадры (может быть None).
        """
        self._editor = editor
        self._cmd = command_handler
        self._rm = registers_manager
        self._wm = window_manager
        self._dr = display_router

        # Guard от рекурсии при register writes
        self._writing = False

        # Last applied state для diff
        self._current: Optional[dict] = None

    # ------------------------------------------------------------------
    # Загрузка из бэкенда
    # ------------------------------------------------------------------

    def load_from_backend(self) -> None:
        """Собрать текущее состояние из всех источников → editor.load().

        Источники:
        - RegistersManager: SOURCES_REGISTER → cameras/regions
        - RegistersManager: PROCESSING_REGISTER → pipeline
        - DisplayWindowManager: list_windows() → displays
        - Processes: пока из editor (будет polling через ProcessDataBridge)
        """
        data: dict = {
            "processes": {},
            "workers": {},
            "cameras": {},
            "regions": {},
            "pipeline": {},
            "displays": {},
            "wires": {},
        }

        # Register Writes path: cameras/regions
        if self._rm is not None:
            try:
                sources_reg = self._rm.get_register("sources")
                if sources_reg is not None:
                    dumped = sources_reg.model_dump() if hasattr(sources_reg, "model_dump") else {}
                    data["cameras"] = dumped.get("cameras", {})
                    data["regions"] = dumped.get("regions", {})
            except Exception:
                logger.exception("TopologyBridge: ошибка загрузки SOURCES_REGISTER")

            # Pipeline
            try:
                proc_reg = self._rm.get_register("processing")
                if proc_reg is not None:
                    dumped = proc_reg.model_dump() if hasattr(proc_reg, "model_dump") else {}
                    data["pipeline"] = dumped.get("region_pipelines", {})
            except Exception:
                logger.exception("TopologyBridge: ошибка загрузки PROCESSING_REGISTER")

        # Direct API path: displays
        if self._wm is not None:
            try:
                for win_id in self._wm.list_windows():
                    data["displays"][win_id] = {
                        "name": win_id,
                        "source_ref": "",
                        "fps_limit": 30,
                    }
            except Exception:
                logger.exception("TopologyBridge: ошибка загрузки displays")

        self._editor.load(data)
        self._current = deepcopy(data)

        logger.info(
            "TopologyBridge: загружено — камер: %d, процессов: %d, displays: %d",
            len(data["cameras"]),
            len(data["processes"]),
            len(data["displays"]),
        )

    # ------------------------------------------------------------------
    # Применение изменений
    # ------------------------------------------------------------------

    def apply(self, section: Optional[str] = None) -> bool:
        """Применить изменения. section=None → всё, иначе только секция.

        Порядок при полном apply:
          1. processes (IPC Commands) — сначала создать процессы
          2. sources (Register Writes) — потом записать параметры
          3. pipeline (Register Writes)
          4. wires (IPC Commands) — SHM + routes между процессами
          5. displays (Direct API)

        Args:
            section: SECTION_PROCESSES / SECTION_SOURCES / SECTION_PIPELINE /
                     SECTION_DISPLAYS / None (всё).

        Returns:
            True если применено успешно.
        """
        # Валидация
        errors = self._editor.validate(section)
        if errors:
            logger.warning("TopologyBridge.apply: ошибки валидации: %s", errors)
            return False

        data = self._editor.to_dict()
        success = True

        if section is None or section == SECTION_PROCESSES:
            if not self._apply_processes(data):
                success = False

        if section is None or section == SECTION_SOURCES:
            if not self._apply_sources(data):
                success = False

        if section is None or section == SECTION_PIPELINE:
            if not self._apply_pipeline(data):
                success = False

        if section is None or section == SECTION_WIRES:
            if not self._apply_wires(data):
                success = False

        if section is None or section == SECTION_DISPLAYS:
            if not self._apply_displays(data):
                success = False

        # Mark clean и обновить current state
        self._editor.mark_clean(section)
        self._current = deepcopy(data)

        logger.info("TopologyBridge.apply(section=%s): success=%s", section, success)
        return success

    # ------------------------------------------------------------------
    # Транспорт A: IPC Commands → ProcessManager
    # ------------------------------------------------------------------

    def _apply_processes(self, data: dict) -> bool:
        """Отправить IPC-команды для lifecycle процессов/воркеров.

        Args:
            data: SystemTopology dict.

        Returns:
            True если все команды отправлены.
        """
        if self._cmd is None:
            logger.debug("TopologyBridge: command_handler не задан, пропуск processes")
            return True

        commands = extract_process_commands(self._current, data)
        if not commands:
            return True

        success = True
        for cmd in commands:
            ok = self._cmd.send("process.command", data=cmd)
            if not ok:
                logger.error("TopologyBridge: команда не отправлена: %s", cmd)
                success = False
            else:
                logger.info("TopologyBridge: отправлена команда: %s", cmd.get("cmd"))

        return success

    # ------------------------------------------------------------------
    # Транспорт B: Register Writes → FieldRouting → процессы
    # ------------------------------------------------------------------

    def _apply_sources(self, data: dict) -> bool:
        """Записать cameras/regions в SOURCES_REGISTER.

        RegistersManager автоматически прочитает FieldRouting и отправит
        register_update в целевые процессы.

        Args:
            data: SystemTopology dict.

        Returns:
            True если запись успешна.
        """
        if self._rm is None:
            logger.debug("TopologyBridge: registers_manager не задан, пропуск sources")
            return True

        self._writing = True
        try:
            ok1, err1 = self._rm.set_field_value("sources", "cameras", data.get("cameras", {}))
            if not ok1:
                logger.error("TopologyBridge: запись cameras: %s", err1)

            ok2, err2 = self._rm.set_field_value("sources", "regions", data.get("regions", {}))
            if not ok2:
                logger.error("TopologyBridge: запись regions: %s", err2)

            return ok1 and ok2
        except Exception:
            logger.exception("TopologyBridge: ошибка записи sources")
            return False
        finally:
            self._writing = False

    def _apply_pipeline(self, data: dict) -> bool:
        """Записать pipeline config в PROCESSING_REGISTER.

        Args:
            data: SystemTopology dict.

        Returns:
            True если запись успешна.
        """
        if self._rm is None:
            logger.debug("TopologyBridge: registers_manager не задан, пропуск pipeline")
            return True

        self._writing = True
        try:
            ok, err = self._rm.set_field_value(
                "processing", "region_pipelines", data.get("pipeline", {})
            )
            if not ok:
                logger.error("TopologyBridge: запись pipeline: %s", err)
            return ok
        except Exception:
            logger.exception("TopologyBridge: ошибка записи pipeline")
            return False
        finally:
            self._writing = False

    # ------------------------------------------------------------------
    # Транспорт D: IPC Commands → wire management (SHM + routes)
    # ------------------------------------------------------------------

    def _apply_wires(self, data: dict) -> bool:
        """Отправить IPC-команды для wire management (SHM + routes).

        Порядок: teardown removed → setup added → teardown+setup modified.

        Args:
            data: SystemTopology dict.

        Returns:
            True если все команды отправлены.
        """
        if self._cmd is None:
            logger.debug("TopologyBridge: command_handler не задан, пропуск wires")
            return True

        commands = extract_wire_commands(self._current, data)
        if not commands:
            return True

        success = True
        for cmd in commands:
            ok = self._cmd.send("process.command", data=cmd)
            if not ok:
                logger.error("TopologyBridge: wire-команда не отправлена: %s", cmd)
                success = False
            else:
                logger.info(
                    "TopologyBridge: wire-команда отправлена: %s (%s)",
                    cmd.get("cmd"),
                    cmd.get("wire_key"),
                )

        return success

    # ------------------------------------------------------------------
    # Транспорт C: Direct API → DisplayWindowManager
    # ------------------------------------------------------------------

    def _apply_displays(self, data: dict) -> bool:
        """Применить изменения displays через Direct API.

        Args:
            data: SystemTopology dict.

        Returns:
            True если применено.
        """
        if self._wm is None:
            logger.debug("TopologyBridge: window_manager не задан, пропуск displays")
            return True

        diff = extract_display_diff(self._current, data)
        if not diff["has_changes"]:
            return True

        try:
            # Удалить убранные окна
            for win_id in diff["removed"]:
                self._wm.destroy_window(win_id)

            # Создать новые окна
            for win_id, cfg in diff["added"].items():
                source_ref = cfg.get("source_ref", "") if isinstance(cfg, dict) else ""
                self._wm.create_window(win_id, source_ref=source_ref)

            # Пересоздать изменённые (destroy + create)
            for win_id, cfg in diff["modified"].items():
                self._wm.destroy_window(win_id)
                source_ref = cfg.get("source_ref", "") if isinstance(cfg, dict) else ""
                self._wm.create_window(win_id, source_ref=source_ref)

            return True
        except Exception:
            logger.exception("TopologyBridge: ошибка применения displays")
            return False

    # ------------------------------------------------------------------
    # Подписка на внешние изменения
    # ------------------------------------------------------------------

    def subscribe_to_changes(self) -> None:
        """Подписаться на внешние изменения регистров.

        Guard: _writing предотвращает рекурсию (наша собственная запись).
        Guard: editor.is_dirty() — не перезаписываем несохранённые изменения.
        """
        if self._rm is None:
            return

        self._rm.subscribe("sources", "cameras", self._on_external_change)
        self._rm.subscribe("sources", "regions", self._on_external_change)

    def _on_external_change(self, value: Any) -> None:
        """Обработчик внешних изменений регистров."""
        if self._writing:
            return  # Наша собственная запись — игнорируем

        if self._editor.is_dirty():
            logger.debug(
                "TopologyBridge: внешнее изменение проигнорировано — есть несохранённые правки"
            )
            return

        logger.info("TopologyBridge: внешнее изменение регистра — перезагрузка")
        self.load_from_backend()


__all__ = ["TopologyBridge"]
