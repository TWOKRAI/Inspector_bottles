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
  Pre: ``name`` — непустая ``str`` без ``/``, ``\\`` и ``..``; иначе
  ``bad_request`` (защита от path traversal), файловая система не трогается.
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
    ``names`` отсортирован; ``active`` — от ``read_active()``.
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

Вне контракта: сохранение комментариев YAML при ``save`` (best effort, не
гарантия); рецепт-папка ADR-RCP-006 (сегодня единица — один файл); права на
команды (Task 1b.4); история глубже одной ревизии.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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
        """Нормализованное валидное тело → ``topology_dict`` для ``topology.apply``."""
        ...


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
        raise NotImplementedError

    def handlers(self) -> dict[str, Callable[..., dict[str, Any]]]:
        """``{имя команды: обработчик}`` для регистрации в CommandManager.

        Post: ключи == ``COMMANDS``; обработчик принимает ``data=None, **kwargs``
        (соглашение хаба ``_merge_cmd_args``).
        """
        raise NotImplementedError

    def list(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """``recipe.list`` — см. модульный докстринг."""
        raise NotImplementedError

    def get(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """``recipe.get`` — см. модульный докстринг."""
        raise NotImplementedError

    def save(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """``recipe.save`` — см. модульный докстринг."""
        raise NotImplementedError

    def validate(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """``recipe.validate`` — см. модульный докстринг."""
        raise NotImplementedError

    def activate(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """``recipe.activate`` — см. модульный докстринг."""
        raise NotImplementedError

    def delete(self, data: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        """``recipe.delete`` — см. модульный докстринг."""
        raise NotImplementedError


def compute_rev(raw: bytes) -> str:
    """Ревизия байтов файла (непрозрачна для клиента; сегодня sha256 hex)."""
    raise NotImplementedError
