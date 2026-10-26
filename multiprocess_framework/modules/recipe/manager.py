"""manager.py — RecipeManager: тонкая обёртка над RecipeEngine (CRUD + state-sync).

RecipeManager предоставляет CRUD-операции над рецептами и интегрируется
с StateProxy для синхронизации state.recipes.active.

Паттерн логирования: if self._logger: self._logger.log_info(...)
(silent fallback при logger=None).

Dict at Boundary: RecipeManager работает с dict (YAML-данные), не с Pydantic на
границе компонентов.

Comment-preserving запись (duplicate) — по умолчанию через generic-writer модуля
``recipe.yaml_io.update_yaml_preserving`` (ruamel round-trip, C3/ADR-RCP-005): writer
доменно-нейтрален и живёт в самом модуле, поэтому прототипу больше НЕ нужен
субкласс-шим с инъекцией (seam снят). Вызывающий может подменить writer через
параметр ``yaml_updater`` (напр. на plain-PyYAML в окружении без ruamel).

Запись файла рецепта по дельте (Task 1.1e, design.md §9.1/§9.2/§9.5): ``read_recipe_rev``,
``patch_recipe`` и ``save_layout``. ``before`` строит менеджер сам из байтов файла, сверка
``expected_rev`` и запись идут под одним межпроцессным ``recipe_file_lock``; раскладка
(``blueprint.metadata.{gui_positions,locked_nodes}``) пишется той же записью, что и топология.

Каноническая форма (Task 1.1f, design.md §10): ``read_canonical`` отдаёт ``N(файл)`` и ``rev`` одного чтения байтов
(``N`` — ``format_hook.normalize``); вызывающий правит свою часть канона и отдаёт его в ``patch_recipe``.
``RecipeFormatError`` — файл нельзя привести к канону.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

from .detect import is_v3_recipe
from .file_lock import recipe_file_lock
from .format import compute_rev
from .yaml_io import patch_yaml_preserving, update_yaml_preserving

if TYPE_CHECKING:  # service импортирует модули пакета — на рантайме это был бы цикл
    from .service import RecipeFormatHook


class RecipeConflict(Exception):
    """``expected_rev`` вызывающего не совпал с ревизией файла: рецепт изменён с момента чтения.

    Поля: ``slug``, ``expected_rev`` (что ждал вызывающий; ``None`` — «файла не было»), ``current_rev``
    (ревизия файла сейчас; ``None`` — файла нет). Файл не тронут.
    """

    def __init__(self, slug: str, expected_rev: str | None, current_rev: str | None) -> None:
        # args = три поля: исключение пиклится (``cls(*args)``), хотя через границу процессов оно не ходит.
        super().__init__(slug, expected_rev, current_rev)
        self.slug = slug
        self.expected_rev = expected_rev
        self.current_rev = current_rev

    def __str__(self) -> str:
        return (
            f"рецепт '{self.slug}' изменён с момента чтения: "
            f"ожидалась ревизия {self.expected_rev!r}, в файле {self.current_rev!r}"
        )


class RecipeFormatError(ValueError):
    """Файл рецепта нельзя привести к канонической форме (Task 1.1f, design.md §10).

    Причины: файл не разбирается, корень не mapping, ``format_hook.normalize`` бросил или вернул не dict,
    ``normalize`` ввёл корневой ключ, которого нет в файле (устаревшая форма — сначала миграция).
    Частичного результата нет; файл не тронут. Текст сообщения не содержит содержимого файла.
    """


class _IdentityFormatHook:
    """Формат-хук по умолчанию: форма файла как есть (``yaml.safe_load``), без миграций."""

    def normalize(self, body: dict) -> dict:
        return copy.deepcopy(body)

    def validate(self, body: dict) -> list[dict]:
        return []

    def to_topology(self, body: dict) -> dict:
        return body


def _validate_slug(slug: str) -> None:
    """Pre: slug непустой и не путь (``ValueError`` до любого обращения к файлу)."""
    if (
        not isinstance(slug, str)
        or not slug
        or slug in (".", "..")
        or "/" in slug
        or "\\" in slug
        or Path(slug).name != slug
    ):
        raise ValueError(f"slug рецепта должен быть именем без разделителей пути, получено: {slug!r}")


class RecipeManager:
    """Тонкая обёртка над RecipeEngine.

    Добавляет к базовому RecipeEngine:
    - обновление state.recipes.active через StateProxy при load/set_active
    - метод duplicate (не реализован в RecipeEngine)
    - единое место логирования мутирующих операций

    Args:
        engine: экземпляр RecipeEngine (generic из framework или доменный wrapper).
        state_proxy: опциональный StateProxy для синхронизации state.recipes.active.
                     Если None — state не обновляется.
        logger: опциональный менеджер логирования (LoggerManager или совместимый).
                Если None — логирование отключено (silent fallback).
        yaml_updater: comment-preserving writer вида ``(path, updates: dict) -> None``.
                     Если None — по умолчанию ``recipe.yaml_io.update_yaml_preserving``
                     (ruamel round-trip, сохраняет комментарии; C3/ADR-RCP-005).
                     Подмена нужна лишь в окружении без ruamel (напр. plain-PyYAML).
        yaml_patcher: писатель по дельте вида ``(path, before: dict, after: dict) -> bool``
                     (``True`` — файл записан). Если None — ``recipe.yaml_io.patch_yaml_preserving``.
        format_hook: ``RecipeFormatHook``; его ``normalize`` приводит файл и ``after`` к одной форме
                     перед построением дельты. Если None — тождество (форма файла как есть).
    """

    def __init__(
        self,
        engine: Any,
        state_proxy: Any | None = None,
        logger: Any | None = None,
        yaml_updater: Callable[[str | Path, dict], None] | None = None,
        yaml_patcher: Callable[[str | Path, dict, dict], bool] | None = None,
        format_hook: RecipeFormatHook | None = None,
    ) -> None:
        self._engine = engine
        self._state_proxy = state_proxy
        self._logger = logger
        self._yaml_updater = yaml_updater if yaml_updater is not None else update_yaml_preserving
        self._yaml_patcher = yaml_patcher if yaml_patcher is not None else patch_yaml_preserving
        self._format_hook: RecipeFormatHook = format_hook if format_hook is not None else _IdentityFormatHook()

    # ------------------------------------------------------------------
    # Вспомогательные методы логирования (silent fallback)
    # ------------------------------------------------------------------

    def _log_info(self, msg: str) -> None:
        """Логировать info. Если logger=None — молча."""
        if self._logger is not None:
            self._logger.log_info(msg)

    def _log_warning(self, msg: str) -> None:
        """Логировать warning. Если logger=None — молча."""
        if self._logger is not None:
            self._logger.log_warning(msg)

    def _log_error(self, msg: str) -> None:
        """Логировать error. Если logger=None — молча."""
        if self._logger is not None:
            self._logger.log_error(msg)

    # ------------------------------------------------------------------
    # Вспомогательные методы для state_proxy
    # ------------------------------------------------------------------

    def _update_active_in_state(self, slug: str | None) -> None:
        """Обновить state.recipes.active через StateProxy если доступен."""
        if self._state_proxy is not None:
            self._state_proxy.set("recipes.active", slug)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def list(self) -> list[str]:
        """Список имён доступных рецептов (файлов без .yaml).

        Делегирует в engine.list().

        Returns:
            Сортированный список slug'ов.
        """
        return self._engine.list()

    def load(
        self,
        slug: str,
        remap: dict[str, str] | None = None,
    ) -> list:
        """Загрузить рецепт и обновить state.recipes.active.

        Делегирует в engine.load(slug, remap).
        После успешной загрузки обновляет state_proxy если доступен.

        Args:
            slug: имя рецепта (без .yaml).
            remap: опциональный remap путей.

        Returns:
            Список Delta из engine.load().

        Raises:
            FileNotFoundError: если рецепт не найден.
        """
        deltas = self._engine.load(slug, remap)
        self._update_active_in_state(slug)
        self._log_info(f"RecipeManager: загружен рецепт '{slug}'")
        return deltas

    def save(
        self,
        slug: str,
        paths: list[str] | None = None,
    ) -> None:
        """Сохранить рецепт.

        Делегирует в engine.save(slug, paths).

        Args:
            slug: имя рецепта (без .yaml).
            paths: список config-путей для snapshot. None → default_paths движка.
        """
        self._engine.save(slug, paths)
        self._log_info(f"RecipeManager: сохранён рецепт '{slug}'")

    def delete(self, slug: str) -> bool:
        """Удалить рецепт.

        Делегирует в engine.delete(slug).
        Если удалён активный рецепт — сбрасывает state.recipes.active = None.

        Args:
            slug: имя рецепта (без .yaml).

        Returns:
            True если рецепт удалён, False если не существовал.
        """
        was_active = self._engine.get_active() == slug
        result = self._engine.delete(slug)

        if result:
            self._log_info(f"RecipeManager: удалён рецепт '{slug}'")
            if was_active:
                self._update_active_in_state(None)

        return result

    def duplicate(self, source_slug: str, new_slug: str) -> bool:
        """Дублировать рецепт под новым именем.

        Читает YAML source_slug, записывает под new_slug с обновлённым именем.

        Edge cases:
        - source_slug пустой → False без исключений
        - source_slug не существует → False
        - new_slug уже занят → False

        Args:
            source_slug: имя исходного рецепта.
            new_slug: имя нового рецепта.

        Returns:
            True если дублирование выполнено успешно, False при ошибке.
        """
        # Проверяем пустые аргументы
        if not source_slug or not new_slug:
            self._log_warning(f"RecipeManager.duplicate: пустой slug (source='{source_slug}', new='{new_slug}')")
            return False

        recipes_dir: Path = self._engine.recipes_dir
        source_path = recipes_dir / f"{source_slug}.yaml"
        target_path = recipes_dir / f"{new_slug}.yaml"

        # Проверяем что source существует
        if not source_path.exists():
            self._log_warning(f"RecipeManager.duplicate: source '{source_slug}' не найден")
            return False

        # Проверяем что target не занят
        if target_path.exists():
            self._log_warning(f"RecipeManager.duplicate: target '{new_slug}' уже существует")
            return False

        # Читаем source
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                recipe_data = yaml.safe_load(f)
        except (yaml.YAMLError, OSError) as exc:
            self._log_error(f"RecipeManager.duplicate: ошибка чтения '{source_slug}': {exc}")
            return False

        if not isinstance(recipe_data, dict):
            self._log_error(f"RecipeManager.duplicate: некорректный формат рецепта '{source_slug}'")
            return False

        # Копируем файл байт-в-байт (сохраняем комментарии), затем обновляем имя через
        # yaml_updater — comment-preserving round-trip. Куда писать имя решает единая
        # формат-стратегия detect (C3/ADR-RCP-005), а не ad-hoc проверка ключа:
        #   v3-blueprint (плоский) → top-level ``name``;
        #   config-snapshot (envelope v1/v2) → ``meta.name``.
        try:
            shutil.copy2(source_path, target_path)
            if is_v3_recipe(recipe_data):
                self._yaml_updater(target_path, {"name": new_slug})
            else:
                meta = dict(recipe_data.get("meta") or {})
                meta["name"] = new_slug
                self._yaml_updater(target_path, {"meta": meta})
        except OSError as exc:
            self._log_error(f"RecipeManager.duplicate: ошибка записи '{new_slug}': {exc}")
            target_path.unlink(missing_ok=True)
            return False

        self._log_info(f"RecipeManager: дублирован рецепт '{source_slug}' → '{new_slug}'")
        return True

    def deactivate(self) -> None:
        """Сбросить активный рецепт (публичный API вместо прямого доступа к engine).

        Вызывает engine.deactivate() (public) и обновляет state.recipes.active.
        Idempotent: если рецепт уже не активен — no-op (state обновляется на None).
        """
        self._engine.deactivate()
        self._update_active_in_state(None)
        self._log_info("RecipeManager: активный рецепт сброшен")

    def set_active(self, slug: str) -> bool:
        """Установить рецепт активным — чистый указатель, БЕЗ config/topology side-effect.

        Делегирует в engine.set_active(slug) (проверка существования + указатель)
        и обновляет state.recipes.active через StateProxy.

        НЕ вызывает load() — никакого store-replay, миграций или перезаписи
        файлов. Применение топологии (рестарт процессов) — отдельная операция
        через apply_topology.

        Args:
            slug: имя рецепта для активации.

        Returns:
            True если успешно, False если рецепт не найден.
        """
        result = self._engine.set_active(slug)
        if not result:
            self._log_warning(f"RecipeManager.set_active: рецепт '{slug}' не найден")
            return False

        self._update_active_in_state(slug)
        self._log_info(f"RecipeManager: активирован рецепт '{slug}'")
        return True

    def get_active(self) -> str | None:
        """Имя текущего активного рецепта (или None).

        Делегирует в engine.get_active().

        Returns:
            slug активного рецепта или None.
        """
        return self._engine.get_active()

    def is_dirty(self) -> bool:
        """True если config изменился после загрузки рецепта.

        Делегирует в engine.is_dirty().

        Returns:
            True если есть несохранённые изменения.
        """
        return self._engine.is_dirty()

    @property
    def recipes_dir(self) -> Path:
        """Директория с YAML-файлами рецептов.

        Делегирует в engine.recipes_dir.

        Returns:
            Path к директории рецептов.
        """
        return self._engine.recipes_dir

    def read_recipe(self, slug: str) -> dict | None:
        """Прочитать YAML рецепта по slug.

        Инкапсулирует чтение файла — presenter не работает с путями напрямую.

        Args:
            slug: имя рецепта (без .yaml).

        Returns:
            dict с данными рецепта или None если файл не найден / невалиден.
        """
        recipe_path = self._engine.recipes_dir / f"{slug}.yaml"
        if not recipe_path.exists():
            return None
        try:
            with open(recipe_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return data if isinstance(data, dict) else None
        except (yaml.YAMLError, OSError) as exc:
            self._log_error(f"RecipeManager.read_recipe: ошибка чтения '{slug}': {exc}")
            return None

    # ------------------------------------------------------------------
    # Запись по дельте под оптимистичной ревизией (Task 1.1e)
    # ------------------------------------------------------------------

    def read_recipe_rev(self, slug: str) -> tuple[dict | None, str | None]:
        """Тело рецепта и его ``rev`` одного чтения байтов (без лока).

        Pre: ``slug`` непустой, ``Path(slug).name == slug`` (иначе ``ValueError``).
        Post: файла нет -> ``(None, None)``; файл не разбирается или корень не mapping -> ``(None, rev)``;
        иначе ``(dict, rev)``. Писать по такому файлу нельзя: ``patch_recipe``/``save_layout`` дают ``ValueError``.
        """
        path = self._recipe_path(slug)
        raw = self._read_bytes(path)
        if raw is None:
            return None, None
        rev = compute_rev(raw)
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            self._log_error(f"RecipeManager.read_recipe_rev: ошибка разбора '{slug}': {exc}")
            return None, rev
        return (data if isinstance(data, dict) else None), rev

    def read_canonical(self, slug: str) -> tuple[dict | None, str | None]:
        """Каноническое тело рецепта ``N(файл)`` и ``rev`` одного чтения байтов (без лока).

        Pre: ``slug`` непустой, ``Path(slug).name == slug`` (иначе ``ValueError``).
        Post: файла нет -> ``(None, None)``; иначе ``(N(файл), rev)``: ``N`` — ``format_hook.normalize``, применён
        один раз к файлу, разобранному из тех же байтов, что дали ``rev``; ``doc`` — новый dict, вызывающий
        меняет только свою часть и отдаёт ``patch_recipe(slug, doc, expected_rev=rev)``.
        Файл не разбирается, корень не mapping, ``normalize`` бросил или вернул не dict -> ``RecipeFormatError``
        (без содержимого файла в сообщении), частичного результата нет.
        """
        path = self._recipe_path(slug)
        raw = self._read_bytes(path)
        if raw is None:
            return None, None
        rev = compute_rev(raw)
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            self._log_error(f"RecipeManager.read_canonical: ошибка разбора '{slug}': {exc}")
            raise RecipeFormatError(f"{slug}: файл рецепта не разбирается") from exc
        if not isinstance(data, dict):
            raise RecipeFormatError(f"{slug}: корень файла рецепта — не mapping")
        return self._normalize_file(slug, data), rev

    def patch_recipe(
        self,
        slug: str,
        after: dict,
        *,
        expected_rev: str | None,
        layout: tuple[dict, list] | None = None,
    ) -> str:
        """Записать ``after`` в файл рецепта дельтой ``N(файл) -> N(after)``; вернуть новый ``rev``.

        Pre: ``slug`` — имя без разделителей (``ValueError``); ``expected_rev`` — ``rev`` файла при чтении
        (``read_recipe_rev``), ``None`` — только если файла нет (иначе ``ValueError``); ``layout`` —
        ``(positions, locked_nodes)`` или ``None``, при нём ``after`` несёт ``blueprint``-mapping (``ValueError``).
        Post: сверка и запись — под одним ``recipe_file_lock``; ``expected_rev`` не совпал с файлом ->
        ``RecipeConflict``, файл не тронут. Раскладка пишется той же записью (``yaml_patcher`` вызван один раз).
        Пустая дельта (после равен файлу) -> записи нет, возврат прежнего ``rev``, ``mtime`` прежний.
        Файл не разбирается -> ``RecipeFormatError`` (подкласс ``ValueError``, без содержимого файла), байты целы.
        ``N(файл)`` вводит корневой ключ, которого нет в файле (устаревшая форма) -> ``RecipeFormatError``
        «сначала миграция», байты целы; удаление и перенос вглубь отказа не дают.
        Raises: ``RecipeLockTimeout`` — лок занят дольше ``timeout`` (5 с), файл цел.
        """
        new_rev = self._write(slug, after=after, expected_rev=expected_rev, layout=layout)
        assert new_rev is not None  # patch_recipe всегда пишет или возвращает ``rev`` существующего файла
        return new_rev

    def save_layout(
        self,
        slug: str,
        positions: dict,
        locked_nodes: list,
        *,
        expected_rev: str | None,
    ) -> str | None:
        """Записать раскладку в ``blueprint.metadata.{gui_positions,locked_nodes}``; вернуть новый ``rev``.

        Pre и сверка ``expected_rev`` — как у ``patch_recipe``.
        Post: файла нет при ``expected_rev=None`` -> записи нет, возврат ``None``, ни каталог, ни lock-файл не
        создаются; файла нет при непустом ``expected_rev`` -> ``RecipeConflict(..., current_rev=None)``;
        ``blueprint`` не mapping -> записи нет, возврат текущего ``rev``. Пустая коллекция, которой нет в файле,
        не создаётся. Раскладка из файла -> записи нет. Файл не разбирается или в устаревшей форме (см.
        ``patch_recipe``) -> ``RecipeFormatError`` (подкласс ``ValueError``), байты целы.
        Raises: ``RecipeLockTimeout`` — лок занят дольше ``timeout`` (5 с), файл цел.
        """
        return self._write(slug, after=None, expected_rev=expected_rev, layout=(positions, locked_nodes))

    def _recipe_path(self, slug: str) -> Path:
        _validate_slug(slug)
        return self._engine.recipes_dir / f"{slug}.yaml"

    def _normalize_file(self, slug: str, body: dict) -> dict:
        """``N(тело файла)``; сбой хука и не-dict в ответе — ``RecipeFormatError`` (без содержимого файла)."""
        try:
            # Копия: хук, мутирующий вход, не портит тело вызывающего.
            result = self._format_hook.normalize(copy.deepcopy(body))
        except RecipeFormatError:
            raise
        except Exception as exc:
            raise RecipeFormatError(f"{slug}: формат-хук не принял файл рецепта ({type(exc).__name__})") from exc
        if not isinstance(result, dict):
            raise RecipeFormatError(f"{slug}: формат-хук вернул {type(result).__name__}, ждали dict")
        return result

    @staticmethod
    def _read_bytes(path: Path) -> bytes | None:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def _write(
        self,
        slug: str,
        *,
        after: dict | None,
        expected_rev: str | None,
        layout: tuple[dict, list] | None,
    ) -> str | None:
        """Единственный путь записи: ``patch_recipe`` (``after`` задан) и ``save_layout`` (``after=None``).

        Лок берётся здесь один раз; помощники ниже его не берут (``recipe_file_lock`` нереентерабелен).
        """
        path = self._recipe_path(slug)
        if after is None and not path.exists():
            # save_layout без файла: писать нечего — ни каталога, ни lock-файла.
            if expected_rev is not None:
                raise RecipeConflict(slug, expected_rev, None)
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        with recipe_file_lock(path):
            raw = self._read_bytes(path)
            current_rev = None if raw is None else compute_rev(raw)
            if raw is not None and expected_rev is None:
                raise ValueError(
                    f"рецепт '{slug}' существует: запись без базовой ревизии (expected_rev=None) запрещена"
                )
            if expected_rev != current_rev:
                raise RecipeConflict(slug, expected_rev, current_rev)

            try:
                file_body = yaml.safe_load(raw) if raw is not None else None
            except yaml.YAMLError as exc:
                raise RecipeFormatError(f"{slug}: файл рецепта не разбирается — запись отменена") from exc
            before: dict = {}
            if isinstance(file_body, dict):
                file_keys = frozenset(file_body)  # до хука: проверка не зависит от того, что хук сделал с телом
                before = self._normalize_file(slug, file_body)
                introduced = sorted(str(key) for key in before if key not in file_keys)
                if introduced:
                    # Дельта по такому файлу создала бы рядом со старым ключом второй (``topology`` + ``blueprint``).
                    raise RecipeFormatError(
                        f"{slug}: файл в устаревшей форме — сначала миграция (хук вводит корневые ключи: {introduced})"
                    )
            if after is None:
                # save_layout: «после» — тот же файл с новой раскладкой; нет файла / blueprint — записи нет.
                if not isinstance(before.get("blueprint"), dict):
                    return current_rev
                target = copy.deepcopy(before)
            else:
                target = copy.deepcopy(self._format_hook.normalize(copy.deepcopy(after)))
            if layout is not None:
                if not isinstance(target.get("blueprint"), dict):
                    raise ValueError(f"раскладка рецепта '{slug}' требует blueprint-mapping в теле")
                self._apply_layout(target, *layout)

            self._yaml_patcher(path, before, target)
            new_rev = compute_rev(path.read_bytes())
        if new_rev != current_rev:
            self._log_info(f"RecipeManager: записан рецепт '{slug}'")
        return new_rev

    @staticmethod
    def _apply_layout(doc: dict, positions: dict, locked_nodes: Any) -> None:
        """Единственный писатель ``blueprint.metadata.{gui_positions,locked_nodes}`` (design.md §9.5).

        Пустую коллекцию, которой нет в файле, не создаёт (F10); ``metadata`` создаётся, только если есть
        что в нём хранить. Pre: ``doc["blueprint"]`` — mapping. Мутирует ``doc``.
        """
        blueprint = doc["blueprint"]
        pos = copy.deepcopy(positions)
        # set без порядка: сортировка нужна, иначе байты файла зависят от PYTHONHASHSEED.
        locked = (
            sorted(locked_nodes) if isinstance(locked_nodes, (set, frozenset)) else copy.deepcopy(list(locked_nodes))
        )
        metadata = blueprint.get("metadata")
        if not isinstance(metadata, dict):
            if not pos and not locked:
                return
            metadata = {}
            blueprint["metadata"] = metadata
        if pos or "gui_positions" in metadata:
            metadata["gui_positions"] = pos
        if locked or "locked_nodes" in metadata:
            metadata["locked_nodes"] = locked


__all__ = ["RecipeConflict", "RecipeFormatError", "RecipeManager"]
