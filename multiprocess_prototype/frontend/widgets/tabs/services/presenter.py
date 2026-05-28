"""ServicesPresenter — бизнес-логика таба сервисов.

Task E.4: мигрирован на AppServices DI. Принимает services: AppServices.
Lifecycle (start/stop/restart/get_lifecycle/list) делегируется в
services.services (ServiceManager Protocol) — адаптер владеет кэшем
экземпляров и мутацией lifecycle. Presenter оборачивает DomainError → bool/None
для UI. Пути директорий читаются из services.config.

Pure Python (без Qt-импортов).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from multiprocess_framework.modules.service_module import ServiceLifecycle
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.errors import DomainError


class ServicesPresenter:
    """Presenter для ServicesTab.

    Делегирует lifecycle сервисов в services.services (ServiceManager Protocol).
    Управляет путями директорий сервисов (read из services.config, write в yaml).

    Примечание (MVP): lifecycle читается из ServiceManager.get_lifecycle() —
    StateProxy недоступен в GUI-процессе (он живёт только в ProcessModule-воркерах).
    IPC-синхронизация с воркерами — Phase 4+.
    """

    def __init__(self, services: AppServices) -> None:
        self._services = services

    def list_services(self) -> "list[tuple[str, str, ServiceLifecycle]]":
        """Список зарегистрированных сервисов через ServiceManager Protocol.

        Returns:
            list[(name, title, lifecycle)] — тройка для построения секций.
            Пустой список если сервисов нет.
        """
        manager = self._services.services
        result: list[tuple[str, str, ServiceLifecycle]] = []
        for spec in manager.list_services():
            # Если в metadata есть title — используем его, иначе генерируем из id
            title = spec.metadata.get("title") or spec.service_id.replace("_", " ").title()
            try:
                lifecycle = manager.get_lifecycle(spec.service_id)
            except DomainError:
                continue
            result.append((spec.service_id, title, lifecycle))
        return result

    # ------------------------------------------------------------------ #
    #  Управление lifecycle сервисов (делегирование в ServiceManager)      #
    # ------------------------------------------------------------------ #

    def start_service(self, name: str) -> bool:
        """Запустить сервис. Делегирует services.services.start(), DomainError → False.

        Адаптер инстанцирует cls(), вызывает start({}), кэширует экземпляр и
        мутирует lifecycle (RUNNING/ERROR). Idempotent: уже RUNNING → no-op.

        Returns:
            True при успешном запуске, False при ошибке или отсутствии сервиса.
        """
        try:
            self._services.services.start(name)
            return True
        except DomainError:
            return False

    def stop_service(self, name: str) -> bool:
        """Остановить сервис. Делегирует services.services.stop(), DomainError → False.

        Returns:
            True при успешной остановке, False при ошибке.
        """
        try:
            self._services.services.stop(name)
            return True
        except DomainError:
            return False

    def restart_service(self, name: str) -> bool:
        """Перезапустить сервис: stop() → start(). DomainError → False.

        Returns:
            True если перезапуск завершился успешно.
        """
        try:
            self._services.services.restart(name)
            return True
        except DomainError:
            return False

    def get_lifecycle(self, name: str) -> "ServiceLifecycle | None":
        """Прочитать текущий lifecycle сервиса через ServiceManager Protocol.

        Returns:
            ServiceLifecycle или None если сервис не найден.
        """
        try:
            return self._services.services.get_lifecycle(name)
        except DomainError:
            return None

    # ------------------------------------------------------------------ #
    #  Управление путями директорий сервисов                               #
    # ------------------------------------------------------------------ #

    def get_service_paths(self) -> list[str]:
        """Текущий список директорий поиска сервисов.

        Returns:
            Список строк-путей из конфига или ["Services"] по умолчанию.
        """
        discovery = self._services.config.get("discovery", {}) or {}
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
        """
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
