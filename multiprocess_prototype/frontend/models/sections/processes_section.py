"""ProcessesSectionView — управление секцией processes/workers.

API совместим с ProcessEditorModel для минимальных изменений в UI.
Бизнес-логика: protected workers, cascade delete, auto-sort_order.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from multiprocess_prototype.registers.system_topology.schemas import SECTION_PROCESSES

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor

logger = logging.getLogger(__name__)


class ProcessesSectionView:
    """Section View для процессов и воркеров.

    Делегирует хранение в SystemTopologyEditor._data["processes"] и ["workers"].
    Каждая мутация уведомляет подписчиков секции SECTION_PROCESSES.
    """

    def __init__(self, editor: SystemTopologyEditor) -> None:
        self._editor = editor

    # ------------------------------------------------------------------
    # Properties (read)
    # ------------------------------------------------------------------

    @property
    def processes(self) -> Dict[str, dict]:
        """Текущие процессы (ссылка на данные editor, не копия)."""
        return self._editor._data.get("processes", {})

    @property
    def workers(self) -> Dict[str, dict]:
        """Текущие воркеры (ссылка на данные editor, не копия)."""
        return self._editor._data.get("workers", {})

    @property
    def dirty(self) -> bool:
        """Есть ли несохранённые изменения в секции процессов."""
        return self._editor.is_dirty(SECTION_PROCESSES)

    # ------------------------------------------------------------------
    # Process CRUD
    # ------------------------------------------------------------------

    def add_process(
        self,
        name: str,
        class_path: str,
        priority: str = "normal",
        auto_start: bool = True,
    ) -> str:
        """Добавить процесс + автоматически создать protected main-воркер.

        Args:
            name: Уникальное имя процесса.
            class_path: Полный путь к классу процесса.
            priority: Приоритет (normal/high/realtime).
            auto_start: Запускать ли автоматически.

        Returns:
            Ключ созданного процесса.
        """
        proc_key = name
        sort_order = len(self.processes)

        self._editor.update_item("processes", proc_key, {
            "name": name,
            "class_path": class_path,
            "priority": priority,
            "auto_start": auto_start,
            "sort_order": sort_order,
        })

        # Автоматически создаём protected main-воркер
        worker_key = f"{proc_key}_main"
        self._editor._data.setdefault("workers", {})[worker_key] = {
            "process_ref": proc_key,
            "name": "main",
            "worker_type": "router_poll",
            "enabled": True,
            "protected": True,
            "target_interval_ms": 0,
            "sort_order": 0,
        }
        # Notification уже отправлен из update_item

        logger.info("ProcessesSectionView: добавлен процесс '%s' + main worker", name)
        return proc_key

    def remove_process(self, proc_key: str) -> None:
        """Удалить процесс и все его воркеры (cascade delete).

        Args:
            proc_key: Ключ процесса.

        Raises:
            KeyError: Если процесс не найден.
        """
        if proc_key not in self.processes:
            raise KeyError(f"Процесс '{proc_key}' не найден")

        # Cascade: удалить все воркеры процесса
        worker_keys = [
            wk for wk, w in self.workers.items()
            if w.get("process_ref") == proc_key
        ]
        for wk in worker_keys:
            self._editor._data["workers"].pop(wk, None)

        self._editor.remove_item("processes", proc_key)
        logger.info(
            "ProcessesSectionView: удалён процесс '%s' + %d воркеров",
            proc_key, len(worker_keys),
        )

    def modify_process(self, proc_key: str, fields: dict) -> None:
        """Обновить поля процесса.

        Args:
            proc_key: Ключ процесса.
            fields: Dict с обновляемыми полями.

        Raises:
            KeyError: Если процесс не найден.
        """
        if proc_key not in self.processes:
            raise KeyError(f"Процесс '{proc_key}' не найден")

        proc = self.processes[proc_key]
        proc.update(fields)
        self._editor._notify_section(SECTION_PROCESSES)

    # ------------------------------------------------------------------
    # Worker CRUD
    # ------------------------------------------------------------------

    def add_worker(
        self,
        process_ref: str,
        name: str,
        worker_type: str = "custom",
        target_interval_ms: int = 0,
    ) -> str:
        """Добавить воркер к процессу.

        Args:
            process_ref: Ключ процесса-владельца.
            name: Имя воркера.
            worker_type: Тип (router_poll/loop/task/custom).
            target_interval_ms: Целевой интервал цикла.

        Returns:
            Ключ созданного воркера.

        Raises:
            KeyError: Если процесс не найден.
        """
        if process_ref not in self.processes:
            raise KeyError(f"Процесс '{process_ref}' не найден")

        worker_key = f"{process_ref}_{name}"
        sort_order = len(self.workers_for_process(process_ref))

        self._editor.update_item("workers", worker_key, {
            "process_ref": process_ref,
            "name": name,
            "worker_type": worker_type,
            "enabled": True,
            "protected": False,
            "target_interval_ms": target_interval_ms,
            "sort_order": sort_order,
        })

        logger.info("ProcessesSectionView: добавлен воркер '%s' → '%s'", name, process_ref)
        return worker_key

    def remove_worker(self, worker_key: str) -> None:
        """Удалить воркер.

        Args:
            worker_key: Ключ воркера.

        Raises:
            KeyError: Если воркер не найден.
            ValueError: Если воркер protected (нельзя удалить через GUI).
        """
        if worker_key not in self.workers:
            raise KeyError(f"Воркер '{worker_key}' не найден")

        worker = self.workers[worker_key]
        if worker.get("protected"):
            raise ValueError(f"Воркер '{worker_key}' защищён (protected), удаление запрещено")

        self._editor.remove_item("workers", worker_key)
        logger.info("ProcessesSectionView: удалён воркер '%s'", worker_key)

    def modify_worker(self, worker_key: str, fields: dict) -> None:
        """Обновить поля воркера.

        Args:
            worker_key: Ключ воркера.
            fields: Dict с обновляемыми полями.

        Raises:
            KeyError: Если воркер не найден.
            ValueError: Если пытаемся снять protected.
        """
        if worker_key not in self.workers:
            raise KeyError(f"Воркер '{worker_key}' не найден")

        worker = self.workers[worker_key]
        if worker.get("protected") and fields.get("protected") is False:
            raise ValueError(f"Нельзя снять protected с воркера '{worker_key}'")

        worker.update(fields)
        self._editor._notify_section(SECTION_PROCESSES)

    def workers_for_process(self, proc_key: str) -> Dict[str, dict]:
        """Все воркеры процесса.

        Args:
            proc_key: Ключ процесса.

        Returns:
            Dict[worker_key, worker_dict].
        """
        return {
            k: v for k, v in self.workers.items()
            if v.get("process_ref") == proc_key
        }

    # ------------------------------------------------------------------
    # Plugin CRUD
    # ------------------------------------------------------------------

    def plugins_for_process(self, proc_key: str) -> List[dict]:
        """Список плагинов процесса (ссылка, не копия).

        Args:
            proc_key: Ключ процесса.

        Returns:
            Список dict-конфигов плагинов (ссылка на внутренние данные).

        Raises:
            KeyError: Если процесс не найден.
        """
        if proc_key not in self.processes:
            raise KeyError(f"Процесс '{proc_key}' не найден")

        proc = self.processes[proc_key]
        # Гарантируем наличие ключа plugins
        if "plugins" not in proc:
            proc["plugins"] = []
        return proc["plugins"]

    def add_plugin(self, proc_key: str, plugin_dict: dict) -> int:
        """Добавить плагин в конец списка плагинов процесса.

        Args:
            proc_key: Ключ процесса.
            plugin_dict: Dict с обязательными ключами plugin_class и plugin_name.

        Returns:
            Индекс добавленного плагина (len - 1).

        Raises:
            KeyError: Если процесс не найден.
            ValueError: Если plugin_dict не содержит plugin_class или plugin_name.
            ValueError: Если plugin_name уже существует в процессе.
        """
        if proc_key not in self.processes:
            raise KeyError(f"Процесс '{proc_key}' не найден")

        if "plugin_class" not in plugin_dict:
            raise ValueError("plugin_dict должен содержать ключ 'plugin_class'")
        if "plugin_name" not in plugin_dict:
            raise ValueError("plugin_dict должен содержать ключ 'plugin_name'")

        plugins = self.plugins_for_process(proc_key)
        new_name = plugin_dict["plugin_name"]

        # Проверяем уникальность plugin_name
        existing_names = [p.get("plugin_name") for p in plugins]
        if new_name in existing_names:
            raise ValueError(
                f"Плагин с plugin_name='{new_name}' уже существует в процессе '{proc_key}'"
            )

        plugins.append(plugin_dict)
        self._editor._notify_section(SECTION_PROCESSES)

        index = len(plugins) - 1
        logger.info(
            "ProcessesSectionView: добавлен плагин '%s' → процесс '%s' [idx=%d]",
            new_name, proc_key, index,
        )
        return index

    def remove_plugin(self, proc_key: str, index: int) -> dict:
        """Удалить плагин по индексу.

        Args:
            proc_key: Ключ процесса.
            index: Индекс плагина в списке.

        Returns:
            Удалённый dict плагина.

        Raises:
            KeyError: Если процесс не найден.
            IndexError: Если индекс выходит за границы.
        """
        if proc_key not in self.processes:
            raise KeyError(f"Процесс '{proc_key}' не найден")

        plugins = self.plugins_for_process(proc_key)

        if index < 0 or index >= len(plugins):
            raise IndexError(
                f"Индекс {index} выходит за границы списка плагинов "
                f"процесса '{proc_key}' (len={len(plugins)})"
            )

        removed = plugins.pop(index)
        self._editor._notify_section(SECTION_PROCESSES)

        logger.info(
            "ProcessesSectionView: удалён плагин '%s' из процесса '%s'",
            removed.get("plugin_name", "?"), proc_key,
        )
        return removed

    def move_plugin(self, proc_key: str, from_idx: int, to_idx: int) -> None:
        """Переместить плагин с одной позиции на другую.

        Args:
            proc_key: Ключ процесса.
            from_idx: Исходный индекс.
            to_idx: Целевой индекс.

        Raises:
            KeyError: Если процесс не найден.
            IndexError: Если любой из индексов выходит за границы.
        """
        if proc_key not in self.processes:
            raise KeyError(f"Процесс '{proc_key}' не найден")

        plugins = self.plugins_for_process(proc_key)
        n = len(plugins)

        if from_idx < 0 or from_idx >= n:
            raise IndexError(
                f"from_idx={from_idx} выходит за границы списка плагинов "
                f"процесса '{proc_key}' (len={n})"
            )
        if to_idx < 0 or to_idx >= n:
            raise IndexError(
                f"to_idx={to_idx} выходит за границы списка плагинов "
                f"процесса '{proc_key}' (len={n})"
            )

        # Если индексы совпадают — no-op, без notification
        if from_idx == to_idx:
            return

        item = plugins.pop(from_idx)
        plugins.insert(to_idx, item)
        self._editor._notify_section(SECTION_PROCESSES)

        logger.info(
            "ProcessesSectionView: перемещён плагин '%s' [%d → %d] в процессе '%s'",
            item.get("plugin_name", "?"), from_idx, to_idx, proc_key,
        )

    def update_plugin_config(self, proc_key: str, index: int, fields: dict) -> None:
        """Обновить поля конфига плагина.

        Args:
            proc_key: Ключ процесса.
            index: Индекс плагина в списке.
            fields: Dict с обновляемыми полями.

        Raises:
            KeyError: Если процесс не найден.
            IndexError: Если индекс выходит за границы.
        """
        if proc_key not in self.processes:
            raise KeyError(f"Процесс '{proc_key}' не найден")

        plugins = self.plugins_for_process(proc_key)

        if index < 0 or index >= len(plugins):
            raise IndexError(
                f"Индекс {index} выходит за границы списка плагинов "
                f"процесса '{proc_key}' (len={len(plugins)})"
            )

        plugins[index].update(fields)
        self._editor._notify_section(SECTION_PROCESSES)

        logger.info(
            "ProcessesSectionView: обновлён конфиг плагина [idx=%d] в процессе '%s', поля: %s",
            index, proc_key, list(fields.keys()),
        )

    # ------------------------------------------------------------------
    # Snapshot для ActionBus undo/redo
    # ------------------------------------------------------------------

    def full_snapshot(self) -> dict:
        """Полный снимок секции (для undo/redo).

        Returns:
            {"processes": {...}, "workers": {...}} — deepcopy.
        """
        return {
            "processes": deepcopy(self.processes),
            "workers": deepcopy(self.workers),
        }

    def load_from_snapshot(self, data: dict) -> None:
        """Загрузить состояние из snapshot (для undo/redo).

        Args:
            data: {"processes": {...}, "workers": {...}}.
        """
        self._editor.set_section_data(SECTION_PROCESSES, data)

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def validate(self) -> List[str]:
        """Валидация секции процессов.

        Returns:
            Список ошибок.
        """
        return self._editor.validate(SECTION_PROCESSES)


__all__ = ["ProcessesSectionView"]
