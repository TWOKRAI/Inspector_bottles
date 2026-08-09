# -*- coding: utf-8 -*-
"""B3 — имя плоскости ошибок: аргумент вызывающего перестал быть мёртвым.

Найдено живым прогоном B3. Гашение плоскости ошибок стало достижимым — и
вместе с ним заработало предупреждение о молчащих приёмниках. Живьём оно
пришло **шесть раз одинаковым**::

    [WARNING] [ErrorManager] [system] приёмники не приняли ни одной записи
              за прогон: critical_file, errors_file, warnings_file

Стенд из шести процессов, шесть плоскостей ошибок — и ни одного адреса, по
которому можно понять, чья молчит. Причина: ``_normalize_error_config``
возвращала строку-дефолт ``"ErrorManager"``, а конструктор присваивал её
БЕЗУСЛОВНО, затирая ``manager_name=f"error_{proc}"``, который передаёт
``process_managers``. Параметр существовал и не значил ничего.
"""

from __future__ import annotations

from ..core.error_manager import ErrorManager


def test_explicit_name_survives_a_config_that_does_not_name_one() -> None:
    em = ErrorManager(manager_name="error_camera_0", config={"app_name": "errors"})
    assert em.manager_name == "error_camera_0"


def test_config_name_still_wins_over_the_argument() -> None:
    """Пара: приоритет конфига сохранён — правка чинит МОЛЧАНИЕ, а не порядок."""
    em = ErrorManager(manager_name="error_camera_0", config={"manager_name": "from_config"})
    assert em.manager_name == "from_config"


def test_no_name_anywhere_keeps_the_historical_default() -> None:
    em = ErrorManager(config=None)
    assert em.manager_name == "ErrorManager"


def test_the_process_wiring_names_the_plane_after_its_process() -> None:
    """Второй заход: тест выше был зелёным, а СТЕНД по-прежнему звал всех одинаково.

    Причина — дефолт схемы: `ErrorManagerConfig.manager_name` приезжает строкой
    «ErrorManager» наравне с заданной, и отличить «оператор так назвал» от
    «схема подставила» на стороне менеджера нечем. Проверка на дубле-словаре
    этого не видела, потому что словарь ключа не содержал; поймал живой прогон.
    Здесь проверяется ПРОДОВАЯ проводка, а не удобная форма конфига.
    """
    from ...process_module.managers.process_managers import ProcessManagers

    class _Proc:
        name = "camera_7"

    factory = ProcessManagers.__new__(ProcessManagers)
    factory.process = _Proc()
    error = factory._create_error_manager({"error": {"app_name": "errors"}})
    assert error is not None
    assert error.manager_name == "error_camera_7"


def test_the_materialized_schema_default_does_not_count_as_a_chosen_name() -> None:
    """Форма, которая приезжает НА СТЕНДЕ, а не удобная форма конфига.

    ``managers_payload_for_proc`` материализует дефолт: в словаре всегда лежит
    ``manager_name: "ErrorManager"``, хотя оператор ничего не писал. Первая
    редакция правки проверяла только пустоту ключа — тест на словаре без ключа
    был зелёным, а стенд по-прежнему звал все шесть плоскостей одинаково.
    Поймано ПОВТОРНЫМ живым прогоном.
    """
    from ...process_module.managers.process_managers import ProcessManagers

    class _Proc:
        name = "camera_7"

    factory = ProcessManagers.__new__(ProcessManagers)
    factory.process = _Proc()
    error = factory._create_error_manager({"error": {"manager_name": "ErrorManager", "app_name": "errors"}})
    assert error.manager_name == "error_camera_7"


def test_an_explicit_config_name_is_not_overwritten_by_the_wiring() -> None:
    """Пара: если имя назвали в конфиге, проводка его не трогает."""
    from ...process_module.managers.process_managers import ProcessManagers

    class _Proc:
        name = "camera_7"

    factory = ProcessManagers.__new__(ProcessManagers)
    factory.process = _Proc()
    error = factory._create_error_manager({"error": {"manager_name": "chosen_by_operator"}})
    assert error.manager_name == "chosen_by_operator"
