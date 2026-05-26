"""SandboxPresenter — бизнес-логика sandbox-теста плагина.

Pure Python (без PySide6). Определяет совместимость плагина с sandbox-режимом
и выполняет plugin.process() на одном кадре.

Совместимые плагины (stateless, single-frame, single-input):
- processing: grayscale, color_mask, flip, resize, negative и т.п.

Несовместимые:
- source — источники данных, используйте ServicesTab
- runtime / control — требуют pipeline-контекст
- multi-input / stitcher — семантика N:1 (fan-in), требует несколько потоков
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from loguru import logger

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


@dataclass
class SandboxCompatibility:
    """Результат проверки совместимости плагина с sandbox-тестом.

    Attributes:
        ok: True если плагин можно запустить в sandbox.
        reason: причина недоступности (русская строка для tooltip).
                Пустая строка если ok=True.
    """

    ok: bool
    reason: str = ""


# Категории, несовместимые с sandbox
_DISABLED_CATEGORIES: frozenset[str] = frozenset({"source", "runtime", "control"})

# Причины отказа по категории
_CATEGORY_REASONS: dict[str, str] = {
    "source": "источник данных — используйте превью сервиса в ServicesTab",
    "runtime": "требует pipeline-контекст",
    "control": "требует pipeline-контекст",
}

# Hardcode имён плагинов с семантикой multi-input (fan-in N:1).
# TODO: заменить на проверку атрибута класса `multi_input: ClassVar[bool] = True`
#       когда он будет добавлен в ProcessModulePlugin (ADR: future work).
_MULTI_INPUT_NAMES: frozenset[str] = frozenset({"stitcher"})


class SandboxPresenter:
    """Presenter для sandbox-теста плагина.

    Логика:
    - check_compatibility() — определяет можно ли запустить плагин в sandbox.
    - run_once() — запускает plugin.configure() + plugin.process() на одном кадре.

    Не импортирует PySide6 — полностью тестируем без Qt.
    """

    def __init__(self, ctx: "AppContext") -> None:
        """Инициализация presenter.

        Args:
            ctx: AppContext — DI-контейнер приложения. Используется для
                 доступа к plugin_registry().
        """
        self._ctx = ctx

    # ------------------------------------------------------------------ #
    #  Классификатор совместимости                                          #
    # ------------------------------------------------------------------ #

    def check_compatibility(self, plugin_name: str) -> SandboxCompatibility:
        """Проверить совместимость плагина с sandbox-тестом.

        Правила (в порядке приоритета):
        1. Registry недоступен → disabled (нет данных для проверки).
        2. Плагин не найден в registry → disabled.
        3. category == "source" → disabled.
        4. category in ("runtime", "control") → disabled.
        5. name in _MULTI_INPUT_NAMES → disabled (stitcher: семантика N:1).
        6. len(inputs) > 1 → disabled (несколько входных портов).
        7. Иначе → ok=True.

        Args:
            plugin_name: имя плагина (ключ в registry).

        Returns:
            SandboxCompatibility с ok и причиной.
        """
        # Получаем registry из AppContext
        registry = self._ctx.plugin_registry()
        if registry is None:
            return SandboxCompatibility(
                ok=False,
                reason="PluginRegistry недоступен",
            )

        # Ищем entry по имени
        entry = registry.get(plugin_name)
        if entry is None:
            return SandboxCompatibility(
                ok=False,
                reason=f"плагин «{plugin_name}» не найден в реестре",
            )

        # Проверяем категорию
        category = getattr(entry, "category", "")
        if category in _DISABLED_CATEGORIES:
            reason = _CATEGORY_REASONS.get(category, f"категория «{category}» несовместима с sandbox")
            return SandboxCompatibility(ok=False, reason=reason)

        # Hardcode: stitcher имеет семантику N:1 (fan-in), несмотря на 1 порт в inputs.
        # TODO: убрать hardcode когда у ProcessModulePlugin появится атрибут
        #       `multi_input: ClassVar[bool]` — тогда проверять getattr(entry.plugin_class, "multi_input", False).
        if plugin_name in _MULTI_INPUT_NAMES:
            return SandboxCompatibility(
                ok=False,
                reason="требует несколько входных потоков (pipeline-контекст)",
            )

        # Проверяем количество входных портов
        inputs = getattr(entry, "inputs", [])
        if len(inputs) > 1:
            return SandboxCompatibility(
                ok=False,
                reason="требует несколько входных потоков (pipeline-контекст)",
            )

        return SandboxCompatibility(ok=True, reason="")

    # ------------------------------------------------------------------ #
    #  Выполнение плагина на одном кадре                                    #
    # ------------------------------------------------------------------ #

    def run_once(
        self,
        plugin_name: str,
        frame: np.ndarray,
        config_overrides: dict[str, Any],
    ) -> np.ndarray | None:
        """Запустить плагин на одном кадре и вернуть результат.

        Создаёт изолированный SubPluginContext с config_overrides.
        Вызывает plugin.configure(ctx) → plugin.process([{"frame": frame}]).
        Все исключения перехватываются — graceful degradation.

        Args:
            plugin_name: имя плагина в registry.
            frame: входной BGR numpy array.
            config_overrides: словарь с параметрами конфига (например HSV-диапазоны).

        Returns:
            Выходной numpy array (frame из первого результирующего item)
            или None при ошибке / пустом результате.
        """
        try:
            return self._run_once_unsafe(plugin_name, frame, config_overrides)
        except Exception as exc:
            self._warn(f"SandboxPresenter.run_once({plugin_name}): {type(exc).__name__}: {exc}")
            return None

    def _run_once_unsafe(
        self,
        plugin_name: str,
        frame: np.ndarray,
        config_overrides: dict[str, Any],
    ) -> np.ndarray | None:
        """Внутренняя реализация run_once без перехвата исключений."""
        from multiprocess_framework.modules.process_module.plugins import SubPluginContext

        # Получаем entry из registry
        registry = self._ctx.plugin_registry()
        if registry is None:
            self._warn(f"SandboxPresenter: PluginRegistry недоступен, run_once({plugin_name}) пропущен")
            return None

        entry = registry.get(plugin_name)
        if entry is None:
            self._warn(f"SandboxPresenter: плагин «{plugin_name}» не найден в registry")
            return None

        # Инстанцируем плагин
        plugin_cls = entry.plugin_class
        plugin = plugin_cls()

        # Создаём изолированный контекст для sandbox
        ctx = SubPluginContext(
            config=config_overrides,
            process_name="sandbox",
        )

        # configure → process
        plugin.configure(ctx)
        result = plugin.process([{"frame": frame}])

        # Извлекаем frame из первого результата
        if result and isinstance(result, list) and len(result) > 0:
            out_frame = result[0].get("frame")
            if out_frame is not None:
                return out_frame

        return None

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    def _warn(self, msg: str) -> None:
        """Логировать предупреждение через ctx.log_warning если доступен, иначе loguru."""
        log_warning = getattr(self._ctx, "log_warning", None)
        if callable(log_warning):
            log_warning(msg)
        else:
            logger.warning(msg)
