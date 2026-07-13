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

from multiprocess_framework.modules.recipe.detect import has_top_level_blueprint
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
        _apply_topology_fn: async callback применения топологии:
                            (blueprint: dict, on_result: Callable[[dict], None]) -> None.
                            Реальный результат PM приходит в on_result (Qt main-thread).
                            None -> set_active работает без перезапуска процессов.
        _logger: опциональный логгер (LoggerManager или совместимый).
        _selected_slug: текущий выбранный slug в nav-списке.
        _apply_in_flight: True пока идёт async-применение (guard от двойного клика).
    """

    def __init__(
        self,
        store: "RecipeStore",
        view: "IRecipesView",
        apply_topology_fn: Callable[[dict, Callable[[dict], None]], Any] | None = None,
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
            apply_topology_fn: опциональный async-callback применения топологии
                при set_active: ``fn(blueprint, on_result)`` — request/response
                через proxy.apply_topology → topology.apply; реальный результат
                PM приходит в on_result в Qt main-thread (command-result-bridge).
                None -> только state обновляется без перезапуска процессов.
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
        # Task 2.1 topology-switch-hardening: guard от повторного apply, пока
        # результат предыдущего не пришёл (backend дебаунсит МОЛЧА — здесь честно).
        self._apply_in_flight = False

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
        """Сделать рецепт активным и применить топологию к живому backend.

        Порядок (Task 2.1 topology-switch-hardening — async request/response):
        1. store.set_active(slug) → dispatch(ActivateRecipe) → upsert устройств.
        2. Если _apply_topology_fn задан — отправляет blueprint асинхронно;
           РЕАЛЬНЫЙ результат PM приходит в _on_apply_result (Qt main-thread).
           На время полёта view.set_switch_busy(True) + guard от второго клика.
        3. По success → persist в манифест + load() (см. _finalize_activation).
           По провалу (rolled_back / debounced / error) → откат slug'а,
           компенсирующий ActivateRecipe(prev), БЕЗ persist (_rollback_activation).
        4. Без _apply_topology_fn — финализация сразу (нет живого backend).

        Args:
            slug: slug для активации. Если None — использует _selected_slug.
        """
        target_slug = slug or self._selected_slug
        if not target_slug:
            self._view.show_error("Рецепт не выбран")
            self._log_warning("RecipesPresenter.on_set_active: нет выбранного рецепта")
            return

        if self._apply_in_flight:
            self._view.show_error("Переключение рецепта уже выполняется — дождитесь завершения")
            self._log_warning("RecipesPresenter.on_set_active: apply в полёте — повторный запрос отклонён")
            return

        # FIX (load-display-rebind): store.set_active ОБЯЗАН выполниться ДО
        # dispatch(ActivateRecipe). dispatch синхронно публикует RecipeActivated, на
        # который подписан _rebuild_displays (app.py) — а тот читает recipe_manager.get_active().
        # Раньше dispatch шёл первым → _rebuild_displays собирал слоты/routing дисплеев по
        # СТАРОМУ активному рецепту (корень «кривой» загрузки: кадры нового рецепта летели
        # не в тот слот). Теперь: set_active (engine._active_name обновлён, событий не шлёт)
        # → dispatch (валидирует blueprint, грузит editor-топологию, эмитит TopologyReplaced
        # + RecipeActivated уже с НОВЫМ активным). При отклонении валидации — откат slug.
        # undoable=False: переключение рецепта = смена контекста, не правка (вне Ctrl+Z).
        prev_active = self._store.get_active()
        success = self._store.set_active(target_slug)
        if not success:
            self._view.show_error(f"Рецепт '{target_slug}' не найден")
            self._log_warning(f"RecipesPresenter.on_set_active: set_active=False для '{target_slug}'")
            return

        if self._commands is not None:
            try:
                self._commands.dispatch(ActivateRecipe(slug=target_slug), undoable=False)
            except DomainError as exc:
                self._store.set_active(prev_active)  # откат: невалидный рецепт не остаётся активным
                self._view.show_error(f"Не удалось активировать рецепт: {exc}")
                self._log_error(f"RecipesPresenter.on_set_active: ActivateRecipe отклонён: {exc}")
                return
            except Exception as exc:  # noqa: BLE001
                # Surface-not-mask: непредвиденные ошибки dispatch (напр. ValidationError
                # от битого/несовместимого YAML рецепта) раньше пролетали мимо узкого
                # except DomainError → «Загрузить» молча ломался. Теперь показываем + откат.
                self._store.set_active(prev_active)
                self._view.show_error(f"Ошибка активации рецепта '{target_slug}': {exc}")
                self._log_error(f"RecipesPresenter.on_set_active: ActivateRecipe исключение: {exc!r}")
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

        # Если задан apply_topology_fn — горячая замена через async request/response
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
            if has_top_level_blueprint(recipe_data) and "processes" not in recipe_data:
                # v3 рецепт (есть blueprint, нет top-level processes)
                topology_source: dict = recipe_data
            else:
                # v2/plain: извлечь blueprint
                topology_source = recipe_data.get("blueprint") or recipe_data.get("data", {}).get("blueprint") or {}

            self._apply_in_flight = True
            self._view.set_switch_busy(True)
            self._log_info(f"RecipesPresenter.on_set_active: topology.apply отправлен для '{target_slug}' (async)")
            try:
                self._apply_topology_fn(
                    topology_source,
                    lambda result: self._on_apply_result(target_slug, prev_active, result),
                )
            except Exception as exc:  # noqa: BLE001
                self._apply_in_flight = False
                self._view.set_switch_busy(False)
                self._log_error(f"RecipesPresenter.on_set_active: исключение отправки apply: {exc}")
                self._rollback_activation(prev_active, f"Ошибка применения топологии: {exc}")
            # persist/load — ТОЛЬКО в _on_apply_result по подтверждённому success
            return

        # Нет живого backend (apply_topology_fn=None) — финализируем сразу
        self._finalize_activation(target_slug)

    # ------------------------------------------------------------------
    # Активация: результат backend + финализация/откат (Task 2.1)
    # ------------------------------------------------------------------

    def _on_apply_result(self, target_slug: str, prev_active: str | None, result: dict | None) -> None:
        """Обработать РЕАЛЬНЫЙ результат PM (command-result-bridge, Qt main-thread).

        Раньше здесь был optimistic-ack fire-and-forget: GUI активировал slug и
        персистил рецепт в app.yaml, даже если backend откатился (rolled_back)
        или молча съел запрос (debounce) — состояние GUI расходилось с backend.

        Args:
            target_slug: рецепт, который применялся.
            prev_active: активный slug ДО активации (для отката).
            result: dict-ответ PM (success/rolled_back/debounced/error) или None.
        """
        self._apply_in_flight = False
        self._view.set_switch_busy(False)

        if isinstance(result, dict) and result.get("success"):
            self._log_info(f"RecipesPresenter: apply_topology подтверждён для '{target_slug}'")
            self._finalize_activation(target_slug)
            # Task 2.2: частичный успех — топология применена, но часть
            # процессов умерла на старте (initialize-провал, ready=False)
            ready = result.get("ready")
            if isinstance(ready, dict):
                not_ready = sorted(name for name, ok in ready.items() if not ok)
                if not_ready:
                    self._log_error(f"RecipesPresenter: процессы не запустились: {not_ready}")
                    self._view.show_error(
                        "Рецепт применён, но процессы не запустились: "
                        + ", ".join(not_ready)
                        + " — проверьте вкладку «Процессы»"
                    )
            return

        if isinstance(result, dict):
            if result.get("debounced"):
                error_msg = "Переключение отклонено backend'ом: предыдущая замена ещё выполняется"
            else:
                error_msg = str(result.get("error") or "Ошибка применения топологии")
                if result.get("rolled_back"):
                    error_msg += " (выполнен откат к предыдущей топологии)"
        else:
            error_msg = "Ошибка применения топологии: нет ответа от ProcessManager"

        self._log_error(f"RecipesPresenter: apply_topology провален для '{target_slug}': {error_msg}")
        self._rollback_activation(prev_active, error_msg)

    def _finalize_activation(self, slug: str) -> None:
        """Финализировать активацию ПОСЛЕ подтверждения (или без backend).

        persist активного slug'а в манифест — только здесь: незавершённый или
        откаченный switch не должен переживать рестарт приложения.
        """
        if self._persist_active_fn is not None:
            try:
                self._persist_active_fn(slug)
                self._log_info(f"RecipesPresenter: persist в манифест '{slug}'")
            except Exception as exc:  # noqa: BLE001
                self._log_warning(f"RecipesPresenter: persist не удался: {exc}")

        self.load()
        self._view.set_buttons_state(True, True)

    def _rollback_activation(self, prev_active: str | None, error_msg: str) -> None:
        """Вернуть GUI к prev_active после провала apply: slug + editor/дисплеи.

        Компенсирующий dispatch(ActivateRecipe(prev)) — а не отложенный исходный
        dispatch: дисплеи обязаны быть перестроены ДО прихода кадров новой
        топологии (fix load-display-rebind), поэтому прямой dispatch идёт до
        apply, а при провале выполняется обратный. Best-effort: ошибки отката
        логируются, пользователь видит error_msg в любом случае.
        """
        try:
            if prev_active:
                self._store.set_active(prev_active)
            else:
                self._store.deactivate()
        except Exception as exc:  # noqa: BLE001
            self._log_error(f"RecipesPresenter: откат set_active({prev_active!r}) не удался: {exc}")

        if self._commands is not None and prev_active:
            try:
                self._commands.dispatch(ActivateRecipe(slug=prev_active), undoable=False)
            except Exception as exc:  # noqa: BLE001
                self._log_error(f"RecipesPresenter: компенсирующий ActivateRecipe('{prev_active}') не удался: {exc}")

        self._view.show_error(error_msg)
        self.load()

    def on_save(self, slug: str | None = None) -> bool:
        """Сохранить текущую живую топологию в выбранный рецепт (Этап 1).

        Источник — TopologyRepository (services.topology): он SSOT текущего графа
        (Pipeline-редактор пишет в него через dispatch). ``load()`` возвращает ``Topology``
        entity (Protocol-контракт) — берём ``.to_dict()`` (Dict at Boundary), как делает и
        Pipeline-путь (``LayoutController.save_to_active_recipe``).

        Единый сборщик v3-raw (RS-1): :func:`recipes.save.build_recipe_v3_raw` собирает полный
        blueprint из raw + topology-dict, СОХРАНЯЯ авторские ``name``/``description`` и layout
        (``gui_positions``/``locked_nodes``) существующего рецепта — Recipes-Save не стирает
        позиции узлов (у презентера нет доступа к живой сцене — override не передаём).

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

        raw = self._store.read_raw(target_slug)
        if raw is None:
            self._view.show_error(f"Рецепт '{target_slug}' не найден")
            return False

        try:
            # Сборка blueprint — ВНУТРИ try/except: раньше topo.get(...) на Topology entity
            # (у неё нет .get()) улетал AttributeError мимо обработки → Save тихо крашился
            # в Qt-слоте, пользователь видел no-op (RS-1). Теперь entity → dict до сборки.
            from multiprocess_prototype.recipes.save import build_recipe_v3_raw, validate_recipe_blueprint

            topo = self._topology_store.load().to_dict()
            new_raw = build_recipe_v3_raw(raw, topo)
            # RS-5 (C-4): валидация перед записью — граф с циклом/дублями имён процессов
            # не пишется. RecipeValidationError ловится тем же except ниже (громкая ошибка).
            validate_recipe_blueprint(new_raw.get("blueprint", {}))
            self._store.save_raw(target_slug, new_raw)
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
