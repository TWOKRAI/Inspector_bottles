"""SandboxPresenter -- бизнес-логика sandbox-теста плагина.

Pure Python (без PySide6). Определяет совместимость плагина с sandbox-режимом
и выполняет plugin.process() на одном кадре.

By design: sandbox требует живой Python plugin_class (entry.plugin_class)
для инстанцирования плагина -- не покрывается PluginCatalog (метаданные).
Bridge _registry остаётся навсегда. Q-F2=C (owner-decision 2026-05-28).

Песочница подаёт ровно `{"frame": frame}`. Совместим плагин, который запускается
от одного кадра И не имеет побочных эффектов.

Совместимые (запускаются от одного кадра, без побочных эффектов):
- processing / render / filter / hub / utility: grayscale, color_mask, blob_detector
  (необязательный вход mask не мешает) и т.п.

Несовместимые:
- source -- источники данных, используйте ServicesTab
- runtime / control -- требуют pipeline-контекст
- io / output / sink -- пишут наружу (файлы, устройства)
- calibration -- требует робота / стенд
- несколько обязательных входов или обязательный не image/bgr (mask, detections, ...) -- берётся из цепочки
- stitcher -- семантика N:1 (fan-in), требует несколько потоков
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from multiprocess_framework.modules.logger_module import get_std_logger
from multiprocess_prototype.domain.app_services import AppServices

# Задача 4.3 (Н-10): было `from loguru import logger`. Песочница плагинов ловит
# отказы чужого кода, и её предупреждения нужны в плоскости логов, а не вторым
# форматом в stderr — там их не видит ни хвост, ни ротация, ни ретеншен.
logger = get_std_logger(__name__)


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
_DISABLED_CATEGORIES: frozenset[str] = frozenset(
    {"source", "runtime", "control", "io", "output", "sink", "calibration"}
)

# Причины отказа по категории
_CATEGORY_REASONS: dict[str, str] = {
    "source": "источник данных — используйте превью сервиса в ServicesTab",
    "runtime": "требует pipeline-контекст",
    "control": "требует pipeline-контекст",
    "io": "пишет наружу (файлы/устройства) — не для песочницы",
    "output": "пишет наружу (файлы/устройства) — не для песочницы",
    "sink": "пишет наружу (файлы/устройства) — не для песочницы",
    "calibration": "требует робота/стенд",
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

    def __init__(self, services: AppServices) -> None:
        """Инициализация presenter.

        Args:
            services: AppServices DI-контейнер. PluginRegistry берётся через
                 services.plugins._registry bridge (plugin_class не покрыт Protocol).
        """
        self._services = services
        # By design: sandbox требует живой Python plugin_class/register_class/service --
        # не покрывается PluginCatalog (метаданные). Q-F2=C (owner-decision 2026-05-28).
        self._registry = getattr(services.plugins, "_registry", None)

    # ------------------------------------------------------------------ #
    #  Классификатор совместимости                                          #
    # ------------------------------------------------------------------ #

    def check_compatibility(self, plugin_name: str) -> SandboxCompatibility:
        """Проверить совместимость плагина с sandbox-тестом.

        Правила (в порядке приоритета):
        1. Registry недоступен → disabled (нет данных для проверки).
        2. Плагин не найден в registry → disabled.
        3. category == "source" → disabled.
        4. category in _DISABLED_CATEGORIES (runtime, control, io, output, sink, calibration) → disabled.
        5. name in _MULTI_INPUT_NAMES → disabled (stitcher: семантика N:1).
        6. Больше одного ОБЯЗАТЕЛЬНОГО входа, либо единственный обязательный не image/bgr
           → disabled (данные берутся из цепочки; необязательные входы, например mask у
           blob_detector, не считаются; имя порта — метка графа, судим по dtype).
        7. Обязательных входов нет, входы есть, но ни один не image/bgr → disabled
           (плагин не принимает кадр).
        8. Иначе → ok=True.

        Категории io / output / sink / calibration отсекаются на шаге 4 вместе с
        source / runtime / control: песочница не должна писать файлы и дёргать устройства.

        Args:
            plugin_name: имя плагина (ключ в registry).

        Returns:
            SandboxCompatibility с ok и причиной.
        """
        # Получаем registry из AppContext
        registry = self._registry
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

        # Имена портов — метки графа, а не ключи item (flip/negative: порт "region" читает
        # item["frame"]). Песочница подаёт один BGR-кадр, поэтому судим по dtype:
        # единственный обязательный вход должен быть image/bgr. Необязательные входы
        # не считаются — плагин обязан работать и без них.
        inputs = getattr(entry, "inputs", [])
        required = [p for p in inputs if not getattr(p, "optional", False)]
        blockers = (
            required if len(required) > 1 else [p for p in required if str(getattr(p, "dtype", "")) != "image/bgr"]
        )
        if blockers:
            return SandboxCompatibility(
                ok=False,
                reason=f"требует входы из цепочки: {', '.join(p.name for p in blockers)}",
            )
        if inputs and not required and not any(str(getattr(p, "dtype", "")) == "image/bgr" for p in inputs):
            return SandboxCompatibility(ok=False, reason="не принимает кадр")

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
            Выходной numpy array: первый image/*-выход плагина (иначе "frame") из первого
            результирующего item; 2D-маска переводится в BGR (H, W, 3).
            None при ошибке / пустом результате.
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
        from multiprocess_framework.modules.process_module.generic import frame_trace
        from multiprocess_framework.modules.process_module.plugins import SubPluginContext

        # Получаем entry из registry
        registry = self._registry
        if registry is None:
            self._warn(f"SandboxPresenter: PluginRegistry недоступен, run_once({plugin_name}) пропущен")
            return None

        entry = registry.get(plugin_name)
        if entry is None:
            self._warn(f"SandboxPresenter: плагин «{plugin_name}» не найден в registry")
            return None

        # Инстанцируем плагин
        plugin_cls = entry.plugin_class
        # Fable MED-2: sandbox исполняет плагин мимо PluginOrchestrator.boot() —
        # ставим frame-trace обёртку здесь (раньше её давал __init_subclass__).
        frame_trace.install_tracing(plugin_cls)
        plugin = plugin_cls()

        # Создаём изолированный контекст для sandbox
        ctx = SubPluginContext(
            config=config_overrides,
            process_name="sandbox",
        )

        # configure → process
        plugin.configure(ctx)
        result = plugin.process([{"frame": frame}])

        # Показываем первый image/*-выход плагина (color_mask/hsv_mask → mask,
        # blob_detector → frame); нет такого порта или значения → "frame".
        if result and isinstance(result, list) and len(result) > 0:
            key = next(
                (p.name for p in getattr(plugin_cls, "outputs", []) if str(p.dtype).startswith("image/")),
                "frame",
            )
            out = result[0].get(key)
            if out is None:
                out = result[0].get("frame")
            if out is not None:
                if out.ndim == 2:  # gray-маска → BGR: вид всегда получает (H, W, 3)
                    out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
                return out

        return None

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    def _warn(self, msg: str) -> None:
        """Логировать предупреждение через разъём логов (не мимо него)."""
        logger.warning(msg)
