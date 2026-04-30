"""persistence_manager.py — Debounced сохранение config-ветвей StateStore на диск.

Реализует PersistenceManager (владелец данных + таймер) и
PersistenceMiddleware (хук after_set / after_merge), который перехватывает
изменения дерева и помечает секции как dirty.

Маппинг prefix → файл:
    cameras.*   → state_cameras.yaml
    renderer.*  → state_renderer.yaml
    robot.*     → state_robot.yaml
    database.*  → state_database.yaml
    system.*    → state_system.yaml

Правила:
    - **.state.** в пути → пропускаем (runtime-only, не персистим)
    - **.config.**, **.regions.**, cameras.* → dirty → debounce → save
    - system.* → dirty → save_now() немедленно
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import yaml

from multiprocess_prototype.state_store.core.delta import Delta
from multiprocess_prototype.state_store.core.tree_store import TreeStore
from multiprocess_prototype.state_store.middleware.base import StateMiddleware

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Маппинг: первый сегмент пути → имя YAML-файла
# ---------------------------------------------------------------------------

_PREFIX_TO_FILE: dict[str, str] = {
    "cameras": "state_cameras.yaml",
    "renderer": "state_renderer.yaml",
    "robot": "state_robot.yaml",
    "database": "state_database.yaml",
    "system": "state_system.yaml",
}


def _resolve_file(path: str) -> str | None:
    """Определяет имя YAML-файла по точечному пути.

    Returns:
        Имя файла или None если путь не нужно сохранять.
    """
    if not path:
        return None
    prefix = path.split(".")[0]
    return _PREFIX_TO_FILE.get(prefix)


def _is_state_only(path: str) -> bool:
    """True если путь ведёт в runtime-only ветку (.state.).

    Примеры:
        "cameras.0.state.status" → True
        "cameras.0.config.fps"   → False
        "cameras.0.regions.zone" → False
    """
    return ".state." in path or path.endswith(".state")


def _is_system(path: str) -> bool:
    """True если путь начинается с 'system.'."""
    return path == "system" or path.startswith("system.")


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
    """Debounced сохранение config-ветвей StateStore на диск.

    Реализуется через PersistenceMiddleware (extends StateMiddleware).
    Подключается через store_manager.use(persistence.middleware).

    Правила:
        - **.config.** → dirty → debounce 2с → save YAML
        - **.state.** → НЕ сохранять (runtime only)
        - **.regions.** → dirty → debounce 2с → save YAML
        - system.* → save немедленно (profile switch)

    Debounce: при каждом dirty-изменении сбрасывается таймер.
    Когда таймер истекает — вызывается save.
    Threading: Timer из threading для debounce.
    """

    def __init__(
        self,
        store: TreeStore,
        data_dir: Path,
        debounce_seconds: float = 2.0,
    ) -> None:
        """
        Args:
            store: TreeStore — для чтения данных при save.
            data_dir: папка для YAML-файлов (создаётся автоматически если нет).
            debounce_seconds: задержка перед сохранением в секундах.
        """
        self._store = store
        self._data_dir = Path(data_dir)
        self._debounce_seconds = debounce_seconds

        # множество грязных файлов (state_cameras.yaml и т.д.)
        self._dirty: set[str] = set()
        # текущий debounce-таймер (один на всё — сбрасывается при каждом dirty)
        self._timer: threading.Timer | None = None
        # блокировка для _dirty и _timer
        self._lock = threading.Lock()

        # middleware-объект для подключения в pipeline
        self._middleware = PersistenceMiddleware(self)

        # создаём папку если не существует
        self._data_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("PersistenceManager: data_dir=%s, debounce=%.1fs", data_dir, debounce_seconds)

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
        Вызывается при shutdown или для system.*.
        """
        with self._lock:
            # отменяем таймер если активен
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            # берём копию dirty-списка и очищаем
            to_save = set(self._dirty)
            self._dirty.clear()

        # сохраняем вне блокировки (чтение из TreeStore и запись на диск)
        for filename in to_save:
            self._save_file(filename)

    def load(self) -> dict[str, Any]:
        """Загрузить все YAML-файлы из data_dir и вернуть merged dict.

        Результат подходит для TreeStore.merge("", result).

        Returns:
            Объединённый dict со всеми загруженными данными.
        """
        merged: dict[str, Any] = {}
        for filename in _PREFIX_TO_FILE.values():
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
        """Отменить debounce-таймер и сохранить все dirty-секции.

        Вызывать при завершении работы приложения.
        """
        logger.info("PersistenceManager: shutdown, сохраняем dirty-секции")
        self.save_now()

    # -----------------------------------------------------------------------
    # Внутренние методы
    # -----------------------------------------------------------------------

    def _on_delta(self, path: str) -> None:
        """Обработка одного изменения: определить файл, пометить dirty.

        Args:
            path: точечный путь изменённого узла.
        """
        # runtime-ветки не сохраняем
        if _is_state_only(path):
            logger.debug("PersistenceManager: skip state-path: %s", path)
            return

        # определяем целевой файл
        filename = _resolve_file(path)
        if filename is None:
            logger.debug("PersistenceManager: неизвестный prefix, skip: %s", path)
            return

        logger.debug("PersistenceManager: dirty %s ← %s", filename, path)

        if _is_system(path):
            # system.* → немедленное сохранение без debounce
            with self._lock:
                self._dirty.add(filename)
            logger.info("PersistenceManager: немедленный save для system.* (%s)", path)
            self.save_now()
        else:
            # обычные конфиги → debounce
            with self._lock:
                self._dirty.add(filename)
                self._reset_timer()

    def _reset_timer(self) -> None:
        """Сбросить (или запустить) debounce-таймер.

        Вызывается под _lock.
        """
        # отменяем предыдущий таймер
        if self._timer is not None:
            self._timer.cancel()
        # запускаем новый
        self._timer = threading.Timer(self._debounce_seconds, self._debounce_fire)
        self._timer.daemon = True  # не блокирует завершение процесса
        self._timer.start()

    def _debounce_fire(self) -> None:
        """Вызывается когда debounce-таймер истекает.

        Выполняется в отдельном потоке (threading.Timer).
        """
        logger.debug("PersistenceManager: debounce сработал, сохраняем")
        with self._lock:
            self._timer = None  # таймер уже выполнился
            to_save = set(self._dirty)
            self._dirty.clear()

        for filename in to_save:
            self._save_file(filename)

    def _save_file(self, filename: str) -> None:
        """Сохранить одну секцию дерева в YAML-файл.

        Читает данные из TreeStore и записывает только нужный prefix.

        Args:
            filename: имя YAML-файла (например 'state_cameras.yaml').
        """
        # обратный маппинг: имя файла → prefix дерева
        prefix = _file_to_prefix(filename)
        if prefix is None:
            logger.error("PersistenceManager: неизвестный файл: %s", filename)
            return

        # читаем данные из TreeStore
        try:
            data = self._store.get(prefix)
        except KeyError:
            # ветка ещё не создана в дереве — сохраняем пустой dict
            data = {}
            logger.debug("PersistenceManager: ветка '%s' не существует, save пустого dict", prefix)

        # оборачиваем в { prefix: data } — для корректного load/merge
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


def _file_to_prefix(filename: str) -> str | None:
    """Обратный маппинг: имя YAML-файла → prefix дерева.

    Returns:
        Строка-prefix или None если файл неизвестен.
    """
    for prefix, fname in _PREFIX_TO_FILE.items():
        if fname == filename:
            return prefix
    return None


def _deep_merge_inplace(target: dict, source: dict) -> None:
    """Рекурсивный merge source в target (in-place).

    Dict'ы мержатся, скаляры перезаписываются.
    """
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge_inplace(target[key], value)
        else:
            target[key] = value
