"""``ManifestStore`` — единственная точка read/write ``app.yaml`` (NEW-1, Ф5.11).

Манифест — **разделяемое состояние двух процессов**: backend (сборка) и GUI
(запись выбранного рецепта) читают/пишут один ``app.yaml``. Раньше это была
конвенция (``persist_pipeline_choice`` в прототипе + ``_persist_active_recipe``
в GUI) — два независимых писателя без синхронизации → гонка read-modify-write
(потеря обновления, torn-read).

``ManifestStore`` делает контракт явным:
  - **межпроцессный лок** на sidecar ``<manifest>.lock`` сериализует read-modify-write —
    параллельные писатели не теряют правки друг друга (``fcntl.flock`` на POSIX,
    ``msvcrt.locking`` на Windows);
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

try:  # Windows — межпроцессный лок диапазона байт (аналог flock для нашей задачи).
    import msvcrt

    _HAVE_MSVCRT = True
except ImportError:  # pragma: no cover - POSIX
    _HAVE_MSVCRT = False

#: Сколько ждать межпроцессный лок на Windows, прежде чем сдаться (сек).
#: ``msvcrt.locking`` в блокирующем режиме сам сдаётся через ~10с и роняет OSError,
#: поэтому ждём сами короткими неблокирующими попытками — так ожидание предсказуемо.
_WIN_LOCK_TIMEOUT_S = 15.0

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
    локом на sidecar-файле ``<manifest>.lock``: ``fcntl.flock`` на POSIX,
    ``msvcrt.locking`` на Windows (см. :class:`_FileLock`).
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
                # nosec B506 — это ruamel YAML() в round-trip режиме
                # (RoundTripConstructor), а НЕ yaml.load из PyYAML: произвольные
                # Python-объекты не инстанцируются. Правило bandit различает их по
                # имени метода и даёт ложное срабатывание.
                data = yaml.load(f)  # nosec B506
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
    """Контекст-менеджер: threading.Lock + межпроцессный лок на sidecar-файле.

    In-process лок сериализует потоки; файловый — процессы. Реализация файлового
    зависит от платформы:

      - POSIX — ``fcntl.flock``, честные SH/EX (много читателей ИЛИ один писатель);
      - Windows — ``msvcrt.locking`` на одном байте sidecar'а. Разделяемого режима
        там нет, поэтому **SH деградирует до EX**: читатели сериализуются между
        собой. Для манифеста (редкая правка ``pipeline``) цена нулевая, а гарантия
        честная.

    Раньше ветки Windows не было вовсе: ``_HAVE_FCNTL=False`` оставлял ОДИН
    потоковый лок, который между процессами не значит ничего. Контракт в шапке
    модуля («межпроцессный лок сериализует read-modify-write») на Windows просто
    не выполнялся — параллельные писатели теряли правки, а ``os.replace`` падал
    ``PermissionError [WinError 5]``, потому что файл был открыт другим процессом.
    """

    def __init__(self, lock_path: Path, *, exclusive: bool) -> None:
        self._lock_path = lock_path
        self._exclusive = exclusive
        self._fd = None

    def _acquire_win(self) -> None:
        """Взять эксклюзивный лок байта 0 sidecar'а, дожидаясь освобождения.

        Неблокирующие попытки в цикле вместо блокирующего ``LK_LOCK``: тот сам
        сдаётся через ~10с своим числом ретраев, и получить предсказуемый дедлайн
        поверх него нельзя.
        """
        import time

        deadline = time.monotonic() + _WIN_LOCK_TIMEOUT_S
        while True:
            try:
                self._fd.seek(0)
                msvcrt.locking(self._fd.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"ManifestStore: не удалось взять межпроцессный лок "
                        f"'{self._lock_path}' за {_WIN_LOCK_TIMEOUT_S}s"
                    ) from None
                time.sleep(0.01)

    def __enter__(self) -> "_FileLock":
        _PROCESS_LOCK.acquire()
        # Всё после acquire() — под защитой: исключение в mkdir/open/lock (права,
        # ro-FS) НЕ должно оставить глобальный лок захваченным навсегда (иначе все
        # последующие операции ManifestStore в процессе виснут). release()+raise.
        try:
            if _HAVE_FCNTL:
                self._lock_path.parent.mkdir(parents=True, exist_ok=True)
                self._fd = open(self._lock_path, "a+")
                flag = fcntl.LOCK_EX if self._exclusive else fcntl.LOCK_SH
                fcntl.flock(self._fd.fileno(), flag)
            elif _HAVE_MSVCRT:
                self._lock_path.parent.mkdir(parents=True, exist_ok=True)
                self._fd = open(self._lock_path, "a+")
                self._acquire_win()
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
                try:
                    if _HAVE_FCNTL:
                        fcntl.flock(self._fd.fileno(), fcntl.LOCK_UN)
                    elif _HAVE_MSVCRT:
                        self._fd.seek(0)
                        msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                finally:
                    self._fd.close()
                    self._fd = None
        finally:
            _PROCESS_LOCK.release()
