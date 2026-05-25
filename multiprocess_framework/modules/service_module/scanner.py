"""ServiceScanner — автоматическое обнаружение и регистрация сервисов.

Рекурсивно обходит указанные директории, находит файлы ``service.py``
и импортирует их через ``importlib``. Декоратор ``@register_service``
в каждом файле автоматически добавляет запись в singleton ServiceRegistry.

Правило слоёв: этот модуль использует ТОЛЬКО stdlib (pathlib, importlib,
dataclasses). Никаких импортов из Services/, Plugins/, multiprocess_prototype/.
ServiceRegistry импортируется только для аннотаций (TYPE_CHECKING).

Пример использования::

    from pathlib import Path
    from multiprocess_framework.modules.service_module.scanner import discover

    result = discover(Path("Services/"))
    print(result.loaded)   # имена файлов успешно импортированных сервисов
    print(result.failed)   # [(путь, причина), ...]
    print(result.total)    # загружено + упало
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_framework.modules.service_module.registry import ServiceRegistry


@dataclass
class DiscoveryResult:
    """Результат сканирования директорий.

    Attributes:
        loaded: Относительные пути к файлам, импортированным без ошибок.
        failed: Список пар (путь, причина ошибки) для файлов с ошибками.
    """

    loaded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Общее количество обработанных файлов (успешных + неуспешных)."""
        return len(self.loaded) + len(self.failed)


def discover(
    *dirs: Path,
    registry: "ServiceRegistry | None" = None,
) -> DiscoveryResult:
    """Рекурсивно обойти директории и зарегистрировать все найденные сервисы.

    Для каждой директории из ``dirs`` ищет ``**/service.py`` (рекурсивно).
    Каждый найденный файл импортируется через ``importlib.util``.
    Декоратор ``@register_service`` при импорте автоматически добавляет
    запись в singleton ServiceRegistry.

    Args:
        *dirs:    Директории для сканирования. Если не указаны — возвращает
                  пустой DiscoveryResult без ошибок.
        registry: Зарезервировано для будущих расширений (namespace-изоляция).
                  В текущей реализации не используется: вся регистрация
                  происходит через декоратор в singleton. Передача значения
                  не влияет на поведение (не вызывает clear()).

    Returns:
        DiscoveryResult с полями ``loaded`` (успешные), ``failed`` (ошибки).

    Пример::

        result = discover(Path("Services/"), Path("extra/"))
        # result.loaded  == ["Services/webcam_camera/service.py", ...]
        # result.failed  == [("Services/broken/service.py", "SyntaxError: ...")]
    """
    result = DiscoveryResult()

    if not dirs:
        return result

    for base_dir in dirs:
        base_dir = Path(base_dir)
        if not base_dir.exists() or not base_dir.is_dir():
            # Молча пропускаем несуществующие директории
            continue

        for service_file in sorted(base_dir.glob("**/service.py")):
            _import_service_file(service_file, base_dir, result)

    return result


def _import_service_file(
    service_file: Path,
    base_dir: Path,
    result: DiscoveryResult,
) -> None:
    """Импортировать один файл service.py и обновить DiscoveryResult.

    Args:
        service_file: Абсолютный путь к service.py.
        base_dir:     Корень сканирования (для построения относительного пути).
        result:       Мутируемый результат сканирования.
    """
    # Относительный путь для отчёта и уникального имени модуля
    try:
        rel_path = service_file.relative_to(base_dir)
    except ValueError:
        rel_path = service_file

    rel_path_str = str(rel_path).replace("\\", "/")

    # Уникальное имя динамического модуля: избегаем коллизий при повторном
    # импорте одноимённых service.py из разных поддиректорий
    # Пример: "_service_dyn_webcam_camera_service"
    parent_name = service_file.parent.name
    stem = service_file.stem
    module_name = f"_service_dyn_{parent_name}_{stem}"

    # Если такой модуль уже загружен (например, при повторном вызове discover)
    # — выгружаем, чтобы декоратор сработал снова. Но если сервис уже
    # зарегистрирован, @register_service выбросит ValueError → попадёт в failed.
    if module_name in sys.modules:
        del sys.modules[module_name]

    try:
        spec = importlib.util.spec_from_file_location(module_name, service_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Не удалось создать spec для {service_file}")

        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        result.loaded.append(rel_path_str)

    except Exception as exc:  # noqa: BLE001
        # Удаляем незавершённый модуль из sys.modules
        sys.modules.pop(module_name, None)
        result.failed.append((rel_path_str, f"{type(exc).__name__}: {exc}"))
