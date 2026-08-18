# -*- coding: utf-8 -*-
"""Общий контракт «дублёр оркестратора не имеет права молчать при рефакторинге» (S-29).

Пять тестовых файлов каталога подменяют ``GenericProcessManagerApp`` дублёром на
время вызова ``configure_topology_engine`` (``multiprocess_prototype/backend/
orchestrator_hooks.py``) — это ЕДИНСТВЕННАЯ функция модуля, чью ПОВЕРХНОСТЬ
оркестратора подменяют дублёры. Вторая функция файла,
``apply_topology_with_display_reload``, тоже принимает параметр ``orchestrator``
(первым позиционным, ``orchestrator_hooks.py:223-224``), но читает у него только
``orchestrator._log_info`` (``orchestrator_hooks.py:273``, уже учтено ниже) и ни
одним из пяти дублёров не вызывается — поэтому её поверхность в контракт ниже не
входит. Дублёр — фейк-гарнитура, а фейк доказывает сам себя:
переименуй метод/атрибут, который хук читает у оркестратора, на НАСТОЯЩЕМ классе —
и дублёры, живущие отдельной жизнью, не заметят ничего, хотя прод упадёт
``AttributeError`` на первом же switch. Измерено (2026-08-18): переименование
``live_process_config`` в ``process_manager_process.py`` не покрасило НИ ОДНОГО
из 69 тестов каталога.

Первый страж такого рода — ``test_hot_rebuild_provenance_hazards.py::
test_the_stub_orchestrator_speaks_the_real_class_surface`` (S-26, дублёр
``test_hot_rebuild_provenance_acceptance.py::_StubOrchestrator``). Этот модуль —
та же логика, вынесенная в общее место для ОСТАЛЬНЫХ четырёх дублёров, чтобы у
проверки не завелось пять слегка разошедшихся копий — ровно тот класс дефекта,
который эта задача и закрывает. Файл ``test_hot_rebuild_provenance_hazards.py``
сюда сознательно не переведён (не в скоупе S-29: его защита уже заведена и
работает, трогать её незачем) — там остаётся исходная, самостоятельная копия
проверки; расхождение между ней и этим хелпером ожидаемо и объяснено здесь.

Список имён — ГРЕПОМ по файлу-потребителю, не по памяти (2026-08-18)::

    rg -on "orchestrator\\.[_a-zA-Z]+" multiprocess_prototype/backend/orchestrator_hooks.py
    rg -n "getattr\\(orchestrator" multiprocess_prototype/backend/orchestrator_hooks.py

даёт (после схлопывания повторов; строки — из грепа 2026-08-18)::

    orchestrator.get_config                  # "sys_config", "observability_config_path",
                                              # "observability_recipe_path", "presentation_overlay"
    orchestrator._log_info
    orchestrator._get_protected_names        # -> FullReplacePlanner(protected_provider=...)
    orchestrator._topology_current_names     # -> FullReplacePlanner(current_provider=...)
    orchestrator.live_process_config         # -> FullReplacePlanner(protected_config_provider=...)
    orchestrator.logger_manager
    orchestrator.error_manager
    orchestrator.stats_manager
    orchestrator._topology_manager           # .configure(diff_fn=..., commands_fn=...)
    orchestrator._full_replace_planner       # ЗАПИСЬ (orchestrator._full_replace_planner = planner) —
                                              # не входит в поверхность: дублёру не обязательно
                                              # иметь атрибут ЗАРАНЕЕ, чтение не требуется
    getattr(orchestrator, "_active_recipe_from_manifest", None)   # внутри _active_recipe_path()

Итоговые ДЕСЯТЬ имён — ровно тот же список, что уже был измерен для S-26 (сверено
заново, а не переписано по памяти — оба грепа бьют в один и тот же, единственный
в модуле, потребитель).

Ред. 2026-08-18 (ревью, находка Д1): вторая линия проверки ниже была текстовым
поиском по ``blob`` исходников (регулярка с границей слова), а не разбором кода —
граница слова защищает от переименования-с-префиксом (``name`` -> ``name_RENAMED``),
но не отличает код от КОММЕНТАРИЯ/докстринга. Парная инъекция (2026-08-18):
переименование всех живых ``self.logger_manager`` красит guard; то же плюс ОДИН
комментарий с текстом старого имени красит guard ОБРАТНО (регулярка находит
подстроку внутри комментария). Вторая линия переведена на AST
(:func:`_self_attribute_names`) — узел ``ast.Attribute`` рождается только настоящим
синтаксисом доступа к атрибуту, из текста комментария/строки не рождается.
"""

from __future__ import annotations

import ast
import inspect

#: Поверхность оркестратора, которую читает ``configure_topology_engine``. См.
#: докстринг модуля — как получен список и почему он общий для всех пяти дублёров
#: (все пять подменяют ОДНОГО и того же потребителя).
ORCHESTRATOR_SURFACE_THE_HOOK_USES: tuple[str, ...] = (
    "get_config",
    "_log_info",
    "_get_protected_names",
    "_topology_current_names",
    "live_process_config",
    "logger_manager",
    "error_manager",
    "stats_manager",
    "_topology_manager",
    "_active_recipe_from_manifest",
)


