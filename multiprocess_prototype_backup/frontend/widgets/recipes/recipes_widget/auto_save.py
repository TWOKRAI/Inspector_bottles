"""RecipeAutoSave — debounce-запись рецепта в YAML с ротацией версий (Phase 1, Task 1.3).

Pure-Python: использует `threading.Timer`, тестируется без PySide6. Qt-адаптер живёт в
`_recipe_panel_base.py` (Task 1.4) как отдельный класс `QtDebounceAdapter`.

Контракт:
  - `schedule()` планирует отложенный вызов `_do_save` через `config.debounce_sec`;
    повторный `schedule()` в течение дебаунс-интервала отменяет предыдущий.
  - `_do_save()` сохраняет снимок в slot через `recipe_manager.save_slot`, предварительно
    архивируя текущий YAML-файл рецептов в `<parent>/versions/<slot>.v<N>.yaml`.
  - `cancel()` отменяет pending-timer без записи.
"""

from __future__ import annotations

import contextlib
import copy
import re
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AutoSaveConfig:
    """Параметры debounce + версионирования."""

    debounce_sec: float = 1.5
    max_versions: int = 5
    versions_subdir: str = "versions"


_SAFE_SLOT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_slot(slot_id: str) -> str:
    """Заменить потенциально опасные символы, чтобы slot-id был валиден для имени файла."""
    return _SAFE_SLOT_RE.sub("_", str(slot_id)) or "slot"


class RecipeAutoSave:
    """Debounce-запись рецепта + ротация версий.

    Args:
        recipe_manager: объект с методом `save_slot(slot_id, snapshot) -> bool`;
            опционально `_data_path: Path | str` для архивации.
        slot_getter: функция → текущий `slot_id` (обычно лямбда от `RecipeSlotComboModel.current_slot_id`).
        rm_snapshot_fn: функция → snapshot-dict для записи (обычно `rm.model_dump_all()` или аналог).
        config: `AutoSaveConfig` (дефолт — debounce 1.5 с, 5 версий).
    """

    def __init__(
        self,
        recipe_manager: Any,
        slot_getter: Callable[[], str],
        rm_snapshot_fn: Callable[[], dict[str, Any]],
        config: AutoSaveConfig | None = None,
    ) -> None:
        self._mgr = recipe_manager
        self._slot_getter = slot_getter
        self._snapshot_fn = rm_snapshot_fn
        self._config = config or AutoSaveConfig()
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # ---- Public API -----------------------------------------------------

    def schedule(self) -> None:
        """Отменить предыдущий отложенный вызов и запланировать новый."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            timer = threading.Timer(self._config.debounce_sec, self._do_save)
            timer.daemon = True
            self._timer = timer
            timer.start()

    def cancel(self) -> None:
        """Отменить pending-timer без записи."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def flush(self) -> bool:
        """Выполнить сохранение немедленно (синхронно), отменив pending-timer."""
        self.cancel()
        return self._do_save()

    # ---- Save logic -----------------------------------------------------

    def _do_save(self) -> bool:
        """Архивирует текущий YAML в versions/<slot>.vN.yaml и записывает новый snapshot."""
        slot_id = str(self._slot_getter())
        snapshot = copy.deepcopy(self._snapshot_fn())
        self._rotate_versions(slot_id)
        return bool(self._mgr.save_slot(slot_id, snapshot))

    def _data_path(self) -> Path | None:
        """Путь к основному файлу рецептов (из атрибута менеджера)."""
        raw = getattr(self._mgr, "_data_path", None)
        if raw is None:
            return None
        return Path(raw)

    def _versions_dir(self) -> Path | None:
        data_path = self._data_path()
        if data_path is None:
            return None
        return data_path.parent / self._config.versions_subdir

    def _rotate_versions(self, slot_id: str) -> None:
        """Скопировать текущий YAML в `versions/<slot>.v<N>.yaml` и обрезать до max_versions."""
        data_path = self._data_path()
        if data_path is None or not data_path.is_file():
            return
        versions_dir = self._versions_dir()
        if versions_dir is None:
            return
        versions_dir.mkdir(parents=True, exist_ok=True)
        safe_slot = _sanitize_slot(slot_id)
        next_n = self._next_version_index(versions_dir, safe_slot)
        target = versions_dir / f"{safe_slot}.v{next_n}.yaml"
        shutil.copy2(data_path, target)
        self._prune_versions(versions_dir, safe_slot)

    def _next_version_index(self, versions_dir: Path, safe_slot: str) -> int:
        existing = self._list_versions(versions_dir, safe_slot)
        if not existing:
            return 1
        return max(n for n, _ in existing) + 1

    def _prune_versions(self, versions_dir: Path, safe_slot: str) -> None:
        existing = self._list_versions(versions_dir, safe_slot)
        keep = self._config.max_versions
        if len(existing) <= keep:
            return
        existing.sort(key=lambda pair: pair[0])
        for _, path in existing[: len(existing) - keep]:
            with contextlib.suppress(OSError):
                path.unlink()

    @staticmethod
    def _list_versions(versions_dir: Path, safe_slot: str) -> list[tuple[int, Path]]:
        pattern = re.compile(rf"^{re.escape(safe_slot)}\.v(\d+)\.yaml$")
        found: list[tuple[int, Path]] = []
        if not versions_dir.is_dir():
            return found
        for entry in versions_dir.iterdir():
            if not entry.is_file():
                continue
            match = pattern.match(entry.name)
            if not match:
                continue
            found.append((int(match.group(1)), entry))
        return found


class QtDebounceAdapter:
    """Qt-совместимый debouncer поверх `QTimer.singleShot` (Phase 1, Task 1.4).

    Выносит таймер из `threading.Timer` в Qt event-loop: callback вызывается в GUI-потоке,
    что безопасно для Qt-виджетов (в отличие от `threading.Timer.start()` → другой поток).

    Использование::

        adapter = QtDebounceAdapter(parent=self)
        adapter.schedule(delay_ms=1500, callback=lambda: self._auto_save.flush())
    """

    def __init__(self, parent: Any = None) -> None:
        from multiprocess_framework.modules.frontend_module.core.qt_imports import QTimer

        self._QTimer = QTimer  # cache класс, чтобы не импортировать повторно
        self._timer: Any = None
        self._parent = parent

    def schedule(self, delay_ms: int, callback: Callable[[], Any]) -> None:
        """Запланировать `callback` через `delay_ms`; отменяет предыдущий pending-таймер."""
        self.cancel()
        timer = self._QTimer(self._parent) if self._parent is not None else self._QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.start(max(0, int(delay_ms)))
        self._timer = timer

    def cancel(self) -> None:
        """Остановить pending-таймер без вызова callback."""
        if self._timer is not None:
            # Qt может бросить, если виджет уже удалён (напр. при закрытии окна).
            with contextlib.suppress(Exception):
                self._timer.stop()
            self._timer = None


__all__ = ["AutoSaveConfig", "QtDebounceAdapter", "RecipeAutoSave"]
