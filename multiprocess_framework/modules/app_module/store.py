"""``ManifestStore`` — единственная точка read/write ``app.yaml`` (NEW-1, Ф5.11).

Манифест — **разделяемое состояние двух процессов**: backend (сборка) и GUI
(запись выбранного рецепта) читают/пишут один ``app.yaml``. Раньше это была
конвенция (``persist_pipeline_choice`` в прототипе + ``_persist_active_recipe``
в GUI) — два независимых писателя без синхронизации → гонка read-modify-write
(потеря обновления, torn-read).

``ManifestStore`` делает контракт явным:
  - **межпроцессный лок** (``fcntl.flock`` на sidecar ``<manifest>.lock``) сериализует
    read-modify-write — параллельные писатели не теряют правки друг друга;
  - **атомарная запись** (temp-файл + ``os.replace``) — читатель никогда не видит
    полу-записанный файл;
  - **сохранение комментариев** (ruamel round-trip) — заголовок/пояснения ``app.yaml``
    переживают запись.

Одна точка — вместо конвенции «все аккуратно пишут через одну функцию».
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

try:  # POSIX (macOS/Linux) — межпроцессный advisory-лок.
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # pragma: no cover - Windows
    _HAVE_FCNTL = False

#: In-process сериализация (flock надёжен между процессами; этот лок — между потоками).
#: Осознанный компромисс масштаба: ОДИН глобальный лок на ВСЕ сторы/файлы в процессе
#: (потоковые операции над РАЗНЫМИ app.yaml сериализуются друг с другом без нужды).
#: Для manifest'а (редкая правка pipeline) это неважно; per-path лок — кандидат 5.12.
_PROCESS_LOCK = threading.Lock()


def _make_yaml():
    """ruamel YAML в round-trip режиме (комментарии/структура сохраняются)."""
    from ruamel.yaml import YAML

    y = YAML()
    y.preserve_quotes = True
    return y


class ManifestStore:
    """Сериализованный read/write ``app.yaml`` — закрывает гонку backend↔GUI.

    Один store на путь манифеста. Потокобезопасен; между процессами защищён
    ``flock`` на sidecar-файле ``<manifest>.lock``.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_name(self._path.name + ".lock")

    @property
    def path(self) -> Path:
        return self._path

    # --- Чтение ---

    def read_raw(self) -> dict[str, Any]:
        """Прочитать манифест в raw dict (под shared-локом)."""
        with self._locked(exclusive=False):
            return self._read_unlocked()

    def load(self):
        """Загрузить и провалидировать манифест в :class:`AppManifest`.

        Тонкая обёртка над :func:`.manifest.load_manifest` — единая точка загрузки.
        """
        from .manifest import load_manifest

        with self._locked(exclusive=False):
            return load_manifest(self._path)

    # --- Запись ---

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Атомарно обновить top-level ключи манифеста (read-modify-write под EX-локом).

        Комментарии/структура сохраняются (ruamel round-trip). Если значение ключа
        уже совпадает с текущим — файл не переписывается (не дёргаем mtime/git).

        Args:
            updates: top-level ключи для записи (значение заменяется целиком).

        Returns:
            Итоговый top-level dict манифеста после применения (для логов/проверок).
        """
        with self._locked(exclusive=True):
            data = self._read_commented_unlocked()
            changed = False
            for key, value in updates.items():
                if data.get(key) != value:
                    data[key] = value
                    changed = True
            if changed:
                self._atomic_write_unlocked(data)
            return {k: data[k] for k in data}

    def set_pipeline(self, value: str) -> str:
        """Записать активный pipeline (``pipeline:``) — самая частая правка (backend↔GUI).

        Returns:
            Записанное (или уже бывшее) значение ``pipeline``.
        """
        result = self.update({"pipeline": value})
        return result.get("pipeline", value)

    # --- Внутреннее ---

    def _read_unlocked(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        import yaml

        with open(self._path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _read_commented_unlocked(self):
        yaml = _make_yaml()
        if self._path.exists():
            with self._path.open("r", encoding="utf-8") as f:
                data = yaml.load(f)
            if data is not None:
                return data
        from ruamel.yaml.comments import CommentedMap

        return CommentedMap()

    def _atomic_write_unlocked(self, data) -> None:
        yaml = _make_yaml()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + f".tmp.{os.getpid()}")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                yaml.dump(data, f)
            # Сохранить права оригинала: os.replace берёт mode temp-файла (0644 из
            # umask), поэтому копируем режим существующего app.yaml перед подменой.
            if self._path.exists():
                os.chmod(tmp, self._path.stat().st_mode)
            os.replace(tmp, self._path)  # атомарная подмена — читатель не видит полу-файл
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def _locked(self, *, exclusive: bool):
        return _FileLock(self._lock_path, exclusive=exclusive)


class _FileLock:
    """Контекст-менеджер: threading.Lock + ``fcntl.flock`` на sidecar-файле.

    In-process лок сериализует потоки; ``flock`` — процессы. На платформах без
    ``fcntl`` (Windows) деградирует до потокового лока (best-effort).
    """

    def __init__(self, lock_path: Path, *, exclusive: bool) -> None:
        self._lock_path = lock_path
        self._exclusive = exclusive
        self._fd = None

    def __enter__(self) -> "_FileLock":
        _PROCESS_LOCK.acquire()
        # Всё после acquire() — под защитой: исключение в mkdir/open/flock (права,
        # ro-FS) НЕ должно оставить глобальный лок захваченным навсегда (иначе все
        # последующие операции ManifestStore в процессе виснут). release()+raise.
        try:
            if _HAVE_FCNTL:
                self._lock_path.parent.mkdir(parents=True, exist_ok=True)
                self._fd = open(self._lock_path, "a+")
                flag = fcntl.LOCK_EX if self._exclusive else fcntl.LOCK_SH
                fcntl.flock(self._fd.fileno(), flag)
        except BaseException:
            if self._fd is not None:
                self._fd.close()
                self._fd = None
            _PROCESS_LOCK.release()
            raise
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            if self._fd is not None:
                fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                self._fd.close()
                self._fd = None
        finally:
            _PROCESS_LOCK.release()