def _self_attribute_names(source: str) -> set[str]:
    """Имена ``self.<attr>``, к которым КОД реально обращается (AST, не текст блоба).

    Ревью 2026-08-18 (Д1): прежняя версия искала регуляркой ``self.<имя>`` (с
    границей слова) по СЫРОМУ ТЕКСТУ исходников класса — граница слова защищала от
    переименования-с-префиксом (``name`` -> ``name_RENAMED``), но не отличала код от
    комментария: строка ``# исторически называлось self.logger_manager`` содержит ту
    же подстроку с той же границей слова, что и настоящее обращение. Узел
    ``ast.Attribute`` рождается только реальным синтаксисом доступа к атрибуту (и
    чтением, и записью — ``self.x`` и ``self.x = ...`` дают один тип узла); текст
    комментария или докстринга узла не порождает.

    Измерено парной инъекцией на боевых файлах (``orchestrator.py``,
    ``process_manager_process.py``, ``process_module.py`` — 10 живых упоминаний
    ``self.logger_manager``): переименование всех десяти красит guard (5 failed из
    38 в каталоге ``backend/tests``, как предсказано); то же плюс один комментарий,
    упоминающий старое имя текстом, красило РЕГУЛЯРОЧНУЮ версию обратно в 38 passed
    (ложный зелёный) — на этой, AST-версии, тот же комментарий не влияет на набор
    имён: 5 failed держится в обоих случаях.

    Args:
        source: исходный текст ОДНОГО класса (``inspect.getsource(cls)``).

    Returns:
        Множество имён атрибутов; пусто, если исходник не парсится (несинтаксируемый
        фрагмент трактуется так же, как «исходника нет» у вызывающего кода).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"
    }


def assert_stub_speaks_the_real_class_surface(stub_cls: type) -> None:
    """Сверить дублёра оркестратора с НАСТОЯЩИМ классом по имени.

    Две проверки, а не одна:

    1. Каждое имя, которое ``configure_topology_engine`` читает у оркестратора,
       обязано существовать у настоящего ``GenericProcessManagerApp`` — методы
       видны через ``hasattr`` на классе, атрибуты экземпляра (``logger_manager``,
       ``_topology_manager`` и т. п.) рождаются в ``__init__`` и на классе не
       видны вовсе, поэтому вторая линия — AST-разбор исходников ВСЕЙ иерархии
       MRO, поиск узлов ``self.<имя>`` (:func:`_self_attribute_names`, см. её
       докстринг — почему не текстовый поиск). Падает эта проверка ровно тогда,
       когда что-то из поверхности переименовали в проде, — то есть ловит именно
       переименование, а не отставание конкретного стаба (стабы намеренно куцые,
       у них нет большинства этих имён РЕАЛИЗОВАННЫМИ — есть только у настоящего
       класса, и только это здесь проверяется).

    2. ``_active_recipe_from_manifest`` — известный и намеренный пробел (S-29):
       у настоящего класса он есть, у ВСЕХ пяти дублёров — нет, поэтому
       ``_active_recipe_path()`` внутри хука на всех пяти идёт фолбэком
       (``orchestrator.get_config("observability_recipe_path")``), а не веткой
       манифеста. Вторая проверка фиксирует, что дублёр НЕ обзавёлся этим именем
       молча: появись оно — хук пойдёт другой веткой, и это должно быть
       осознанным решением автора правки, а не побочным эффектом рефакторинга
       стаба.
    """
    from multiprocess_framework.modules.app_module.orchestrator import GenericProcessManagerApp

    attrs: set[str] = set()
    for cls in GenericProcessManagerApp.__mro__:
        if cls is object:
            continue
        try:
            source = inspect.getsource(cls)
        except (OSError, TypeError):  # класс без доступного исходника — пропускаем молча
            continue
        attrs |= _self_attribute_names(source)

    missing = [
        name
        for name in ORCHESTRATOR_SURFACE_THE_HOOK_USES
        if not hasattr(GenericProcessManagerApp, name) and name not in attrs
    ]
    assert not missing, (
        f"configure_topology_engine читает у оркестратора имена, которых у настоящего класса нет: "
        f"{missing} — либо их переименовали в проде (тогда горячая пересборка падает "
        f"AttributeError на первом же switch), либо список свидетелей протух"
    )

    assert not hasattr(stub_cls, "_active_recipe_from_manifest"), (
        f"{stub_cls.__name__} обзавёлся _active_recipe_from_manifest — тогда _active_recipe_path() "
        "внутри configure_topology_engine идёт веткой манифеста, а не фолбэком на "
        "observability_recipe_path; тесты этого файла, что полагаются на фолбэк, надо перепроверить "
        "осознанно, а не как побочный эффект правки стаба"
    )
