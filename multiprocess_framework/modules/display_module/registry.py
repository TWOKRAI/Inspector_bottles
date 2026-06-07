"""DisplayRegistry — thread-safe singleton-реестр именованных дисплеев.

Центральное доменное хранилище ``DisplayEntry`` в framework-слое.
Singleton через ``__new__`` с double-checked locking (как ``ServiceRegistry``).
CRUD-операции под ``threading.Lock``. Персистентность — YAML через ``yaml.safe_dump``.

Пример использования::

    from multiprocess_framework.modules.display_module import DisplayRegistry, DisplayEntry

    reg = DisplayRegistry()
    reg.register(DisplayEntry(
        id="main", name="Основной", width=1280, height=720,
        format="BGR", fps_limit=30.0, ring_buffer_blocks=3,
    ))
    reg.persist(Path("displays.yaml"))

Правило слоёв:
    НИКАКИХ импортов из Services/, Plugins/, multiprocess_prototype/ —
    только stdlib + yaml + interfaces (display_module).
    ADR-DM-003: ``_cleanup_shm_channel`` только логирует предупреждение;
    фактический cleanup SHM — в prototype при следующем старте процессов.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from yaml import safe_dump, safe_load

from .interfaces import DisplayEntry, IDisplayRegistry  # noqa: F401 — реэкспорт намеренно не здесь


class DisplayRegistry:
    """Singleton-реестр дисплеев с thread-safe доступом и YAML-персистентностью.

    Гарантирует единственный экземпляр через ``__new__``.
    Все мутирующие операции защищены ``threading.Lock``.

    Attributes:
        _instance:      Единственный экземпляр класса (class-level).
        _singleton_lock: Lock для создания singleton (class-level).
        _registry:      Внутреннее хранилище ``{display_id: DisplayEntry}``.
        _lock:          Lock для CRUD-операций (instance-level).
        _logger:        Необязательный logger (паттерн logger-fallback).
    """

    _instance: DisplayRegistry | None = None
    _singleton_lock: threading.Lock = threading.Lock()

    def __new__(cls, logger=None) -> DisplayRegistry:  # type: ignore[misc]
        """Потокобезопасное создание singleton через double-checked locking.

        Args:
            logger: Необязательный logger для предупреждений и ошибок.
                    Если None — внутренние предупреждения silent.

        Returns:
            Единственный экземпляр ``DisplayRegistry``.
        """
        if cls._instance is None:
            with cls._singleton_lock:
                # Double-checked locking
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._registry: dict[str, DisplayEntry] = {}
                    instance._lock = threading.Lock()
                    instance._logger = logger
                    cls._instance = instance
        return cls._instance

    # ------------------------------------------------------------------
    # Вспомогательные методы логирования (паттерн logger-fallback)
    # ------------------------------------------------------------------

    def _log_warning(self, msg: str) -> None:
        """Логировать предупреждение, если logger доступен (иначе silent).

        Args:
            msg: Текст предупреждения.
        """
        if self._logger is not None:
            self._logger.warning(msg)

    def _log_error(self, msg: str) -> None:
        """Логировать ошибку, если logger доступен (иначе silent).

        Args:
            msg: Текст ошибки.
        """
        if self._logger is not None:
            self._logger.error(msg)

    # ------------------------------------------------------------------
    # Приватные операции
    # ------------------------------------------------------------------

    def _cleanup_shm_channel(self, display_id: str) -> None:
        """Логировать предупреждение об освобождении SHM-канала дисплея.

        Фактическое освобождение SHM-сегмента происходит в prototype-слое
        при следующем рестарте ``ProcessManagerProcess`` (ADR-DM-003 / ADR-025).
        Этот метод намеренно НЕ импортирует ``router_module`` или
        ``shared_resources_module`` — это сохраняет decoupling display_module
        от низкоуровневых IPC-компонентов.

        Args:
            display_id: Идентификатор удалённого дисплея.
        """
        self._log_warning(
            f"DisplayRegistry: дисплей '{display_id}' удалён из реестра. "
            f"SHM-канал 'display.{display_id}' будет фактически освобождён "
            f"при следующем рестарте процессов (ADR-025 / ADR-DM-003)."
        )

    # ------------------------------------------------------------------
    # Мутирующие CRUD-операции (под lock)
    # ------------------------------------------------------------------

    def register(self, entry: DisplayEntry) -> None:
        """Зарегистрировать дисплей в реестре.

        Args:
            entry: Конфигурационная запись дисплея с уникальным ``id``.

        Raises:
            ValueError: Если дисплей с таким ``entry.id`` уже зарегистрирован.
        """
        with self._lock:
            if entry.id in self._registry:
                raise ValueError(f"Дисплей уже зарегистрирован: {entry.id!r}")
            self._registry[entry.id] = entry

    def unregister(self, display_id: str) -> bool:
        """Удалить дисплей из реестра по идентификатору.

        После удаления вызывает ``_cleanup_shm_channel`` (вне lock)
        для логирования предупреждения об SHM-канале.

        Args:
            display_id: Идентификатор дисплея для удаления.

        Returns:
            True если дисплей был найден и удалён, False если не существовал.
        """
        with self._lock:
            if display_id not in self._registry:
                return False
            del self._registry[display_id]
            removed = True

        if removed:
            # Вызов вне lock — не блокируем реестр во время логирования
            self._cleanup_shm_channel(display_id)

        return True

    def clear(self) -> None:
        """Очистить реестр (для изоляции тестов).

        Не вызывает ``_cleanup_shm_channel`` — предназначено только для тестов.
        """
        with self._lock:
            self._registry.clear()

    def reload(
        self,
        entries: list[dict],
        *,
        on_orphan: Callable[[str], None] | None = None,
    ) -> None:
        """Атомарно заменить содержимое реестра новыми определениями.

        Реализует транзакционную замену метаданных дисплеев. Из каждого dict
        извлекаются ТОЛЬКО 7 SHM-полей ``DisplayEntry`` (id, name, width,
        height, format, fps_limit, ring_buffer_blocks). Render-параметры
        (fit, scale, rotate, flip, crop, position и любые другие) **игнорируются** —
        реестр generic (ADR-DM-001). SHM реестром НЕ выделяется и НЕ освобождается:
        кадр дисплея = SHM-frame ноды-продюсера в бэкенде, аллоцируется штатной
        фазой ``process.provision`` (ADR-DM-003). ``bind_displays_to_blueprint``
        — obsolete (мёртвый код, не воскрешать).

        Порядок операций (раздел 4 спеки «Дисплеи в рецепте»):
            1. Вычислить orphan-id (в реестре, но НЕ в entries).
            2. Для каждого orphan вызвать ``on_orphan(id)`` (если передан) —
               prototype подставит колбэк закрытия окон; framework НЕ знает про Qt.
            3. Для каждого orphan — ``_cleanup_shm_channel(id)`` (лог, ADR-DM-003).
            4. Очистить внутренний реестр.
            5. Зарегистрировать новые: для каждого dict взять только 7 SHM-ключей,
               построить ``DisplayEntry``, положить в реестр. Дубль id → warning,
               пропуск (без исключения).

        Идемпотентность: ``reload(same)`` = тот же реестр. ``reload(old)`` после
        ``reload(new)`` полностью восстанавливает старый набор (rollback Task 2.2).

        Args:
            entries: Список dict-определений дисплеев с границы (list[dict]).
                     Допускаются любые ключи — извлекаются только SHM-поля.
            on_orphan: Опциональный колбэк, вызываемый для каждого orphan-id
                       (дисплей был в реестре, но отсутствует в entries).
                       Prototype подставит сюда закрытие окон превью.
                       Если None — шаг уведомления пропускается, но
                       ``_cleanup_shm_channel`` всё равно вызывается.
        """
        # SHM-ключи, допустимые в DisplayEntry
        _SHM_KEYS = ("id", "name", "width", "height", "format", "fps_limit", "ring_buffer_blocks")

        # --- Шаг 1: снять snapshot + вычислить orphan под lock ---
        new_ids: set[str] = set()
        for entry_dict in entries:
            eid = entry_dict.get("id")
            if eid is not None:
                new_ids.add(eid)

        with self._lock:
            current_ids = set(self._registry.keys())

        orphan_ids = current_ids - new_ids

        # --- Шаг 2: уведомить об orphan (вне lock — колбэк может быть тяжёлым) ---
        for orphan_id in orphan_ids:
            if on_orphan is not None:
                on_orphan(orphan_id)

        # --- Шаг 3: _cleanup_shm_channel для orphan (лог, ADR-DM-003) ---
        for orphan_id in orphan_ids:
            self._cleanup_shm_channel(orphan_id)

        # --- Шаг 4-5: очистить + зарегистрировать новые (под lock, атомарно) ---
        new_registry: dict[str, DisplayEntry] = {}
        seen_ids: set[str] = set()

        for entry_dict in entries:
            if not isinstance(entry_dict, dict):
                self._log_warning(f"DisplayRegistry.reload: элемент entries не является dict: {entry_dict!r}, пропущен")
                continue

            eid = entry_dict.get("id")
            if eid is None:
                self._log_warning("DisplayRegistry.reload: запись без обязательного ключа 'id', пропущена")
                continue

            # Дубль id → warning + пропуск (паттерн displays_config_to_registry)
            if eid in seen_ids:
                self._log_warning(f"DisplayRegistry.reload: дубль id={eid!r} в entries, пропущен")
                continue
            seen_ids.add(eid)

            # Извлечь только SHM-поля, render-поля игнорируются
            filtered = {k: entry_dict[k] for k in _SHM_KEYS if k in entry_dict}

            # Добавить дефолты для опциональных полей
            filtered.setdefault("name", "")
            filtered.setdefault("width", 1280)
            filtered.setdefault("height", 720)
            filtered.setdefault("format", "BGR")
            filtered.setdefault("fps_limit", 30.0)
            filtered.setdefault("ring_buffer_blocks", 3)

            try:
                entry = DisplayEntry(**filtered)
            except TypeError as exc:
                self._log_warning(f"DisplayRegistry.reload: не удалось создать DisplayEntry из {filtered!r}: {exc}")
                continue

            new_registry[entry.id] = entry

        with self._lock:
            self._registry = new_registry

    # ------------------------------------------------------------------
    # Читающие операции (под lock для snapshot-консистентности)
    # ------------------------------------------------------------------

    def get(self, display_id: str) -> DisplayEntry | None:
        """Получить запись дисплея по идентификатору.

        Args:
            display_id: Идентификатор дисплея.

        Returns:
            ``DisplayEntry`` если найден, иначе ``None``.
        """
        with self._lock:
            return self._registry.get(display_id)

    def list(self) -> list[DisplayEntry]:
        """Вернуть список всех зарегистрированных дисплеев (копия).

        Returns:
            Копия списка ``DisplayEntry`` — безопасна для итерации
            при параллельной модификации реестра.
        """
        with self._lock:
            return list(self._registry.values())

    # ------------------------------------------------------------------
    # Персистентность (YAML)
    # ------------------------------------------------------------------

    def persist(self, path: Path) -> None:
        """Сохранить текущее состояние реестра в YAML-файл.

        Формат файла::

            displays:
              - id: main
                name: Основной
                width: 1280
                height: 720
                format: BGR
                fps_limit: 30.0
                ring_buffer_blocks: 3

        При ошибке записи — логирует ошибку через ``_log_error``,
        исключение не пробрасывает (graceful degradation).

        Args:
            path: Путь к YAML-файлу для записи (создаётся при необходимости).
        """
        with self._lock:
            entries_snapshot = list(self._registry.values())

        data = {"displays": [asdict(entry) for entry in entries_snapshot]}

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                safe_dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
        except OSError as exc:
            self._log_error(f"DisplayRegistry.persist: не удалось записать '{path}': {exc}")

    def load(self, path: Path) -> None:
        """Загрузить состояние реестра из YAML-файла.

        Заменяет текущее содержимое реестра. Если файл не существует —
        тихо возвращает (файл создастся при первом ``persist``).
        При ошибке парсинга или валидации — логирует ошибку,
        реестр остаётся без изменений.

        Десериализация выполняется без Pydantic — через dict→dataclass ``**kwargs``.

        Args:
            path: Путь к YAML-файлу для загрузки.
        """
        if not path.exists():
            # Тихое игнорирование: файл создастся при первом persist
            return

        try:
            raw = safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — все ошибки парсинга YAML
            self._log_error(f"DisplayRegistry.load: ошибка парсинга YAML '{path}': {exc}")
            return

        if not isinstance(raw, dict) or "displays" not in raw:
            self._log_error(
                f"DisplayRegistry.load: неверный формат YAML '{path}': ожидается ключ 'displays' верхнего уровня"
            )
            return

        displays_raw = raw["displays"]
        if not isinstance(displays_raw, list):
            self._log_error(f"DisplayRegistry.load: 'displays' в '{path}' должен быть списком")
            return

        new_registry: dict[str, DisplayEntry] = {}
        for item in displays_raw:
            if not isinstance(item, dict):
                self._log_error(f"DisplayRegistry.load: элемент в 'displays' не является dict: {item!r}")
                return
            try:
                entry = DisplayEntry(**item)
            except TypeError as exc:
                self._log_error(f"DisplayRegistry.load: не удалось создать DisplayEntry из {item!r}: {exc}")
                return
            new_registry[entry.id] = entry

        with self._lock:
            self._registry = new_registry

    # ------------------------------------------------------------------
    # Dunder-методы
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        with self._lock:
            return len(self._registry)

    def __contains__(self, display_id: str) -> bool:
        with self._lock:
            return display_id in self._registry

    def __repr__(self) -> str:
        with self._lock:
            count = len(self._registry)
        return f"<DisplayRegistry displays={count}>"
