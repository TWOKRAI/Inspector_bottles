"""ServicesPresenter — бизнес-логика таба сервисов.

Pure Python (без Qt-импортов).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from multiprocess_framework.modules.service_module import ServiceLifecycle
    from multiprocess_prototype.frontend.app_context import AppContext


class ServicesPresenter:
    """Presenter для ServicesTab.

    Читает сервисы из ServiceRegistry через AppContext.
    Управляет путями директорий сервисов (аналогично PluginsPresenter).
    """

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx

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
