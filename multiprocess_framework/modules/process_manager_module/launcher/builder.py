"""Generic-сборка ``SystemLauncher`` из готовых proc_dict'ов — шов E3 (Task 5.2).

Вынесено из ``multiprocess_prototype/backend/launch.py`` (шов ``SystemLauncher(...)``
+ ``add_process``-цикл). Универсальная часть композиции: ``proc_dicts`` + DI-параметры
оркестратора → сконфигурированный ``SystemLauncher``. Прототип-специфика (манифест,
state bootstrap, конкретный ``orchestrator_class_path``) остаётся в приложении и
передаётся сюда параметрами (DI), а не хардкодится во framework.

Инвариант слоёв: framework не знает про приложение — ``orchestrator_class_path``
приходит извне (DI), функция его лишь пробрасывает.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .system_launcher import SystemLauncher


@runtime_checkable
class SpawnBackend(Protocol):
    """Точка расширения «как система поднимается» — задел multi-node (Task 5.2).

    Сегодня единственный backend — локальный spawn внутри
    ``SystemLauncher``/``ProcessSpawner`` (``launcher.run()``). Протокол фиксирует
    границу для будущего удалённого/контейнерного backend'а, но **не строится в
    этой задаче** (только контракт — «задел, без постройки»).

    Pre:  ``launcher`` собран (``assemble_launcher`` уже отработал).
    Post: реализация поднимает процессы launcher'а и возвращает управление
          согласно своей семантике (блокирующий ``run`` / фоновый ``start``).
    """

    def launch(self, launcher: "SystemLauncher") -> None:  # pragma: no cover - контракт
        ...


def assemble_launcher(
    proc_dicts: Mapping[str, Dict[str, Any]],
    *,
    orchestrator_class_path: Optional[str] = None,
    orchestrator_config: Optional[Dict[str, Any]] = None,
    stop_timeout: float = 5.0,
) -> "SystemLauncher":
    """Собрать ``SystemLauncher`` из готовых proc_dict'ов + DI-параметров оркестратора.

    Универсальный шов E3: конструктор ``SystemLauncher`` + ``add_process``-цикл,
    ранее инлайн в ``SystemBuilder.build()``. Что за оркестратор и что в его
    конфиге — приходит параметрами (DI), не хардкод во framework.

    Args:
        proc_dicts: ``{process_name -> proc_dict}``; порядок итерации = порядок
            ``add_process`` (dict сохраняет порядок вставки в PY3.7+).
        orchestrator_class_path: import-path класса оркестратора; ``None`` = дефолт
            ``ProcessManagerProcess`` (проброс в ``SystemLauncher``).
        orchestrator_config: Dict-at-Boundary конфиг оркестратора (проброс без правок).
        stop_timeout: таймаут остановки (проброс в ``SystemLauncher``).

    Returns:
        Сконфигурированный ``SystemLauncher``: для каждой ``(name, proc_dict)``
        вызван ``add_process`` (proc_dict нормализуется ``merge_with_defaults``).

    Pre:
        - ``proc_dicts`` — не-``None`` mapping (может быть пустым).
    Post:
        - ``len(launcher._processes) == len(proc_dicts)``; имена и порядок сохранены;
        - ``orchestrator_class_path``/``orchestrator_config``/``stop_timeout``
          проброшены в конструктор без изменений.
    Invariants:
        - функция НЕ спавнит процессы (только конфигурирует launcher);
        - ``proc_dicts`` не мутируется.
    """
    from .system_launcher import SystemLauncher

    launcher = SystemLauncher(
        stop_timeout=stop_timeout,
        orchestrator_class_path=orchestrator_class_path,
        orchestrator_config=orchestrator_config,
    )
    for name, proc_dict in proc_dicts.items():
        launcher.add_process(name, proc_dict)
    return launcher
