"""persistence_manager.py — Debounced сохранение веток StateStore на диск.

Реализует PersistenceManager (владелец данных + таймер) и
PersistenceMiddleware (хук after_set / after_merge), который перехватывает
изменения дерева и помечает секции как dirty.

ADR-SS-011 (2026-05-07): file_mapping и предикаты пропуска/немедленного save
вынесены в параметры конструктора. Раньше зашитые prefix (cameras/renderer/...)
и предикаты `.state.` / `system.*` нарушали ADR-SS-003 — фреймворк не должен
знать про доменные ветви. Теперь приложение конфигурирует их явно.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable

import yaml

from ..core.delta import Delta
from ..core.tree_store import TreeStore
from ..middleware.base import StateMiddleware

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Типы предикатов
# ---------------------------------------------------------------------------

PathPredicate = Callable[[str], bool]


# ---------------------------------------------------------------------------
# PersistenceMiddleware — хук после каждого set/merge
# ---------------------------------------------------------------------------


class PersistenceMiddleware(StateMiddleware):
    """Middleware, перехватывающий изменения и помечающий секции как dirty.

    Передаёт управление в PersistenceManager для расчёта debounce и сохранения.
    """

    def __init__(self, manager: "PersistenceManager") -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "persistence"

    def after_set(self, delta: Delta, context: dict) -> None:
        """Вызывается после каждого успешного TreeStore.set()."""
        self._manager._on_delta(delta.path)

    def after_merge(self, deltas: list[Delta], context: dict) -> None:
        """Вызывается после каждого успешного TreeStore.merge()."""
        for delta in deltas:
            self._manager._on_delta(delta.path)


# ---------------------------------------------------------------------------
# PersistenceManager — владелец логики persist
# ---------------------------------------------------------------------------


class PersistenceManager:
    """Debounced сохранение секций StateStore на диск (доменно-нейтральный).

    Поведение полностью определяется тремя параметрами конструктора:

    * ``file_mapping``: dict ``{prefix: filename}`` — маппинг первого сегмента
      пути в имя YAML-файла. Прикладной код задаёт собственные ветви.
    * ``skip_predicate``: callable, возвращающий True для путей, которые
      сохранять НЕ нужно (например, runtime-only ``*.state.*``). По умолчанию —
      ничего не пропускать.
    * ``immediate_predicate``: callable для путей, которые требуют сохранения
      без debounce (например, ``system.*`` для смены профиля). По умолчанию —
      все пути идут через debounce.

    Подключается через ``store_manager.use(manager.middleware)``.

    Пример конфигурации (приложение, не фреймворк)::

        manager = PersistenceManager(
            store=tree,
            data_dir=Path("/var/state"),
            file_mapping={
                "cameras":  "state_cameras.yaml",
                "renderer": "state_renderer.yaml",
                "system":   "state_system.yaml",
            },
            skip_predicate=lambda p: ".state." in p or p.endswith(".state"),
            immediate_predicate=lambda p: p == "system" or p.startswith("system."),
        )

    Threading: ``threading.Timer`` для debounce.
    """

    def __init__(
        self,
        store: TreeStore,
        data_dir: Path,
        debounce_seconds: float = 2.0,
        file_mapping: dict[str, str] | None = None,
        skip_predicate: PathPredicate | None = None,
        immediate_predicate: PathPredicate | None = None,
    ) -> None:
        """
        Args:
            store: TreeStore — для чтения данных при save.
            data_dir: папка для YAML-файлов (создаётся автоматически если нет).
            debounce_seconds: задержка перед сохранением в секундах.
            file_mapping: ``{prefix: filename}``. ``None`` или пустой dict —
                сохранять нечего (любой путь даёт «неизвестный prefix»).
            skip_predicate: callable(path) → True для путей, которые
                пропускать. ``None`` — ничего не пропускать.
            immediate_predicate: callable(path) → True для путей, требующих
                save без debounce. ``None`` — все пути идут через debounce.
        """
        self._store = store
        self._data_dir = Path(data_dir)
        self._debounce_seconds = debounce_seconds
        self._file_mapping: dict[str, str] = dict(file_mapping or {})
        # Обратный маппинг для save: filename → prefix
        self._reverse_mapping: dict[str, str] = {
            fname: prefix for prefix, fname in self._file_mapping.items()
        }
        self._skip = skip_predicate
        self._immediate = immediate_predicate

        self._dirty: set[str] = set()
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

        self._middleware = PersistenceMiddleware(self)

        self._data_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(
            "PersistenceManager: data_dir=%s, debounce=%.1fs, prefixes=%s",
            data_dir,
            debounce_seconds,
            sorted(self._file_mapping.keys()),
        )

    # -----------------------------------------------------------------------
    # Публичный API
    # -----------------------------------------------------------------------

    @property
    def middleware(self) -> StateMiddleware:
        """Middleware для подключения в pipeline через store_manager.use()."""
        return self._middleware

    @property
    def is_dirty(self) -> bool:
        """True если есть несохранённые изменения."""
        with self._lock:
            return bool(self._dirty)

    def save_now(self) -> None:
        """Принудительный save всех dirty-секций.

        Отменяет текущий debounce-таймер и сохраняет немедленно.
        Вызывается при shutdown или для immediate-путей.
        """
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            to_save = set(self._dirty)
            self._dirty.clear()

        for filename in to_save:
            self._save_file(filename)

    def load(self) -> dict[str, Any]:
        """Загрузить все YAML-файлы из ``data_dir`` и вернуть merged dict.

        Берёт только файлы из ``file_mapping`` (отсекает чужие YAML рядом).
        Результат подходит для ``TreeStore.merge("", result)``.

        Returns:
            Объединённый dict со всеми загруженными данными.
        """
        merged: dict[str, Any] = {}
        for filename in self._file_mapping.values():
            filepath = self._data_dir / filename
            if not filepath.exists():
                logger.debug("PersistenceManager: файл не найден, пропуск: %s", filepath)
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict):
                    _deep_merge_inplace(merged, data)
                    logger.debug("PersistenceManager: загружен %s", filename)
                elif data is not None:
                    logger.warning(
                        "PersistenceManager: файл %s содержит не-dict данные: %s",
                        filename,
                        type(data).__name__,
                    )
            except yaml.YAMLError as exc:
                logger.error("PersistenceManager: ошибка разбора YAML %s: %s", filename, exc)
            except OSError as exc:
                logger.error("PersistenceManager: ошибка чтения %s: %s", filename, exc)

        return merged

    def shutdown(self) -> None:
        """Отменить debounce-таймер и сохранить все dirty-секции."""
        logger.info("PersistenceManager: shutdown, сохраняем dirty-секции")
        self.save_now()

    # -----------------------------------------------------------------------
    # Внутренние методы
    # -----------------------------------------------------------------------

    def _resolve_file(self, path: str) -> str | None:
        """Имя YAML-файла для пути или None если prefix не настроен."""
        if not path:
            return None
        prefix = path.split(".")[0]
        return self._file_mapping.get(prefix)

    def _on_delta(self, path: str) -> None:
        """Обработка одного изменения: определить файл, пометить dirty."""
        # 1. Пропускаемые ветви (например, runtime *.state.*)
        if self._skip is not None and self._skip(path):
            logger.debug("PersistenceManager: skip по skip_predicate: %s", path)
            return

        # 2. Найти целевой файл по mapping
        filename = self._resolve_file(path)
        if filename is None:
            logger.debug("PersistenceManager: prefix не в file_mapping, skip: %s", path)
            return

        logger.debug("PersistenceManager: dirty %s ← %s", filename, path)

        # 3. Решить — debounce или immediate
        if self._immediate is not None and self._immediate(path):
            with self._lock:
                self._dirty.add(filename)
            logger.info("PersistenceManager: immediate save для пути %s", path)
            self.save_now()
        else:
            with self._lock:
                self._dirty.add(filename)
                self._reset_timer()

    def _reset_timer(self) -> None:
        """Сбросить (или запустить) debounce-таймер. Вызывается под _lock."""
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(self._debounce_seconds, self._debounce_fire)
        self._timer.daemon = True
        self._timer.start()

    def _debounce_fire(self) -> None:
        """Колбэк debounce-таймера. Выполняется в отдельном потоке."""
        logger.debug("PersistenceManager: debounce сработал, сохраняем")
        with self._lock:
            self._timer = None
            to_save = set(self._dirty)
            self._dirty.clear()

        for filename in to_save:
            self._save_file(filename)

    def _save_file(self, filename: str) -> None:
        """Сохранить одну секцию дерева в YAML-файл."""
        prefix = self._reverse_mapping.get(filename)
        if prefix is None:
            logger.error("PersistenceManager: filename вне file_mapping: %s", filename)
            return

        try:
            data = self._store.get(prefix)
        except KeyError:
            data = {}
            logger.debug(
                "PersistenceManager: ветка '%s' не существует, save пустого dict",
                prefix,
            )

        payload = {prefix: data}

        filepath = self._data_dir / filename
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                yaml.dump(
                    payload,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=True,
                )
            logger.info("PersistenceManager: сохранён %s", filepath)
        except OSError as exc:
            logger.error("PersistenceManager: ошибка записи %s: %s", filepath, exc)


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _deep_merge_inplace(target: dict, source: dict) -> None:
    """Рекурсивный merge source в target (in-place).

    Dict'ы мержатся, скаляры перезаписываются.
    """
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge_inplace(target[key], value)
        else:
            target[key] = value
