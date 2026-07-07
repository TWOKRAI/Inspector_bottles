# -*- coding: utf-8 -*-
"""Управление живым backend из вкладки Pipeline (Трек F, Task F.3).

Кнопки «Запустить активный рецепт» / «Перезапустить» / start-stop-restart процесса
→ IPC в ``ProcessManager``-proxy. Вынесено из ``PipelinePresenter`` дословно —
поведение заморожено ``tests/test_launch_recipe.py`` и НЕ меняется этим разрезом.

Разграничение ответственности (контроллер НЕ трогает scene/позиции/модель графа):
- источник топологии — сохранённый рецепт (``launch_active_recipe``) ИЛИ in-memory
  модель редактора (``restart_topology`` → ``graph_to_blueprint``);
- транспорт — ``pm_proxy.apply_topology`` / ``start_process`` / ``stop_process`` /
  ``restart_process``; ответ PM разбирается в ``_on_recipe_launch_result``;
- обратная связь — не-модальный статус через ``notify``-callback (+ лог).

Qt-зависимость: ``launch_active_recipe`` / ``_on_recipe_launch_result`` /
``_notify_status`` полностью Qt-free (feedback через notify). ``restart_topology``
и ``control_process`` дословно сохранили ``QMessageBox`` (локальный импорт) как
GUI-реакцию — контроллер частично тянет Qt именно из-за них (перенос без переписи).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from .io import graph_to_blueprint
from .recipe_io import launch_topology_source, recipe_blueprint

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from multiprocess_prototype.domain.protocols import RecipeStore

    from .model import PipelineModel

logger = logging.getLogger(__name__)


class RuntimeController:
    """Контроллер команд управления живым backend для вкладки Pipeline.

    Зависимости — runtime-объекты (не domain): ProcessManager-proxy (может быть
    None, если система не запущена), RecipeStore (сохранённые рецепты), модель
    редактора (для «Перезапустить»), notify-callback (статусная строка).
    """

    def __init__(
        self,
        *,
        pm_proxy: Any,
        recipes: "RecipeStore",
        model: "PipelineModel",
        notify: "Callable[[str], None] | None",
    ) -> None:
        # Этап 1 pipeline-live-control: IPC-фасад управления живым backend
        # (apply_topology / start / stop / restart). None → кнопки управления
        # дают понятный статус вместо действия.
        self._pm_proxy = pm_proxy
        # RecipeStore Protocol (services.recipes) — сохранённые рецепты.
        self._recipes = recipes
        # Модель редактора — источник blueprint для restart_topology (in-memory граф).
        self._model = model
        # G.6.2: callback показа статуса пользователю (statusBar). None → только лог.
        self._notify = notify

    # ------------------------------------------------------------------ #
    #  Запуск активного рецепта                                           #
    # ------------------------------------------------------------------ #

    def launch_active_recipe(self, parent: "QWidget | None" = None) -> bool:
        """Запустить активный рецепт через ProcessManager-proxy (request/response).

        Получает blueprint из активного рецепта и вызывает
        ``proxy.apply_topology(blueprint, on_result=...)`` — горячую замену
        процессов с РЕАЛЬНЫМ результатом (command-result-bridge, Task 4.1).

        В отличие от прежнего fire-and-forget (показывал «отправлено» без знания
        факта): request исполняется на worker-потоке (UI не фризится), а реальный
        ответ PM (``success``/``replaced``/``rolled_back``) приходит в
        :meth:`_on_recipe_launch_result` в Qt main-thread и показывается
        пользователю как успех (с числом заменённых процессов) или ошибка/rollback.

        Task F.4: использует RecipeStore Protocol (services.recipes).

        Args:
            parent: родительский виджет для QMessageBox (может быть None).

        Returns:
            True если запрос отправлен в работу (результат придёт асинхронно в
            ``_on_recipe_launch_result``); False при pre-flight ошибке (нет
            активного рецепта / blueprint / proxy / ошибка отправки).

        Note:
            Feedback не-модальный: статус и результат идут в статусную строку
            (``_notify``) и лог (терминал), без блокирующих QMessageBox.
        """
        store = self._recipes

        # Шаг 1: проверить активный рецепт
        active_slug = store.get_active()
        if active_slug is None:
            self._notify_status("Запуск рецепта: не выбран активный рецепт", level="warning")
            return False

        # Шаг 2: прочитать рецепт через RecipeStore Protocol
        current = store.read_raw(active_slug)
        if current is None:
            self._notify_status(f"Запуск рецепта: не удалось прочитать рецепт '{active_slug}'", level="error")
            return False

        # Шаг 3: проверить наличие blueprint в рецепте (SC-12: единая READ-точка
        # recipe_io поверх backend.unwrap_recipe; поддержка v3 top-level и legacy
        # data.blueprint без локальной or-цепочки разбора формата).
        blueprint = recipe_blueprint(current)
        if not blueprint:
            self._notify_status(f"Запуск рецепта: рецепт '{active_slug}' не содержит blueprint", level="warning")
            return False

        # Шаг 4: ProcessManager-proxy с async request/response (Task 4.1: topology.apply).
        proxy = self._pm_proxy
        if proxy is None or not hasattr(proxy, "apply_topology"):
            self._notify_status(
                "Запуск рецепта: ProcessManager-proxy недоступен (система не запущена)",
                level="warning",
            )
            return False

        # Шаг 5: request/response — реальный результат придёт в on_result (main-thread),
        # request исполняется на worker-потоке (UI не фризится). До ответа показываем
        # «выполняется…» в статусной строке (не модально, чтобы не блокировать UI).
        # Task 2.2 displays-in-recipe: если рецепт v3 (top-level blueprint) — передаём
        # ПОЛНЫЙ raw-dict, backend-овский unwrap_recipe извлечёт display_definitions.
        # Иначе (legacy v2) — только blueprint (backward compat). Выбор — в recipe_io.
        topology_source = launch_topology_source(current)
        self._notify_status(f"Запуск рецепта '{active_slug}': выполняется…")
        try:
            proxy.apply_topology(
                topology_source,
                on_result=lambda resp: self._on_recipe_launch_result(resp, active_slug),
            )
        except Exception as exc:
            logger.exception("launch_active_recipe dispatch failed")
            self._notify_status(f"Запуск рецепта '{active_slug}': ошибка отправки — {exc}", level="error")
            return False
        return True

    def _on_recipe_launch_result(self, resp: dict, slug: str) -> None:
        """Главный поток: показать реальный результат активации рецепта (P3).

        Не-модально (статус-строка + лог). Форма ответа:
        - полный PM-ответ ``{"success": bool, "result": {success, replaced,
          rolled_back, error, ...}}`` (через ``router.request`` → reply PM);
        - error/timeout-обёртка ``{"success": False, "error": "..."}`` (без
          ``result``) — от RequestRunner/``request()``.

        Приоритет вердикту самого PM (``result["success"]``); при его отсутствии —
        транспортный ``success``.
        """
        resp = resp if isinstance(resp, dict) else {}
        inner = resp.get("result")
        inner = inner if isinstance(inner, dict) else {}
        ok = bool(inner["success"]) if "success" in inner else bool(resp.get("success"))

        if ok:
            replaced = inner.get("replaced")
            count = len(replaced) if isinstance(replaced, list) else replaced
            detail = f"заменено процессов: {count}" if count is not None else "горячая замена применена"
            self._notify_status(f"Рецепт '{slug}' запущен ({detail})")
            return

        # Ошибка / rollback
        error = inner.get("error") or resp.get("error") or "неизвестная ошибка"
        if inner.get("rolled_back"):
            error = f"{error}; изменения откачены (rollback) — прежняя топология сохранена"
        self._notify_status(f"Рецепт '{slug}': ошибка запуска — {error}", level="error")

    # ------------------------------------------------------------------ #
    #  Этап 1 pipeline-live-control — кнопки управления процессами         #
    # ------------------------------------------------------------------ #

    def restart_topology(self, parent: "QWidget | None" = None) -> bool:
        """Применить ТЕКУЩИЙ граф редактора к живому backend (горячая замена).

        В отличие от ``launch_active_recipe`` (берёт сохранённый рецепт) — берёт
        in-memory модель редактора (``graph_to_blueprint``), тот же формат blueprint,
        что принимает ``apply_topology`` (Task 4.1). Fire-and-forget IPC.

        Сценарий: удалить ноду → «Перезапустить» → эффект ноды пропадает на дисплее.

        Args:
            parent: родитель для QMessageBox.

        Returns:
            True если команда отправлена, False при отсутствии proxy / ошибке.
        """
        from PySide6.QtWidgets import QMessageBox

        proxy = self._pm_proxy
        if proxy is None or not hasattr(proxy, "apply_topology"):
            QMessageBox.warning(
                parent,
                "Перезапустить",
                "ProcessManager-proxy недоступен.\nУправление возможно только при работающей системе.",
            )
            return False

        bp_dict, _bindings, _gui_positions = graph_to_blueprint(self._model)
        try:
            result = proxy.apply_topology(bp_dict)
            if result is not None and result.get("success", False):
                self._notify_status("Команда перезапуска топологии отправлена в backend")
                return True
            QMessageBox.critical(
                parent,
                "Перезапустить",
                f"Не удалось отправить команду: {(result or {}).get('error') or 'неизвестная ошибка'}",
            )
            return False
        except Exception as exc:
            logger.exception("restart_topology failed")
            QMessageBox.critical(parent, "Перезапустить", f"Ошибка: {exc}")
            return False

    def control_process(self, action: str, process_name: str, parent: "QWidget | None" = None) -> bool:
        """Управление одним процессом по имени (Task 1.2): start / stop / restart.

        Args:
            action: "start" | "stop" | "restart".
            process_name: имя процесса (НЕ адрес — per-worker управление это Этап 3).
            parent: родитель для QMessageBox.

        Returns:
            True если команда отправлена, False при отсутствии proxy / неизвестном action.
        """
        from PySide6.QtWidgets import QMessageBox

        proxy = self._pm_proxy
        method = {
            "start": getattr(proxy, "start_process", None) if proxy else None,
            "stop": getattr(proxy, "stop_process", None) if proxy else None,
            "restart": getattr(proxy, "restart_process", None) if proxy else None,
        }.get(action)

        if proxy is None or method is None:
            QMessageBox.warning(
                parent,
                "Управление процессом",
                "ProcessManager-proxy недоступен или действие не поддержано.",
            )
            return False
        if not process_name:
            QMessageBox.warning(parent, "Управление процессом", "Не выбран процесс")
            return False

        try:
            method(process_name)
            labels = {"start": "запуск", "stop": "остановка", "restart": "перезапуск"}
            self._notify_status(f"Команда '{labels[action]}' процесса '{process_name}' отправлена")
            return True
        except Exception as exc:
            logger.exception("control_process(%s, %s) failed", action, process_name)
            QMessageBox.critical(parent, "Управление процессом", f"Ошибка: {exc}")
            return False

    def _notify_status(self, message: str, *, level: str = "info") -> None:
        """Показать статус через notify-callback (statusBar) + лог в терминал.

        Не-модально: вместо блокирующих QMessageBox результат команды виден в
        статусной строке и в логе (терминал). ``level`` — уровень логгера
        ("info"/"warning"/"error").
        """
        getattr(logger, level, logger.info)(message)
        if self._notify is not None:
            self._notify(message)


__all__ = ["RuntimeController"]
