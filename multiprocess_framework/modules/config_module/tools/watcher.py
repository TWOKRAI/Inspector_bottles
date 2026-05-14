"""
ConfigFileWatcher — hot-reload конфигов при изменении файла.

Требует ``watchdog``::

    pip install watchdog

Использование::

    from multiprocess_framework.modules.config_module.tools import ConfigFileWatcher

    cfg = Config(initial_data=load_my_config())
    watcher = ConfigFileWatcher(
        path="config.yaml",
        config=cfg,
        on_reload=lambda c: print("Reloaded!"),
    )
    watcher.start()
    # ... при изменении файла Config обновится автоматически
    watcher.stop()
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

if TYPE_CHECKING:
    from multiprocess_framework.modules.config_module.core.config import Config


class _ConfigReloadHandler(FileSystemEventHandler):
    """Internal handler: отслеживает изменения конкретного файла."""

    def __init__(
        self,
        target_path: Path,
        config: "Config",
        on_reload: Optional[Callable[["Config"], None]],
        debounce_seconds: float,
    ) -> None:
        super().__init__()
        self._target = target_path.resolve()
        self._config = config
        self._on_reload = on_reload
        self._debounce = debounce_seconds
        self._last_reload: float = 0.0

    def on_modified(self, event: FileModifiedEvent) -> None:
        if event.is_directory:
            return

        modified_path = Path(event.src_path).resolve()
        if modified_path != self._target:
            return

        now = time.monotonic()
        if now - self._last_reload < self._debounce:
            return
        self._last_reload = now

        self._reload()

    def _reload(self) -> None:
        """Перезагрузить конфиг из файла."""
        try:
            from multiprocess_framework.modules.data_schema_module.serialization.converter import DataConverter

            data = DataConverter.load_from_file(self._target)
            if isinstance(data, dict):
                self._config.update(data)
                if self._on_reload:
                    self._on_reload(self._config)
        except Exception:
            # Файл может быть частично записан — не ломаем процесс
            pass


class ConfigFileWatcher:
    """
    Hot-reload: следит за файлом, обновляет Config при изменении.

    Запускает фоновый daemon-поток через watchdog Observer.
    """

    def __init__(
        self,
        path: str | Path,
        config: "Config",
        on_reload: Optional[Callable[["Config"], None]] = None,
        debounce_seconds: float = 1.0,
    ) -> None:
        self._path = Path(path).resolve()
        self._config = config
        self._on_reload = on_reload
        self._debounce = debounce_seconds
        self._observer: Optional[Observer] = None

    def start(self) -> None:
        """Начать наблюдение в фоновом потоке."""
        if self._observer is not None:
            return

        handler = _ConfigReloadHandler(
            self._path,
            self._config,
            self._on_reload,
            self._debounce,
        )
        self._observer = Observer()
        self._observer.daemon = True
        self._observer.schedule(handler, str(self._path.parent), recursive=False)
        self._observer.start()

    def stop(self) -> None:
        """Остановить наблюдение."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

    @property
    def is_running(self) -> bool:
        """Активен ли watcher."""
        return self._observer is not None and self._observer.is_alive()
