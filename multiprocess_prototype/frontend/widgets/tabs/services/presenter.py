"""ServicesPresenter — бизнес-логика таба сервисов.

Pure Python (без Qt-импортов).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from loguru import logger

from multiprocess_framework.modules.service_module import IService, ServiceLifecycle

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


class ServicesPresenter:
    """Presenter для ServicesTab.

    Читает сервисы из ServiceRegistry через AppContext.
    Управляет путями директорий сервисов (аналогично PluginsPresenter).
    Кэширует запущенные экземпляры (_instances) для корректного stop/restart.

    Примечание (MVP): статус читается напрямую из ServiceRegistry.get(name).lifecycle —
    StateProxy недоступен в GUI-процессе (он живёт только в ProcessModule-воркерах).
    IPC-синхронизация с воркерами — Phase 4+.
    """

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx
        # Кэш запущенных экземпляров: name → экземпляр IService.
        # TODO (Phase 4+): инстанцирование через entry.cls() без параметров — MVP.
        # Webcam-сервис в продакшне должен получать device_index через config dict.
        self._instances: dict[str, IService] = {}

    def list_services(self) -> "list[tuple[str, str, ServiceLifecycle]]":
        """Список зарегистрированных сервисов из ServiceRegistry.

        Returns:
            list[(name, title, lifecycle)] — тройка для построения секций.
            Пустой список если registry не инициализирован или пуст.
        """
        registry = self._ctx.service_registry()
        if registry is None:
            return []

        result = []
        for entry in registry.list():
            # Если в meta есть title — используем его, иначе генерируем из name
            title = entry.meta.get("title") or entry.name.replace("_", " ").title()
            result.append((entry.name, title, entry.lifecycle))
        return result

    # ------------------------------------------------------------------ #
    #  Управление lifecycle сервисов                                       #
    # ------------------------------------------------------------------ #

    def start_service(self, name: str) -> bool:
        """Запустить сервис с указанным именем.

        Инстанцирует класс сервиса (если ещё не создан), вызывает start({}).
        Обновляет entry.lifecycle в ServiceRegistry напрямую.

        Args:
            name: Имя сервиса из ServiceRegistry.

        Returns:
            True при успешном запуске, False при ошибке или отсутствии сервиса.
        """
        registry = self._ctx.service_registry()
        if registry is None:
            return False

        entry = registry.get(name)
        if entry is None:
            return False

        # Инстанцируем если ещё нет в кэше
        instance = self._instances.get(name)
        if instance is None:
            try:
                instance = entry.cls()
            except Exception as exc:
                logger.error(f"ServicesPresenter: не удалось создать экземпляр {name}: {exc}")
                entry.lifecycle = ServiceLifecycle.ERROR
                return False
            self._instances[name] = instance

        try:
            ok = bool(instance.start({}))
        except Exception as exc:
            logger.error(f"ServicesPresenter: start({name}) выбросил исключение: {exc}")
            entry.lifecycle = ServiceLifecycle.ERROR
            return False

        entry.lifecycle = ServiceLifecycle.RUNNING if ok else ServiceLifecycle.ERROR
        return ok

    def stop_service(self, name: str) -> bool:
        """Остановить сервис с указанным именем.

        Если экземпляра нет в кэше — синхронизирует lifecycle → STOPPED без вызова stop().

        Args:
            name: Имя сервиса из ServiceRegistry.

        Returns:
            True при успешной остановке, False при ошибке.
        """
        registry = self._ctx.service_registry()
        if registry is None:
            return False

        entry = registry.get(name)
        if entry is None:
            return False

        instance = self._instances.get(name)
        if instance is None:
            # Нечего останавливать — синхронизируем lifecycle
            entry.lifecycle = ServiceLifecycle.STOPPED
            return True

        try:
            ok = bool(instance.stop())
        except Exception as exc:
            logger.error(f"ServicesPresenter: stop({name}) выбросил исключение: {exc}")
            entry.lifecycle = ServiceLifecycle.ERROR
            return False

        entry.lifecycle = ServiceLifecycle.STOPPED if ok else ServiceLifecycle.ERROR
        return ok

    def restart_service(self, name: str) -> bool:
        """Перезапустить сервис: stop() → start().

        Args:
            name: Имя сервиса из ServiceRegistry.

        Returns:
            True если оба шага (stop и start) завершились успешно.
        """
        return self.stop_service(name) and self.start_service(name)

    def get_lifecycle(self, name: str) -> "ServiceLifecycle | None":
        """Прочитать текущий lifecycle сервиса напрямую из ServiceRegistry.

        Примечание: StateProxy не используется — он недоступен в GUI-процессе.
        Прямое чтение из registry — MVP для Phase 3.

        Args:
            name: Имя сервиса.

        Returns:
            ServiceLifecycle или None если registry не инициализирован / сервис не найден.
        """
        registry = self._ctx.service_registry()
        if registry is None:
            return None
        entry = registry.get(name)
        return entry.lifecycle if entry is not None else None

    # ------------------------------------------------------------------ #
    #  Управление путями директорий сервисов                               #
    # ------------------------------------------------------------------ #

    def get_service_paths(self) -> list[str]:
        """Текущий список директорий поиска сервисов.

        Returns:
            Список строк-путей из конфига или [] если конфиг пустой.
        """
        config = getattr(self._ctx, "config", {}) or {}
        discovery = config.get("discovery", {}) or {}
        paths = discovery.get("service_paths") or ["Services"]
        return [str(p) for p in paths]

    def add_service_path(self, path: str) -> None:
        """Добавить новый путь к директориям поиска сервисов.

        Добавляет путь (если его нет в списке), сохраняет в user_overrides.yaml.

        Args:
            path: строковый путь к директории.
        """
        current = self.get_service_paths()
        if path in current:
            return
        new_list = current + [path]
        self._save_service_paths(new_list)

    def remove_service_path(self, path: str) -> None:
        """Удалить путь из директорий поиска сервисов.

        Args:
            path: строковый путь для удаления.
        """
        current = self.get_service_paths()
        if path not in current:
            return
        new_list = [p for p in current if p != path]
        self._save_service_paths(new_list)

    def rescan(self) -> str:
        """Запустить переобнаружение сервисов через scanner.discover().

        Returns:
            Строка-сводка результата «Загружено: N, ошибок: M».
            При отсутствии registry возвращает сообщение об ошибке.
        """
        registry = self._ctx.service_registry()
        if registry is None:
            return "ServiceRegistry не инициализирован"

        from multiprocess_framework.modules.service_module.scanner import discover
        from multiprocess_prototype.main import PROJECT_ROOT

        service_paths = [
            Path(PROJECT_ROOT / p) if not Path(p).is_absolute() else Path(p) for p in self.get_service_paths()
        ]
        result = discover(*service_paths)
        return f"Загружено: {len(result.loaded)}, ошибок: {len(result.failed)}"

    def _save_service_paths(self, paths: list[str]) -> None:
        """Сохранить список путей сервисов в user_overrides.yaml.

        Читает существующий файл (или {} если нет), обновляет только ключ
        discovery.service_paths, записывает обратно.

        Args:
            paths: новый список строковых путей.
        """
        from multiprocess_prototype.main import CONFIG_PATH

        override_path = CONFIG_PATH.parent / "user_overrides.yaml"

        existing: dict = {}
        if override_path.exists():
            try:
                with open(override_path, encoding="utf-8") as f:
                    existing = yaml.safe_load(f) or {}
            except yaml.YAMLError:
                existing = {}

        discovery = existing.get("discovery", {})
        if not isinstance(discovery, dict):
            discovery = {}
        discovery["service_paths"] = paths
        existing["discovery"] = discovery

        with open(override_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True, default_flow_style=False)
