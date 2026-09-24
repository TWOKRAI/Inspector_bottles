"""Сервис рецептов: командная поверхность ``recipe.*`` на бэкенде (ADR-RCP-007).

Бэкенд — единственный владелец рецептов. Клиенты (встроенный GUI, Пульт,
``backend_ctl``) читают, сохраняют, активируют и удаляют рецепты командами;
сохранение идёт с оптимистичной ревизией ``rev``, чтобы два редактора не
затирали друг друга молча.

Хостинг — хаб (ProcessManager). Сервис Qt-free, на границе только ``dict``,
приложение он не импортирует: формат рецепта (миграции, валидация, «рецепт →
topology_dict»), применение топологии и запись «последнего активного» в
манифест приходят снаружи вызываемыми объектами (инъекция в конструктор).

Контракт (lite, ``module-contract``)
====================================

Общее для всех команд
---------------------
* Вход — ``dict`` (аргументы команды), выход — ``dict``. Обработчик НЕ бросает
  исключений наружу: любая ошибка — ответ с ``success: False``.
* Форма ошибки: ``{"success": False, "error": <code>, "message": str, ...}``.
  Коды: ``not_found``, ``conflict``, ``invalid``, ``bad_request``,
  ``io_error``, ``apply_failed``, ``active`` (только ``recipe.delete``).
* ``name`` — slug без расширения; файл рецепта — ``<recipes_dir>/<name>.yaml``.
  Pre: ``name`` — ``str`` по белому списку ``\\w[\\w.\\- ]*`` (Unicode-буквы, цифры,
  ``_``, далее ещё ``.``, ``-``, пробел; без ведущей точки, ``:``, ``/``, ``\\``), и
  файл обязан лежать прямо в ``recipes_dir``; иначе ``bad_request`` (защита от
  path traversal, включая диск Windows ``D:x``), файловая система не трогается.
* ``rev`` — НЕПРОЗРАЧНАЯ строка. Сегодня это ``sha256(байты файла).hexdigest()``,
  но клиент обязан только сравнивать на равенство. ``rev`` считается от
  ТЕКУЩИХ байтов на диске, а не от счётчика в памяти: ручная правка файла и
  любой писатель мимо ``recipe.save`` меняют ``rev`` → у редактора ``conflict``.
* Ошибки валидации — список ``[{"path": str, "message": str}]``
  (``path == ""`` — ошибка без адреса).

``recipe.list`` — ``{}``
    Pre: —.
    Post: ``{"success": True, "names": [str], "active": str | None}``;
    ``set(names)`` == множество stem-ов ``<recipes_dir>/*.yaml`` (без рекурсии),
    ``names`` отсортирован; ``active`` — от ``read_active()``. Файлы, чьё имя
    не проходит белый список ``name``, в ``names`` не попадают (``list`` и
    ``get`` согласованы: всё, что перечислено, открывается).
    Ошибка чтения каталога → ``io_error``.

``recipe.get`` — ``{"name"}``
    Post: ``{"success": True, "name", "rev", "body"}``; ``rev`` — от байтов,
    прочитанных в этом же вызове; ``body == hook.normalize(<YAML файла>)``.
    Нет файла → ``not_found``; файл не разбирается как YAML-mapping →
    ``invalid`` с ``errors``; ``OSError`` → ``io_error``.

``recipe.save`` — ``{"name", "base_rev": str | None, "body": dict}``
    ``body`` — ПОЛНЫЙ документ (не merge): ключи, которых нет в ``body``, из
    файла исчезают. ``base_rev is None`` — создание: файла быть не должно.
    Pre: ``body`` — ``dict``, ключ ``base_rev`` присутствует; иначе ``bad_request``.
    Post (успех): ``{"success": True, "name", "rev"}``; на диске лежит
    ``hook.normalize(body)``, ``rev`` == ``rev`` новых байтов; замена атомарна
    (tmp в том же каталоге + ``os.replace``) — упавшая запись оставляет старый
    файл целым, полуфайла нет.
    Post (отказ): байты файла на диске НЕ изменились.
    * ``base_rev`` не равен ``rev`` текущих байтов (или ``None`` при
      существующем файле, или строка при отсутствующем) → ``conflict`` с
      ``current_rev: str | None``.
    * ``hook.validate(hook.normalize(body))`` непуст → ``invalid`` с ``errors``.
    * ``OSError`` при записи → ``io_error``.
    Инвариант: сравнение ``rev`` и запись идут под одним локом на имя —
    из двух ``save`` с одним ``base_rev`` успешен ровно один.

``recipe.validate`` — ``{"body"}`` или ``{"name"}`` (ровно одно из двух)
    Post: ``{"success": True, "valid": bool, "errors": [...]}``,
    ``valid == (errors == [])``; ``errors = hook.validate(hook.normalize(body))``.
    Ничего не пишет. Оба ключа или ни одного → ``bad_request``;
    ``name`` без файла → ``not_found``.

``recipe.activate`` — ``{"name"}``  (СИНХРОННАЯ)
    Порядок: прочитать → ``hook.normalize`` → ``hook.validate`` →
    ``apply_topology({"topology_dict": hook.to_topology(body),
    "recipe_path": <абсолютный путь файла>})`` → при ``success`` —
    ``persist_active(<абсолютный путь>)``.
    Post (успех): ``{"success": True, "name", "apply": <ответ topology.apply>}``.
    Нет файла → ``not_found``; ошибки валидации → ``invalid`` с ``errors``; в
    обоих случаях ``apply_topology`` и ``persist_active`` не вызывались.
    Ответ ``apply_topology`` без ``success is True`` (включая debounce) →
    ``apply_failed`` с ``apply``; ``persist_active`` не вызывался, активный
    рецепт в манифесте прежний.
    ``persist_active`` бросил → ``io_error`` с ``apply`` (топология УЖЕ
    применена, манифест — нет: после рестарта поднимется прежний рецепт).
    ``recipe_path`` передаётся всегда: без него хаб ретаргетит адрес L2 по
    манифесту, то есть на старый рецепт.
    Лок имени держится только на чтении, не на ``apply_topology``.

``recipe.delete`` — ``{"name", "base_rev"?: str}``
    Post (успех): ``{"success": True, "name"}``, файла нет.
    Нет файла → ``not_found``; ``base_rev`` передан и не равен ``rev`` → ``conflict``
    с ``current_rev``; ``name == read_active()`` → ``active`` (удалять активный
    нельзя), файл цел; ``OSError`` → ``io_error``.

Комментарии YAML при ``save`` ТЕРЯЮТСЯ: файл пишется ``yaml.safe_dump``
нормализованного тела, комментарии и стиль исходника не сохраняются
(comment-preserving запись — предусловие Task 1b.3). Вне контракта: рецепт-папка
ADR-RCP-006 (сегодня единица — один файл); права на
команды (Task 1b.4); история глубже одной ревизии.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

# Имена команд — ровно как их регистрирует хаб в CommandManager.
COMMANDS: tuple[str, ...] = (
    "recipe.list",
    "recipe.get",
    "recipe.save",
    "recipe.validate",
    "recipe.activate",
    "recipe.delete",
)

ERROR_CODES: frozenset[str] = frozenset(
    {"not_found", "conflict", "invalid", "bad_request", "io_error", "apply_failed", "active"}
)

_SUFFIX = ".yaml"
_NAME_RE = re.compile(r"\w[\w.\- ]*")


@runtime_checkable
class RecipeFormatHook(Protocol):
    """Формат рецепта приложения — всё, что сервис о нём не знает.

    Инспекторская реализация живёт в прототипе (миграции v1→v2 и layout,
    ``validate_recipe_blueprint``, ``unwrap_recipe``/identity).
    """

    def normalize(self, body: dict) -> dict:
        """Привести тело к текущему формату (миграции).

        Pre: ``body`` — dict, разобранный из YAML рецепта.
        Post: новый dict текущего формата; идемпотентно —
        ``normalize(normalize(b)) == normalize(b)``; вход не мутирует.
        """
        ...

    def validate(self, body: dict) -> list[dict]:
        """Проверить нормализованное тело.

        Post: ``[{"path": str, "message": str}, ...]``; ``[]`` — валидно.
        Не бросает на невалидном теле — возвращает ошибки.
        """
        ...

    def to_topology(self, body: dict) -> dict:
        """Нормализованное валидное тело → тело, которое принимает ``topology.apply`` хоста.

        Не обязательно развёрнутая топология: если хост разворачивает рецепт сам
        (хаб Inspector извлекает ``devices:`` из сырого тела рецепта, S-25), хук
        отдаёт тело целиком — развёртка здесь срезала бы то, что хост читает.
        """
        ...


class _Reply(Exception):
    """Внутренний короткий выход: готовый ответ-ошибка. Наружу не уходит."""

    def __init__(self, error: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.reply: dict[str, Any] = {"success": False, "error": error, "message": message, **extra}


def _args(data: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(data) if isinstance(data, dict) else {}
    merged.update(kwargs)
    return merged


def _guarded(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Обработчик не бросает наружу: ``_Reply`` → его ответ, прочее → ``io_error``."""

    def wrapper(self: RecipeService, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        try:
            return fn(self, _args(data, kwargs))
        except _Reply as r:
            return r.reply
        except OSError as exc:
            return {"success": False, "error": "io_error", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 — контракт: наружу только ответ
            return {"success": False, "error": "io_error", "message": f"{type(exc).__name__}: {exc}"}

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


class RecipeService:
    """Обработчики ``recipe.*`` над каталогом рецептов.

    Args:
        recipes_dir: каталог рецептов (из манифеста, ``recipes:``), не хардкод.
        hook: формат рецепта приложения.
        apply_topology: ``args -> reply`` с семантикой команды ``topology.apply``
            (на хабе — ``_cmd_topology_apply``); ``args`` —
            ``{"topology_dict": dict, "recipe_path": str}``.
        persist_active: записать «последний активный» (на хабе —
            ``ManifestStore.set_pipeline`` через адаптер пути); получает
            абсолютный путь файла рецепта.
        read_active: имя активного рецепта или ``None``.

    Потокобезопасность: обработчики могут звать с разных потоков; CAS на
    ``save``/``delete`` — под локом на имя (в пределах одного процесса-хаба).
    """

    def __init__(
        self,
        recipes_dir: str | Path,
        hook: RecipeFormatHook,
        apply_topology: Callable[[dict[str, Any]], dict[str, Any]],
        persist_active: Callable[[Path], object],
        read_active: Callable[[], str | None],
    ) -> None:
        self._dir = Path(recipes_dir).resolve()
        self._hook = hook
        self._apply_topology = apply_topology
        self._persist_active = persist_active
        self._read_active = read_active
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def handlers(self) -> dict[str, Callable[..., dict[str, Any]]]:
        """``{имя команды: обработчик}`` для регистрации в CommandManager.

        Post: ключи == ``COMMANDS``; обработчик принимает ``data=None, **kwargs``
        (соглашение хаба ``_merge_cmd_args``).
        """
        return {cmd: getattr(self, cmd.split(".", 1)[1]) for cmd in COMMANDS}

    # --- помощники --------------------------------------------------------

    def _lock(self, name: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(name, threading.Lock())

    def _path(self, args: dict[str, Any]) -> tuple[str, Path]:
        name = args.get("name")
        # Белый список: буквы/цифры/_ (Unicode), затем ещё . - и пробел. Нет ведущей
        # точки, ``:`` (диск Windows: ``D:evil`` уходит с каталога), ``/``, ``\\``.
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise _Reply("bad_request", f"недопустимое имя рецепта: {name!r}")
        path = self._dir / f"{name}{_SUFFIX}"
        if path.resolve().parent != self._dir:  # вторая линия: симлинки и то, что белый список пропустил
            raise _Reply("bad_request", f"имя рецепта уводит из каталога: {name!r}")
        return name, path

    @staticmethod
    def _read_bytes(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def _parse(self, raw: bytes) -> dict:
        try:
            doc = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise _Reply("invalid", "файл рецепта не разбирается как YAML", errors=[{"path": "", "message": str(exc)}])
        if not isinstance(doc, dict):
            raise _Reply(
                "invalid",
                "файл рецепта — не YAML-mapping",
                errors=[{"path": "", "message": f"ожидался mapping, получено {type(doc).__name__}"}],
            )
        return self._hook.normalize(doc)

    def _load(self, name: str, path: Path) -> tuple[bytes, dict]:
        raw = self._read_bytes(path)
        if raw is None:
            raise _Reply("not_found", f"рецепт {name!r} не найден")
        return raw, self._parse(raw)

    # --- команды ----------------------------------------------------------

    @_guarded
    def list(self, args: dict[str, Any]) -> dict[str, Any]:
        """``recipe.list`` — см. модульный докстринг."""
        names = sorted(
            p.stem for p in self._dir.iterdir() if p.is_file() and p.suffix == _SUFFIX and _NAME_RE.fullmatch(p.stem)
        )
        return {"success": True, "names": names, "active": self._read_active()}

    @_guarded
    def get(self, args: dict[str, Any]) -> dict[str, Any]:
        """``recipe.get`` — см. модульный докстринг."""
        name, path = self._path(args)
        raw, body = self._load(name, path)
        return {"success": True, "name": name, "rev": compute_rev(raw), "body": body}

    @_guarded
    def save(self, args: dict[str, Any]) -> dict[str, Any]:
        """``recipe.save`` — см. модульный докстринг."""
        name, path = self._path(args)
        body = args.get("body")
        if not isinstance(body, dict) or "base_rev" not in args:
            raise _Reply("bad_request", "нужны body: dict и ключ base_rev")
        base_rev = args["base_rev"]
        normalized = self._hook.normalize(body)
        errors = self._hook.validate(normalized)
        if errors:
            raise _Reply("invalid", "рецепт не прошёл валидацию", errors=errors)
        try:
            new_bytes = yaml.safe_dump(normalized, sort_keys=False, allow_unicode=True).encode("utf-8")
        except yaml.YAMLError as exc:
            raise _Reply("bad_request", f"body не сериализуется в YAML: {exc}")

        with self._lock(name):
            current = self._read_bytes(path)
            current_rev = None if current is None else compute_rev(current)
            if base_rev != current_rev:
                raise _Reply("conflict", "рецепт изменён с момента чтения", current_rev=current_rev)
            _atomic_write(path, new_bytes)
        return {"success": True, "name": name, "rev": compute_rev(new_bytes)}

    @_guarded
    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        """``recipe.validate`` — см. модульный докстринг."""
        if ("body" in args) == ("name" in args):
            raise _Reply("bad_request", "нужно ровно одно из: body, name")
        if "body" in args:
            if not isinstance(args["body"], dict):
                raise _Reply("bad_request", "body должен быть dict")
            body = self._hook.normalize(args["body"])
        else:
            name, path = self._path(args)
            _, body = self._load(name, path)
        errors = self._hook.validate(body)
        return {"success": True, "valid": not errors, "errors": errors}

    @_guarded
    def activate(self, args: dict[str, Any]) -> dict[str, Any]:
        """``recipe.activate`` — см. модульный докстринг."""
        name, path = self._path(args)
        with self._lock(name):
            _, body = self._load(name, path)
        errors = self._hook.validate(body)
        if errors:
            raise _Reply("invalid", "рецепт не прошёл валидацию", errors=errors)
        apply = self._apply_topology({"topology_dict": self._hook.to_topology(body), "recipe_path": str(path)})
        if not isinstance(apply, dict) or apply.get("success") is not True:
            raise _Reply("apply_failed", "topology.apply отказал", apply=apply)
        try:
            self._persist_active(path)
        except Exception as exc:  # noqa: BLE001 — топология применена, манифест нет
            raise _Reply("io_error", f"топология применена, манифест не записан: {exc}", apply=apply)
        return {"success": True, "name": name, "apply": apply}

    @_guarded
    def delete(self, args: dict[str, Any]) -> dict[str, Any]:
        """``recipe.delete`` — см. модульный докстринг."""
        name, path = self._path(args)
        with self._lock(name):
            current = self._read_bytes(path)
            if current is None:
                raise _Reply("not_found", f"рецепт {name!r} не найден")
            if "base_rev" in args and args["base_rev"] != compute_rev(current):
                raise _Reply("conflict", "рецепт изменён с момента чтения", current_rev=compute_rev(current))
            if name == self._read_active():
                raise _Reply("active", f"рецепт {name!r} активен — удалять нельзя")
            path.unlink()
        return {"success": True, "name": name}


def _atomic_write(path: Path, data: bytes) -> None:
    """tmp в том же каталоге + ``os.replace``; при сбое tmp убирается, старый файл цел."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def compute_rev(raw: bytes) -> str:
    """Ревизия байтов файла (непрозрачна для клиента; сегодня sha256 hex)."""
    return hashlib.sha256(raw).hexdigest()
