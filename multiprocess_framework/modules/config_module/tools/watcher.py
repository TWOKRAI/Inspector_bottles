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

import sys
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
        log_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__()
        self._target = target_path.resolve()
        self._config = config
        self._on_reload = on_reload
        self._debounce = debounce_seconds
        self._log_error = log_error
        self._last_reload: float = 0.0

    def on_modified(self, event: FileModifiedEvent) -> None:
        """Запись НА МЕСТЕ, а также пересоздание файла (remove + write).

        ``on_created`` здесь сознательно НЕ реализован: слом-инъекция показала,
        что его удаление не убивает ни одного теста — пересоздание файла даёт
        и ``created``, и ``modified``, и второго достаточно. Обработчик, который
        нечем сломать, защищает не путь, а веру в него.
        """
        self._maybe_reload(getattr(event, "src_path", None), event.is_directory)

    def on_moved(self, event) -> None:
        """Переименование В целевой путь — основной случай атомарной записи.

        **Живой дефект 2026-07-29: правки спутника рецепта не подхватывались
        НИКОГДА.** ``write_companion`` (и многие редакторы) пишут во временный
        файл и делают ``os.replace``. Для watchdog это не модификация целевого
        пути: приходят ``created``/``modified`` по ВРЕМЕННОМУ файлу и ``moved``
        по целевому. Обработчик знал только ``on_modified``, отбрасывал события
        временного файла по несовпадению имени — и hot-reload молчал. Держалось
        это на тестах, которые писали файл на месте, то есть проверяли способ
        записи, которым система не пользуется.

        Смотрим ``dest_path``: источник — временный файл, назначение — наш конфиг.
        """
        self._maybe_reload(getattr(event, "dest_path", None), event.is_directory)

    def _maybe_reload(self, raw_path, is_directory: bool) -> None:
        """Общий фильтр всех трёх событий: наш ли это файл и не слишком ли часто.

        Дебаунс здесь обязателен именно потому, что событий теперь три: одна
        атомарная запись даёт и moved, и created, и modified — без общего
        счётчика она вызывала бы перезагрузку трижды.
        """
        if is_directory or not raw_path:
            return
        if Path(raw_path).resolve() != self._target:
            return

        now = time.monotonic()
        if now - self._last_reload < self._debounce:
            return
        self._last_reload = now

        self._reload()

    def _reload(self) -> None:
        """Перезагрузить конфиг из файла.

        Сбой не роняет процесс — но и не проходит молча. Прежде здесь стоял
        голый ``except: pass`` с объяснением «файл может быть записан частично»:
        объяснение верное для чтения, но оно накрывало и весь ``on_reload``, то
        есть отказ ПРИМЕНЕНИЯ выглядел снаружи как «правку не заметили». Живой
        разбор 2026-07-29 упёрся ровно в это: hot-reload молчал, а причина была
        не видна ниоткуда. Класс «проглоченный сбой» — следствие без причины
        хуже отсутствия следствия.
        """
        try:
            from multiprocess_framework.modules.data_schema_module.serialization.converter import DataConverter

            data = DataConverter.load_from_file(self._target)
            if not isinstance(data, dict):
                self._report(f"hot-reload: {self._target} прочитан как {type(data).__name__}, ожидался dict")
                return
            self._config.update(data)
            if self._on_reload:
                self._on_reload(self._config)
        except Exception as exc:  # noqa: BLE001 — поток watchdog'а не роняет процесс
            self._report(f"hot-reload {self._target} не применён: {exc!r}")

    def _report(self, message: str) -> None:
        """Сообщить о сбое туда, куда попросил владелец; иначе — в stderr.

        stderr выбран фолбэком осознанно: watcher живёт в config_module, ниже
        слоя логгера, и завести здесь менеджер значило бы перевернуть слои. Но
        молчать нельзя — молчащий hot-reload неотличим от работающего.
        """
        if self._log_error is not None:
            try:
                self._log_error(message)
                return
            except Exception:  # noqa: BLE001 — отказ логгера не должен маскировать исходную ошибку
                pass
        print(f"[ConfigFileWatcher] {message}", file=sys.stderr, flush=True)


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
        log_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._path = Path(path).resolve()
        self._config = config
        self._on_reload = on_reload
        self._debounce = debounce_seconds
        self._log_error = log_error
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
            log_error=self._log_error,
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
