"""SystemTopologyEditor — центральная модель конфигурации системы.

Единый объект, которым все вкладки UI пользуются для чтения и записи
конфигурации. Без Qt-зависимостей — чистая бизнес-логика.

Ключевые возможности:
- Per-section dirty tracking (каждая вкладка видит только свои изменения)
- Cross-tab queries (process_names(), camera_keys() и т.д.)
- Section subscriptions (подписки на изменения конкретной секции)
- Unified validate() с FK-проверками
"""

from __future__ import annotations

import logging
from collections import defaultdict
from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional

from multiprocess_prototype.registers.system_topology.schemas import (
    ALL_SECTIONS,
    SECTION_DISPLAYS,
    SECTION_KEYS,
    SECTION_PIPELINE,
    SECTION_PROCESSES,
    SECTION_SOURCES,
    SECTION_WIRES,
    SystemTopology,
)

logger = logging.getLogger(__name__)


class SystemTopologyEditor:
    """Центральная модель конфигурации системы.

    Хранит dict-представление SystemTopology. Каждая вкладка UI работает
    со своей секцией через Section View (Task 1.4), но данные хранятся здесь.

    Без Qt-зависимостей — тестируется чистым pytest.
    """

    def __init__(self) -> None:
        # Данные: dict-представление SystemTopology
        self._data: dict = SystemTopology().model_dump()

        # Per-section snapshots для dirty tracking
        self._snapshots: dict[str, dict] = {}

        # Подписки на изменения по секциям
        self._section_callbacks: dict[str, list[Callable]] = defaultdict(list)

        # Общие callbacks (при любом изменении)
        self._global_callbacks: list[Callable] = []

        # Lazy-cached section views
        self._section_views: dict[str, Any] = {}

        # Инициализируем snapshots — свежий editor считается чистым
        self.mark_clean()

    # ------------------------------------------------------------------
    # Загрузка / состояние
    # ------------------------------------------------------------------

    def load(self, data: dict) -> None:
        """Загрузить данные из dict (заменяет всё текущее состояние).

        Args:
            data: SystemTopology.model_dump() или аналогичный dict.
        """
        # Валидируем через Pydantic и сохраняем model_dump
        validated = SystemTopology.model_validate(data)
        self._data = validated.model_dump()
        self.mark_clean()
        logger.info(
            "SystemTopologyEditor: загружено — процессов: %d, камер: %d",
            len(self._data.get("processes", {})),
            len(self._data.get("cameras", {})),
        )

    def to_dict(self) -> dict:
        """Экспорт текущего состояния в dict (deepcopy).

        Returns:
            Полная копия данных для отправки в TopologyBridge.
        """
        return deepcopy(self._data)

    # ------------------------------------------------------------------
    # Per-section dirty tracking
    # ------------------------------------------------------------------

    def is_dirty(self, section: Optional[str] = None) -> bool:
        """Проверить наличие несохранённых изменений.

        Args:
            section: Имя секции (SECTION_PROCESSES и т.д.) или None для проверки всех.

        Returns:
            True если есть несохранённые изменения.
        """
        if section is None:
            return any(self.is_dirty(s) for s in ALL_SECTIONS)

        keys = SECTION_KEYS.get(section)
        if keys is None:
            return False

        snapshot = self._snapshots.get(section)
        if snapshot is None:
            # Snapshot не создавался — считаем dirty
            return True

        current = self._section_data_raw(section)
        return current != snapshot

    def mark_clean(self, section: Optional[str] = None) -> None:
        """Пометить секцию как «чистую» (сохранить snapshot).

        Args:
            section: Имя секции или None для всех.
        """
        sections = [section] if section else list(ALL_SECTIONS)
        for s in sections:
            self._snapshots[s] = deepcopy(self._section_data_raw(s))

    def _section_data_raw(self, section: str) -> dict:
        """Извлечь данные секции как dict (без deepcopy).

        Для SECTION_PROCESSES возвращает {"processes": {...}, "workers": {...}}.
        """
        keys = SECTION_KEYS.get(section, ())
        if len(keys) == 1:
            return self._data.get(keys[0], {})
        # Несколько ключей → объединяем в один dict
        return {k: self._data.get(k, {}) for k in keys}

    def section_data(self, section: str) -> dict:
        """Извлечь данные секции (deepcopy для безопасности).

        Args:
            section: Имя секции.

        Returns:
            Копия данных секции.
        """
        return deepcopy(self._section_data_raw(section))

    # ------------------------------------------------------------------
    # Мутации
    # ------------------------------------------------------------------

    def set_section_data(self, section: str, data: dict) -> None:
        """Заменить данные секции целиком.

        Args:
            section: Имя секции.
            data: Новые данные. Для multi-key секций — dict с ключами.
        """
        keys = SECTION_KEYS.get(section, ())
        if len(keys) == 1:
            self._data[keys[0]] = data
        else:
            for k in keys:
                if k in data:
                    self._data[k] = data[k]
        self._notify_section(section)

    def update_item(self, top_key: str, item_key: str, value: Any) -> None:
        """Обновить один элемент в конкретном top-level dict.

        Args:
            top_key: Ключ верхнего уровня ('processes', 'workers', 'cameras', ...).
            item_key: Ключ элемента внутри dict.
            value: Новое значение (dict или None для удаления).
        """
        section = self._key_to_section(top_key)
        if value is None:
            self._data.get(top_key, {}).pop(item_key, None)
        else:
            if top_key not in self._data:
                self._data[top_key] = {}
            self._data[top_key][item_key] = value
        if section:
            self._notify_section(section)

    def remove_item(self, top_key: str, item_key: str) -> Any:
        """Удалить элемент из top-level dict.

        Args:
            top_key: Ключ верхнего уровня.
            item_key: Ключ элемента.

        Returns:
            Удалённое значение или None.
        """
        section = self._key_to_section(top_key)
        removed = self._data.get(top_key, {}).pop(item_key, None)
        if section:
            self._notify_section(section)
        return removed

    def _key_to_section(self, top_key: str) -> Optional[str]:
        """Определить секцию по top-level ключу."""
        for section, keys in SECTION_KEYS.items():
            if top_key in keys:
                return section
        return None

    # ------------------------------------------------------------------
    # Подписки (cross-tab notifications)
    # ------------------------------------------------------------------

    def subscribe(self, section: str, callback: Callable) -> None:
        """Подписаться на изменения секции.

        Args:
            section: Имя секции (SECTION_PROCESSES, SECTION_SOURCES, ...).
            callback: Callable без аргументов, вызываемый при изменении.
        """
        if callback not in self._section_callbacks[section]:
            self._section_callbacks[section].append(callback)

    def unsubscribe(self, section: str, callback: Callable) -> None:
        """Отписаться от изменений секции."""
        try:
            self._section_callbacks[section].remove(callback)
        except ValueError:
            pass

    def subscribe_all(self, callback: Callable) -> None:
        """Подписаться на любое изменение (любой секции)."""
        if callback not in self._global_callbacks:
            self._global_callbacks.append(callback)

    def _notify_section(self, section: str) -> None:
        """Уведомить подписчиков секции и глобальных."""
        for cb in list(self._section_callbacks.get(section, [])):
            try:
                cb()
            except Exception:
                logger.exception("section callback failed for '%s'", section)

        for cb in list(self._global_callbacks):
            try:
                cb()
            except Exception:
                logger.exception("global callback failed")

    # ------------------------------------------------------------------
    # Cross-tab queries
    # ------------------------------------------------------------------

    def process_names(self) -> List[str]:
        """Список имён процессов (для ComboBox в других вкладках).

        Returns:
            Отсортированный по sort_order список имён.
        """
        procs = self._data.get("processes", {})
        items = sorted(procs.items(), key=lambda x: x[1].get("sort_order", 0))
        return [v.get("name", k) for k, v in items]

    def process_keys(self) -> List[str]:
        """Список ключей процессов."""
        return list(self._data.get("processes", {}).keys())

    def process_worker_names(self, proc_key: str) -> List[str]:
        """Список имён воркеров процесса.

        Args:
            proc_key: Ключ процесса.

        Returns:
            Отсортированный по sort_order список имён воркеров.
        """
        workers = self._data.get("workers", {})
        proc_workers = {
            k: v for k, v in workers.items()
            if v.get("process_ref") == proc_key
        }
        items = sorted(proc_workers.items(), key=lambda x: x[1].get("sort_order", 0))
        return [v.get("name", k) for k, v in items]

    def camera_keys(self) -> List[str]:
        """Список ключей камер (для ComboBox в Pipeline/Display)."""
        cams = self._data.get("cameras", {})
        items = sorted(cams.items(), key=lambda x: x[1].get("camera_id", 0))
        return [k for k, _ in items]

    def region_keys_for_camera(self, cam_key: str) -> List[str]:
        """Список ключей регионов для камеры.

        Args:
            cam_key: Ключ камеры.

        Returns:
            Отсортированный по sort_order список ключей.
        """
        regions = self._data.get("regions", {})
        cam_regions = {
            k: v for k, v in regions.items()
            if v.get("camera_ref") == cam_key
        }
        items = sorted(cam_regions.items(), key=lambda x: x[1].get("sort_order", 0))
        return [k for k, _ in items]

    def pipeline_output_refs(self) -> List[str]:
        """Список ссылок на выходы pipeline (для ComboBox в Display).

        Формат: camera_0, processor_0.region_0.final, ...
        """
        refs: list[str] = []
        # Камеры как базовые источники
        for cam_key, cam in self._data.get("cameras", {}).items():
            cam_id = cam.get("camera_id", 0)
            refs.append(f"camera_{cam_id}")
        # Pipeline outputs (если есть)
        for region_key in self._data.get("pipeline", {}).keys():
            refs.append(f"{region_key}.final")
        return refs

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def validate(self, section: Optional[str] = None) -> List[str]:
        """Валидация данных.

        Args:
            section: Имя секции или None для полной валидации.

        Returns:
            Список ошибок (пустой = всё ок).
        """
        errors: list[str] = []

        if section is None or section == SECTION_PROCESSES:
            errors.extend(self._validate_processes())

        if section is None or section == SECTION_SOURCES:
            errors.extend(self._validate_sources())

        if section is None or section == SECTION_WIRES:
            errors.extend(self._validate_wires())

        if section is None:
            # FK-валидация через SystemTopology
            try:
                st = SystemTopology.model_validate(self._data)
                errors.extend(st.validate_refs())
            except Exception as e:
                errors.append(f"Schema validation error: {e}")

        return errors

    def _validate_processes(self) -> List[str]:
        """Валидация секции процессов."""
        errors: list[str] = []
        procs = self._data.get("processes", {})
        workers = self._data.get("workers", {})

        for pk, p in procs.items():
            name = p.get("name", "")
            if not name:
                errors.append(f"Процесс '{pk}': имя не задано")
            if not p.get("class_path"):
                errors.append(f"Процесс '{pk}': class_path не задан")

        # Каждый процесс должен иметь хотя бы 1 protected воркер
        for pk in procs:
            proc_workers = [
                w for w in workers.values()
                if w.get("process_ref") == pk
            ]
            has_protected = any(w.get("protected") for w in proc_workers)
            if not has_protected:
                errors.append(f"Процесс '{pk}': нет protected-воркера")

        # Валидация совместимости портов plugin chain (graceful degradation)
        errors.extend(self._validate_plugin_chains(procs))

        return errors

    def _validate_plugin_chains(self, procs: dict) -> List[str]:
        """Валидация совместимости портов в цепочках плагинов.

        Graceful degradation: если PluginRegistry недоступен или плагин
        не найден — пропускаем валидацию портов (warning, не ошибка).
        В design-time реестр может быть пуст.
        """
        errors: list[str] = []

        # Импорт PluginRegistry с graceful degradation
        try:
            from multiprocess_framework.modules.process_module.plugins.registry import (
                PluginRegistry,
            )
            from multiprocess_framework.modules.process_module.plugins.port import (
                validate_chain,
            )
        except ImportError:
            logger.warning(
                "PluginRegistry недоступен — валидация портов пропущена"
            )
            return errors

        for pk, p in procs.items():
            plugins_list = p.get("plugins", [])
            if len(plugins_list) < 2:
                # Цепочка из 0-1 плагинов — нечего валидировать
                continue

            # Собираем данные портов из реестра
            chain_data: list[tuple[str, list, list]] = []
            all_found = True

            for plugin_dict in plugins_list:
                plugin_name = plugin_dict.get("plugin_name", "")
                if not plugin_name:
                    continue

                entry = PluginRegistry.get(plugin_name)
                if entry is None:
                    # Плагин не найден в реестре — registry может быть
                    # не заполнен (design-time). Пропускаем валидацию
                    # портов для всего процесса.
                    logger.warning(
                        "Процесс '%s': плагин '%s' не найден в PluginRegistry — "
                        "валидация портов пропущена",
                        pk,
                        plugin_name,
                    )
                    all_found = False
                    break

                chain_data.append((plugin_name, entry.inputs, entry.outputs))

            if not all_found or len(chain_data) < 2:
                continue

            # Все плагины найдены — проверяем совместимость цепочки
            chain_errors = validate_chain(chain_data)
            for err in chain_errors:
                errors.append(f"Процесс '{pk}': {err}")

        return errors

    def _validate_wires(self) -> List[str]:
        """Валидация секции wires — формат адресов и FK-ссылки."""
        errors: list[str] = []
        wires = self._data.get("wires", {})
        procs = self._data.get("processes", {})

        for wk, wire in wires.items():
            for field in ("source", "target"):
                addr = wire.get(field, "")
                if not addr:
                    errors.append(f"Wire '{wk}': {field} пустой")
                    continue
                parts = addr.split(".")
                if len(parts) != 3:
                    errors.append(
                        f"Wire '{wk}': {field} '{addr}' — "
                        f"ожидается 'process.plugin.port'"
                    )
                    continue
                proc_name = parts[0]
                plugin_name = parts[1]
                if proc_name not in procs:
                    errors.append(
                        f"Wire '{wk}': {field} — процесс '{proc_name}' не найден"
                    )
                else:
                    plugin_names = {
                        p.get("plugin_name", "")
                        for p in procs[proc_name].get("plugins", [])
                    }
                    if plugin_name not in plugin_names:
                        errors.append(
                            f"Wire '{wk}': {field} — плагин '{plugin_name}' "
                            f"не найден в процессе '{proc_name}'"
                        )
        return errors

    def _validate_sources(self) -> List[str]:
        """Валидация секции источников."""
        errors: list[str] = []
        cameras = self._data.get("cameras", {})

        # Уникальность camera_id
        seen_ids: dict[int, str] = {}
        for ck, c in cameras.items():
            cid = c.get("camera_id", 0)
            if cid in seen_ids:
                errors.append(
                    f"Камера '{ck}': camera_id={cid} дублирует '{seen_ids[cid]}'"
                )
            else:
                seen_ids[cid] = ck

        return errors

    # ------------------------------------------------------------------
    # Section Views (lazy creation)
    # ------------------------------------------------------------------

    @property
    def processes(self) -> Any:
        """Section View для процессов (lazy).

        Returns:
            ProcessesSectionView
        """
        if "processes" not in self._section_views:
            from multiprocess_prototype.frontend.models.sections.processes_section import (
                ProcessesSectionView,
            )
            self._section_views["processes"] = ProcessesSectionView(self)
        return self._section_views["processes"]

    @property
    def sources(self) -> Any:
        """Section View для источников (lazy).

        Returns:
            SourcesSectionView
        """
        if "sources" not in self._section_views:
            from multiprocess_prototype.frontend.models.sections.sources_section import (
                SourcesSectionView,
            )
            self._section_views["sources"] = SourcesSectionView(self)
        return self._section_views["sources"]

    @property
    def pipeline_section(self) -> Any:
        """Section View для pipeline (lazy).

        Returns:
            PipelineSectionView
        """
        if "pipeline" not in self._section_views:
            from multiprocess_prototype.frontend.models.sections.pipeline_section import (
                PipelineSectionView,
            )
            self._section_views["pipeline"] = PipelineSectionView(self)
        return self._section_views["pipeline"]

    @property
    def displays(self) -> Any:
        """Section View для дисплеев (lazy).

        Returns:
            DisplaysSectionView
        """
        if "displays" not in self._section_views:
            from multiprocess_prototype.frontend.models.sections.displays_section import (
                DisplaysSectionView,
            )
            self._section_views["displays"] = DisplaysSectionView(self)
        return self._section_views["displays"]

    @property
    def wires_section(self) -> Any:
        """Section View для межпроцессных wire-связей (lazy).

        Returns:
            WiresSectionView
        """
        if "wires" not in self._section_views:
            from multiprocess_prototype.frontend.models.sections.wires_section import (
                WiresSectionView,
            )
            self._section_views["wires"] = WiresSectionView(self)
        return self._section_views["wires"]


__all__ = ["SystemTopologyEditor"]
