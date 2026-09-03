"""Тесты владения singleton-секцией «Пути» (`__paths__`) в `build_plugin_sections`.

RED-фаза (Task fix/plugins-paths-section-cache, worktree paths-cache): на коммите,
где писались эти тесты, `build_plugin_sections()` ЕЩЁ НЕ принимает параметр
`paths_cache` — весь файл обязан падать с `TypeError: unexpected keyword argument
'paths_cache'`. Это ожидаемый и единственно верный результат прогона.

Контракт (см. промпт задачи, домыслы явно помечены "ДОГАДКА"):
- `build_plugin_sections(services, *, ..., paths_cache: dict | None = None)`
- `paths_cache` — держатель singleton-секций, ПРИНАДЛЕЖАЩИЙ вызывающему (вкладке).
  Один и тот же dict в двух вызовах → одна и та же секция «Пути» (П1).
  Разные dict-держатели → разные секции, даже при равных по значению `services` (П2).
- `paths_cache=None` → держатель локален вызову, секция не переживает сам вызов
  и не оседает в модульном (глобальном) состоянии `_sections` (П3).
- Секция «Пути» живёт не дольше своего держателя: когда dict-держатель, переданный
  вызывающим, уничтожен, секция становится недостижимой вместе с ним (П4).
  ДОГАДКА: реализация не должна прятать секцию за отдельной структурой, живущей
  дольше переданного `paths_cache` (например, WeakKeyDictionary с ключом `id(cache)` —
  тогда переиспользование id после сборки мусора склеило бы чужие секции).

Секция «Пути» — обычный python-объект (не QWidget), её `.widget()` ленив и здесь
не вызывается: Qt-виджет тестам не нужен, offscreen-платформа не требуется по сути
контракта (но команда прогона задаёт QT_QPA_PLATFORM=offscreen на случай, если модуль
`_sections` всё же тянет Qt-импорты на уровне модуля).

Покрывает:
- test_same_holder_returns_same_paths_section        — П1
- test_different_holders_return_different_sections   — П2, включая равные-по-значению services
- test_no_holder_leaves_no_module_level_state         — П3, weakref + gc
- test_holder_lifetime_bounds_section_lifetime        — П4, weakref + gc
"""

from __future__ import annotations

import dataclasses
import gc
import weakref

from multiprocess_prototype.frontend.widgets.tabs.plugins._sections import (
    build_plugin_sections,
)

from ._helpers import make_plugins_services

_PATHS_KEY = "__paths__"


def _paths_spec(specs):
    """Найти SectionSpec секции «Пути» в списке, отданном build_plugin_sections."""
    for spec in specs:
        if spec.key == _PATHS_KEY:
            return spec
    raise AssertionError(f"секция с key={_PATHS_KEY!r} не найдена среди {[s.key for s in specs]}")


def _paths_section_weakref(services, paths_cache):
    """Построить секцию «Пути» через build_plugin_sections и вернуть weakref на неё.

    Не возвращает и не удерживает ничего, кроме weakref: specs/spec/section — явно
    удалены из локального стека этой функции до return, иначе тест П3/П4 был бы
    зелёным по неверной причине (живая ссылка через фрейм, а не через кэш).
    """
    specs = build_plugin_sections(services, paths_cache=paths_cache)
    spec = _paths_spec(specs)
    section = spec.factory(None)
    ref = weakref.ref(section)
    del section
    del spec
    del specs
    return ref


def test_same_holder_returns_same_paths_section():
    """П1: один и тот же dict-держатель → одна и та же секция «Пути» между вызовами.

    Если сломать: вкладка после refresh_catalog() (второй вызов build_plugin_sections
    с тем же paths_cache) получит НОВЫЙ объект секции «Пути» — подписка секции на
    catalog_updated из первого объекта останется висеть на выброшенном экземпляре,
    а новый экземпляр сигналов не получит. Секция «Пути» в GUI перестанет обновляться.
    """
    services = make_plugins_services()
    cache: dict = {}

    specs_first = build_plugin_sections(services, paths_cache=cache)
    specs_second = build_plugin_sections(services, paths_cache=cache)

    section_first = _paths_spec(specs_first).factory(None)
    section_second = _paths_spec(specs_second).factory(None)

    assert section_first is section_second


def test_different_holders_return_different_sections():
    """П2: разные dict-держатели → разные секции, даже при РАВНЫХ по значению services.

    AppServices — frozen dataclass: два независимо собранных экземпляра с одинаковой
    начинкой равны (`==`) и хешируются одинаково. Если реализация ошибочно кладёт
    секцию в глобальный кэш по ключу `services` (а не по держателю, который ей дал
    вызывающий), то два разных держателя с равными services получат ОДНУ и ту же
    секцию — то есть утечку состояния между двумя независимыми вкладками/вызовами.

    Строим "два отдельных, но равных" AppServices через dataclasses.replace() без
    изменений: это два РАЗНЫХ экземпляра контейнера (проверено `is not` ниже), поля
    которых — те же самые объекты (значит равны по построению) — это честнее, чем
    вызывать make_plugins_services() дважды: там под капотом создаются НЕЗАВИСИМЫЕ
    Fake-объекты без __eq__ (identity-equality), и два вызова дали бы services_a !=
    services_b — сам сценарий "равные, но разные" не собрался бы.
    """
    services_a = make_plugins_services()
    services_b = dataclasses.replace(services_a)
    assert services_a is not services_b
    assert services_a == services_b
    assert hash(services_a) == hash(services_b)

    cache_a: dict = {}
    cache_b: dict = {}

    specs_a = build_plugin_sections(services_a, paths_cache=cache_a)
    specs_b = build_plugin_sections(services_b, paths_cache=cache_b)

    section_a = _paths_spec(specs_a).factory(None)
    section_b = _paths_spec(specs_b).factory(None)

    assert section_a is not section_b


def test_no_holder_leaves_no_module_level_state():
    """П3: paths_cache=None → секция не оседает в модульном состоянии `_sections`.

    Если сломать: модуль `_sections` держит singleton-секцию «Пути» сам (модульная
    глобальная переменная вместо переданного вызывающим держателя) — тогда секция
    переживёт оба вызова этого теста даже без единого dict-держателя, weakref после
    gc.collect() останется живым, и разные вкладки/тесты процесса начнут незаметно
    делить одну и ту же секцию «Пути» без какого-либо paths_cache в подписи вызова.
    """
    services = make_plugins_services()

    ref_first = _paths_section_weakref(services, None)
    ref_second = _paths_section_weakref(services, None)

    gc.collect()

    assert ref_first() is None
    assert ref_second() is None


def test_holder_lifetime_bounds_section_lifetime():
    """П4: секция «Пути» не переживает уничтожение своего dict-держателя.

    Если сломать: реализация регистрирует секцию во внутренней структуре, живущей
    дольше переданного paths_cache (например, по `id(cache)` в отдельном модульном
    реестре) — тогда после удаления единственной внешней ссылки на cache и gc.collect()
    секция всё равно останется достижимой (утечка), а при переиспользовании Python'ом
    того же id() для нового dict-держателя новый держатель рискует получить чужую,
    устаревшую секцию «Пути».
    """
    services = make_plugins_services()
    cache: dict = {}

    ref = _paths_section_weakref(services, cache)

    del cache
    gc.collect()

    assert ref() is None
