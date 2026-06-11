# -*- coding: utf-8 -*-
"""RecipesPresenter — бизнес-логика таба рецептов (MVP).

Pure Python, без Qt-импортов. Управляет CRUD через RecipeStore Protocol:
- load() / on_select() / on_create() / on_duplicate()
- on_delete() / on_set_active() / on_open_in_pipeline()

Task F.4: перешёл с RecipeManager на RecipeStore Protocol.
Presenter больше не трогает файловую систему — вся I/O через store.

«Dict at Boundary»: apply_topology_fn принимает и возвращает dict.
Логирование: if self._logger: self._logger.log_info(...) — silent при logger=None.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.6
      plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md Task F.4
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Callable

from multiprocess_prototype.domain.commands import ActivateRecipe
from multiprocess_prototype.domain.errors import DomainError

if TYPE_CHECKING:
    from multiprocess_prototype.domain.protocols.command_dispatcher import CommandDispatcher
    from multiprocess_prototype.domain.protocols.recipe_store import RecipeStore

    from .view import IRecipesView


def _slugify(name: str) -> str:
    """Преобразовать произвольное имя в безопасный slug.

    Правила:
    - Перевести в нижний регистр.
    - Заменить пробелы и специальные символы на '_'.
    - Оставить только [a-z0-9_-].
    - Убрать дублирующиеся '_' и '-'.
    - Обрезать до 80 символов.

    Args:
        name: произвольная строка имени.

    Returns:
        Безопасный slug или пустую строку если имя содержит только спецсимволы.
    """
    slug = name.lower()
    # Пробелы → '_'
    slug = slug.replace(" ", "_")
    # Убрать все символы не из [a-z0-9_-]
    slug = re.sub(r"[^a-z0-9_\-]", "_", slug)
    # Схлопнуть множественные '_' и '-'
    slug = re.sub(r"[_\-]{2,}", "_", slug)
    # Убрать ведущие/хвостовые '_' и '-'
    slug = slug.strip("_-")
    return slug[:80]


class RecipesPresenter:
    """Presenter для RecipesTab.

    Содержит всю бизнес-логику работы с рецептами v2 (blueprint-based CRUD).
    View получает обновления только через методы IRecipesView.
    Qt-зависимостей нет — presenter полностью тестируется без QApplication.

    Task F.4: работает через RecipeStore Protocol (не RecipeManager напрямую).

    Attributes:
        _store: RecipeStore Protocol (CRUD + raw dict + duplicate).
        _view: реализация IRecipesView (Qt-виджет или mock в тестах).
        _apply_topology_fn: callback apply_topology(blueprint) -> dict result.
                            None -> set_active работает без перезапуска процессов.
        _logger: опциональный логгер (LoggerManager или совместимый).
        _selected_slug: текущий выбранный slug в nav-списке.
    """

    def __init__(
        self,
        store: "RecipeStore",
        view: "IRecipesView",
        apply_topology_fn: Callable[[dict], dict] | None = None,
        logger: Any | None = None,
        commands: "CommandDispatcher | None" = None,
        topology_store: Any | None = None,
        persist_active_fn: Callable[[str], None] | None = None,
        upsert_devices_fn: Callable[[list[dict], str], None] | None = None,
    ) -> None:
        """Инициализировать presenter.

        Args:
            store: RecipeStore Protocol с доступом к CRUD и raw-dict I/O.
            view: реализация IRecipesView.
            apply_topology_fn: опциональный callback применения топологии
                при set_active (proxy.apply_topology → topology.apply). None ->
                только state обновляется без перезапуска процессов.
            logger: опциональный менеджер логирования (silent при None).
            commands: domain CommandDispatcher (G.6.5). При наличии активация
                рецепта идёт через dispatch(ActivateRecipe) — валидирует blueprint,
                загружает топологию рецепта в editor (Pipeline reload) и эмитит
                RecipeActivated (cross-tab linking, G.6.6). None → legacy-путь
                (только set_active, без загрузки в editor).
            upsert_devices_fn: опциональный callback для upsert устройств рецепта
                в процесс devices ДО apply_topology (Р11 device-hub).
                Сигнатура: (devices: list[dict], slug: str) -> None.
                Вызывается на worker-потоке (через RequestRunner).
                None → пропуск (устройства не upsert'ятся при активации).
        """
        self._store = store
        self._view = view
        self._apply_topology_fn = apply_topology_fn
        self._logger = logger
        self._commands = commands
        # Этап 1 pipeline-live-control: источник текущей топологии (TopologyRepository
        # с .load()) для кнопки «Сохранить» (живой граф → выбранный рецепт). None → no-op.
        self._topology_store = topology_store
        # persist активного рецепта в манифест (app.yaml). None → no-op.
        self._persist_active_fn = persist_active_fn
        # Фаза 3 device-hub: upsert устройств рецепта ДО apply_topology.
        self._upsert_devices_fn = upsert_devices_fn
        self._selected_slug: str | None = None

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
    # Загрузка списка
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Загрузить список рецептов и обновить nav в view.

        Сбрасывает выбор (set_buttons_state -> False, False).
        """
        slugs = list(self._store.list())
        self._view.refresh_list(slugs)
        self._view.set_buttons_state(False, False)
        # Показать какой рецепт сейчас активен (загружен в систему).
        self._view.show_active_recipe(self._store.get_active())
        self._log_info(f"RecipesPresenter.load: {len(slugs)} рецептов")

    # ------------------------------------------------------------------
    # Выбор рецепта
    # ------------------------------------------------------------------

    def on_select(self, slug: str | None) -> None:
        """Обработать выбор slug'а в nav-списке.

        Args:
            slug: slug выбранного рецепта или None при снятии выбора.
        """
        if slug is None:
            self._selected_slug = None
            self._view.show_recipe(None, None)
            self._view.set_buttons_state(False, False)
            return

        self._selected_slug = slug

        # Читаем raw YAML через RecipeStore Protocol
        data = self._store.read_raw(slug)
        if data is None:
            self._view.show_recipe(slug, None)
            self._view.show_error("Рецепт не найден")
            self._log_warning(f"RecipesPresenter.on_select: '{slug}' не найден или нечитаем")
            return

        active = self._store.get_active()
        self._view.show_recipe(slug, data)
        self._view.set_buttons_state(True, slug == active)
        self._log_info(f"RecipesPresenter.on_select: выбран '{slug}', active='{active}'")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def on_create(self, name: str, description: str) -> None:
        """Создать новый рецепт из имени и описания.

        Генерирует slug из name (slugify), создаёт raw dict с пустым blueprint,
        записывает через store.save_raw(), затем вызывает load() для обновления.

        Args:
            name: человекочитаемое имя рецепта.
            description: описание рецепта.
        """
        slug = _slugify(name)
        if not slug:
            self._view.show_error("Имя рецепта содержит только недопустимые символы")
            self._log_warning(f"RecipesPresenter.on_create: пустой slug из name='{name}'")
            return

        # Проверяем существование через read_raw
        if self._store.read_raw(slug) is not None:
            self._view.show_error(f"Рецепт '{slug}' уже существует")
            self._log_warning(f"RecipesPresenter.on_create: '{slug}' уже существует")
            return

        # Создаём пустой рецепт v2 с заглушечным blueprint
        recipe_data = {
            "version": 2,
            "name": name,
            "description": description,
            "blueprint": {
                "processes": [],
                "wires": [],
            },
            "active_services": [],
            "display_bindings": [],
        }

        try:
            self._store.save_raw(slug, recipe_data)
        except OSError as exc:
            self._view.show_error(f"Ошибка создания рецепта: {exc}")
            self._log_error(f"RecipesPresenter.on_create: ошибка записи '{slug}': {exc}")
            return

        self._log_info(f"RecipesPresenter.on_create: создан '{slug}' (name='{name}')")
        self.load()

    def on_duplicate(self, slug: str | None = None) -> None:
        """Дублировать рецепт с суффиксом _copy.

        Args:
            slug: slug для дублирования. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        if not target_slug:
            self._view.show_error("Рецепт не выбран")
            self._log_warning("RecipesPresenter.on_duplicate: нет выбранного рецепта")
            return

        # Auto-increment: пробуем _copy, _copy_2 ... _copy_99
        new_slug: str | None = None
        base_copy = f"{target_slug}_copy"
        if self._store.read_raw(base_copy) is None:
            new_slug = base_copy
        else:
            for n in range(2, 100):
                candidate = f"{target_slug}_copy_{n}"
                if self._store.read_raw(candidate) is None:
                    new_slug = candidate
                    break

        if new_slug is None:
            self._view.show_error("Слишком много копий рецепта")
            self._log_warning(f"RecipesPresenter.on_duplicate: все суффиксы заняты для '{target_slug}'")
            return

        result = self._store.duplicate(target_slug, new_slug)

        if result:
            self._log_info(f"RecipesPresenter.on_duplicate: '{target_slug}' -> '{new_slug}'")
            self.load()
        else:
            self._view.show_error(f"Не удалось дублировать рецепт '{target_slug}'")
            self._log_warning(f"RecipesPresenter.on_duplicate: дублирование '{target_slug}' не удалось")

    def on_delete(self, slug: str | None = None) -> None:
        """Удалить рецепт после подтверждения пользователем.

        Args:
            slug: slug для удаления. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        if not target_slug:
            self._view.show_error("Рецепт не выбран")
            self._log_warning("RecipesPresenter.on_delete: нет выбранного рецепта")
            return

        confirmed = self._view.confirm_delete(target_slug)
        if not confirmed:
            self._log_info(f"RecipesPresenter.on_delete: '{target_slug}' — удаление отменено")
            return

        self._store.delete(target_slug)

        # Сбрасываем выбор если удалили выбранный
        if self._selected_slug == target_slug:
            self._selected_slug = None

        self._log_info(f"RecipesPresenter.on_delete: удалён '{target_slug}'")
        self.load()

    def on_set_active(self, slug: str | None = None) -> None:
        """Сделать рецепт активным и применить топологию (apply_topology) если задана.

        Порядок:
        1. store.set_active(slug) -> bool.
        2. Если _apply_topology_fn задан — читает blueprint из raw dict и вызывает его.
        3. Если result["success"] -> load() + set_buttons_state(True, True).
        4. Если ошибка -> view.show_error.

        Args:
            slug: slug для активации. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        if not target_slug:
            self._view.show_error("Рецепт не выбран")
            self._log_warning("RecipesPresenter.on_set_active: нет выбранного рецепта")
            return

        # G.6.5 (Вариант A): domain dispatch ДО persist — валидирует blueprint
        # рецепта (плагины/дисплеи/циклы), загружает топологию рецепта в editor
        # (Pipeline scene reload через TopologyReplaced) и эмитит RecipeActivated
        # (cross-tab linking, G.6.6). undoable=False — переключение рецепта это
        # смена контекста, а не правка топологии (не попадает в Ctrl+Z-историю).
        # DomainError (рецепт ссылается на неизвестный плагин и т.п.) → graceful.
        if self._commands is not None:
            try:
                self._commands.dispatch(ActivateRecipe(slug=target_slug), undoable=False)
            except DomainError as exc:
                self._view.show_error(f"Не удалось активировать рецепт: {exc}")
                self._log_error(f"RecipesPresenter.on_set_active: ActivateRecipe отклонён: {exc}")
                return
            except Exception as exc:  # noqa: BLE001
                # Surface-not-mask: непредвиденные ошибки dispatch (напр. ValidationError
                # от битого/несовместимого YAML рецепта) раньше пролетали мимо узкого
                # except DomainError → «Загрузить» молча ломался. Теперь показываем.
                self._view.show_error(f"Ошибка активации рецепта '{target_slug}': {exc}")
                self._log_error(f"RecipesPresenter.on_set_active: ActivateRecipe исключение: {exc!r}")
                return

        # Активируем через RecipeStore Protocol
        success = self._store.set_active(target_slug)
        if not success:
            self._view.show_error(f"Рецепт '{target_slug}' не найден")
            self._log_warning(f"RecipesPresenter.on_set_active: set_active=False для '{target_slug}'")
            return

        self._log_info(f"RecipesPresenter.on_set_active: активирован '{target_slug}'")

        # Фаза 3 device-hub (Р11/У2): upsert устройств рецепта ДО apply_topology.
        # devices — always-on, upsert+connect подготовят устройства заранее;
        # иначе свежий robot_io стартует и форвардит в неподключённое устройство.
        if self._upsert_devices_fn is not None:
            recipe_raw_for_devices = self._store.read_raw(target_slug)
            if recipe_raw_for_devices is not None:
                from multiprocess_prototype.recipes.devices_sync import extract_recipe_devices

                recipe_devs = extract_recipe_devices(recipe_raw_for_devices)
                if recipe_devs:
                    try:
                        self._upsert_devices_fn(recipe_devs, target_slug)
                        self._log_info(
                            f"RecipesPresenter.on_set_active: upsert {len(recipe_devs)} устройств "
                            f"ДО apply_topology для '{target_slug}'"
                        )
                    except Exception as exc:  # noqa: BLE001
                        # Деградация: upsert не удался — логируем, но не блокируем активацию
                        self._log_warning(f"RecipesPresenter.on_set_active: upsert устройств не удался: {exc}")

        # Если задан apply_topology_fn — выполняем горячую замену топологии
        if self._apply_topology_fn is not None:
            # Читаем raw YAML через RecipeStore Protocol
            recipe_data = self._store.read_raw(target_slug)
            if recipe_data is None:
                self._view.show_error(f"Ошибка чтения blueprint рецепта '{target_slug}'")
                self._log_error(f"RecipesPresenter.on_set_active: не удалось прочитать '{target_slug}'")
                return

            # Task 2.2 displays-in-recipe: если рецепт v3 (top-level blueprint) —
            # передаём ПОЛНЫЙ raw-dict, backend-овский unwrap_recipe извлечёт
            # display_definitions из top-level «displays». Иначе (v2/plain) —
            # только blueprint dict (backward compat).
            if "blueprint" in recipe_data and "processes" not in recipe_data:
                # v3 рецепт (есть blueprint, нет top-level processes)
                topology_source: dict = recipe_data
            else:
                # v2/plain: извлечь blueprint
                topology_source = recipe_data.get("blueprint") or recipe_data.get("data", {}).get("blueprint") or {}

            try:
                result = self._apply_topology_fn(topology_source)
            except Exception as exc:  # noqa: BLE001
                self._view.show_error(f"Ошибка применения топологии: {exc}")
                self._log_error(f"RecipesPresenter.on_set_active: исключение apply_topology: {exc}")
                return

            if not isinstance(result, dict) or not result.get("success"):
                error_msg = (
                    result.get("error", "Ошибка применения топологии")
                    if isinstance(result, dict)
                    else "Ошибка применения топологии"
                )
                self._view.show_error(error_msg)
                self._log_error(f"RecipesPresenter.on_set_active: apply_topology failed: {error_msg}")
                return

            self._log_info(f"RecipesPresenter.on_set_active: apply_topology успешен для '{target_slug}'")

        # persist #1: записать активный slug в манифест (app.yaml → pipeline), чтобы
        # следующий старт восстановил этот рецепт. Ошибка persist не валит активацию.
        if self._persist_active_fn is not None:
            try:
                self._persist_active_fn(target_slug)
                self._log_info(f"RecipesPresenter.on_set_active: persist в манифест '{target_slug}'")
            except Exception as exc:  # noqa: BLE001
                self._log_warning(f"RecipesPresenter.on_set_active: persist не удался: {exc}")

        self.load()
        self._view.set_buttons_state(True, True)

    def on_save(self, slug: str | None = None) -> bool:
        """Сохранить текущую живую топологию в выбранный рецепт (Этап 1).

        Источник — TopologyRepository (services.topology): он SSOT текущего графа
        (Pipeline-редактор пишет в него через dispatch). Разворачиваем topology dict
        обратно в recipe-формат (blueprint + display_bindings) и пишем через store.save_raw.
        Не дублирует graph_to_blueprint: топология уже плоская, оборачиваем как рецепт.

        Args:
            slug: целевой рецепт. None → _selected_slug.

        Returns:
            True при успехе, False при ошибке / отсутствии topology_store.
        """
        target_slug = slug or self._selected_slug
        if not target_slug:
            self._view.show_error("Рецепт не выбран")
            return False
        if self._topology_store is None:
            self._view.show_error("Источник топологии недоступен")
            self._log_warning("RecipesPresenter.on_save: topology_store=None")
            return False

        topo = self._topology_store.load() or {}
        # v3-схема: blueprint top-level, displays ВНУТРИ blueprint.displays.
        blueprint = {
            "processes": topo.get("processes", []),
            "wires": topo.get("wires", []),
            "displays": topo.get("displays", []),
        }
        gui_positions = topo.get("gui_positions", {})

        raw = self._store.read_raw(target_slug)
        if raw is None:
            self._view.show_error(f"Рецепт '{target_slug}' не найден")
            return False

        try:
            # Единый нормализатор v3-raw (one source of truth): top-level blueprint,
            # без legacy data:/meta:, прочие ключи (name/version/active_services)
            # сохраняются. save_raw пишет с комментариями (ruamel round-trip).
            from multiprocess_prototype.recipes.format import normalize_recipe_v3_raw

            self._store.save_raw(target_slug, normalize_recipe_v3_raw(raw, blueprint, gui_positions))
            self._log_info(f"RecipesPresenter.on_save: топология сохранена в '{target_slug}'")
            return True
        except Exception as exc:  # noqa: BLE001
            self._view.show_error(f"Ошибка сохранения: {exc}")
            self._log_error(f"RecipesPresenter.on_save: '{target_slug}': {exc}")
            return False

    def on_open_in_pipeline(self, slug: str | None = None) -> None:
        """Открыть рецепт в Pipeline (заглушка — Task 7a).

        Args:
            slug: slug для открытия. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        # TODO: Task 7a — реализовать открытие в PipelineTab
        self._log_info(f"RecipesPresenter.on_open_in_pipeline: TBD (slug='{target_slug}')")
