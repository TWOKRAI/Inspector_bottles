# -*- coding: utf-8 -*-
"""Task 2.9, шаг 4 — программный страж покрытия схемы против РЕАЛЬНОЙ проводки.

Автор — разработчик (внутренний hazard-тест механизма, пишется ПОСЛЕ реализации), не
независимый тестер: контрактный набор ДО реализации уже написан и лежит в
``test_f2_task29_verifier_covers_every_leaf.py`` (RED-режим, база 11 failed/51 passed).
Этот файл — ДОБАВОЧНЫЙ сторож того же свойства другим объективом, а не замена.

Отличие от ``TestSchemaCoverageGuard`` тестера в соседнем файле:

* тестер перечисляет 52 листа СХЕМЫ РУКАМИ (словарь ``_LEAF_CASES``, составленный один
  раз по чтению ``observability_config.py``/``observation_policy.py``) и сверяет каждый
  против ПОЛНОСТЬЮ ПУСТОГО ``effective={}`` — так он ловит «лист выпал из ``expected``
  целиком»;
* этот страж получает МНОЖЕСТВО листьев ОБХОДОМ ``ObservabilityConfig.model_fields``
  (рекурсия по SchemaBase-подсекциям — тем же правилом, что ``unread_schema_fields``
  в ``test_f2_task22_schema_wiring.py``, тот же образец стража, что просит спека Task 2.9
  шаг 4), а effective — РЕАЛЬНЫЙ readback через ``_real_wired`` (config.reload по живому
  ``CommandManager``/``LoggerManager``/``ErrorManager``, тот же харнесс, что критерии 3-5
  Task 2.2). Так страж ловит ВТОРОЙ класс дефекта, недоступный тестеру с пустым
  ``effective``: «путь есть в ``expected``, а живая проводка readback отдаёт его под
  ДРУГИМ именем» (ровно M2 — ``stats.enabled``/``plane_disabled``) — с пустым ``{}``
  effective любой путь automatически ``unverifiable``, и расхождение имён не отличимо
  от «читателя нет вовсе».

Множество путей — не переписанный руками список: добавь новое поле в
``ObservabilityConfig`` (или под-схему) — оно попадёт в обход и получит собственный
параметризованный кейс без правки этого файла, если тип поля покрыт generic-правилом
``_probe_value`` (bool/int/float/непустая str). Требует ручного разбора (см.
``_OVERRIDES`` ниже) только там, где generic-флип НЕ валиден: validated level-строки
(``canonical_level_or_raise``, ровно пять полей во всей схеме) и dict-листья с
провалидированной внутренней формой (``observation.rules`` → ``Dict[str, MetricRule]``)
или просто нуждающиеся в представительном непустом значении.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, Tuple

import pytest

from multiprocess_framework.modules.data_schema_module import SchemaBase
from multiprocess_framework.modules.logger_module.core.windowed_voice import reset_voices_policy
from multiprocess_framework.modules.process_module.configs.observability_config import (
    ObservabilityConfig,
)

from .test_f2_task22_schema_wiring import _real_wired, _reload


@pytest.fixture(autouse=True)
def _isolated_voices_policy() -> Iterator[None]:
    """Политика окон голоса — ПРОЦЕССНАЯ (модульный singleton в ``windowed_voice``),
    не привязанная к конкретному ``_real_wired``-процессу: параметризованные кейсы
    ``voices.*`` (``config.reload`` в реальном харнессе действительно мутирует её
    через ``apply_voices_policy``) обязаны не переживать свой собственный тест —
    иначе следующий кейс (или вовсе другой тестовый файл в том же процессе pytest)
    увидит след соседа вместо схемного дефолта. Тот же приём и та же причина, что
    у ``test_voices_policy_road_guards.py::_isolated_policy`` — найдено ПОСЛЕ
    первого прогона полного гейта: без сброса
    ``test_introspect_commands.py::test_missing_managers_are_omitted_not_faked``
    (сверяет литералы ``default_window_sec``/``max_tracked_keys``/…) красный,
    если этот файл коллекции отработал раньше по алфавиту, а порядковый тест
    ``test_declarations_leak_order_independence.py`` тем же следом краснеет тоже —
    оба чужие по имени, оба являются производной ОДНОЙ утечки, а не отдельными
    дефектами."""
    reset_voices_policy()
    yield
    reset_voices_policy()


def _schema_leaf_paths(model_cls: type) -> list:
    """Листовые пути схемы: под-``SchemaBase`` разворачиваются рекурсивно.

    Правило — БУКВАЛЬНО то же, что у ``unread_schema_fields._schema_leaf_paths``
    (Task 2.2, тот же файл, соседняя проверка): ``issubclass(field.annotation,
    SchemaBase)`` решает, спускаться ли внутрь. Копия, а не импорт чужой приватной
    функции — этот страж не должен краснеть/зеленеть от правки СОСЕДНЕЙ проверки
    Task 2.2, только от правки самой схемы; расхождению между копиями взяться
    неоткуда, потому что правило — атрибут схемы (`SchemaBase`), а не решение автора.
    """
    out: list = []
    for name, field in model_cls.model_fields.items():
        ann = field.annotation
        if isinstance(ann, type) and issubclass(ann, SchemaBase):
            out.extend((name, *rest) for rest in _schema_leaf_paths(ann))
        else:
            out.append((name,))
    return out


#: Явные значения для листьев, где generic-правило `_probe_value` не годится:
#:
#: * validated level-строки — сверены с полем, где стоит
#:   ``@field_validator(..., mode="before") canonical_level_or_raise``: их РОВНО ПЯТЬ
#:   во всей схеме (``log_level``, ``errors.level``, ``stats.log_level``,
#:   ``sampling_max_level``, ``history.level``) — generic ``f"{default}__probe"``
#:   значило бы «неизвестный уровень» и падало бы валидацией;
#: * dict-листья — представительное НЕПУСТОЕ значение своей формы. Для большинства
#:   (``channels``/``scopes``/``loggers``/``logger_groups``/``errors.channels``/
#:   ``stats.channels``/``documents.config``) форма — ``Dict[str, Any]`` произвольная,
#:   но generic-правило не знает, что положить нетривиального; ``observation.rules``
#:   — единственный, где форма ПРОВАЛИДИРОВАНА подтипом (``Dict[str, MetricRule]``),
#:   и случайный dict уронил бы Pydantic-валидацию.
_OVERRIDES: Dict[Tuple[str, ...], Any] = {
    ("log_level",): "WARNING",
    ("errors", "level"): "ERROR",
    ("stats", "log_level"): "WARNING",
    ("sampling_max_level",): "WARNING",
    ("history", "level"): "WARNING",
    ("log_directory",): "/tmp/f2_t29_probe_dir",
    # `type` — способ записи определить новый канал самостоятельно
    # (``observability_refs.unknown_observability_refs``): без него имя, не
    # входящее в реестр ЖИВОГО менеджера, отвергается как «ссылка в пустоту»
    # ДО применения (`config.reload` вернул бы `success: False`, до вердикта
    # дело не дошло бы вовсе — воспроизведено при первом прогоне стража).
    ("channels",): {"probe_channel": {"enabled": False, "type": "file"}},
    # Ссылка на РЕАЛЬНЫЙ известный канал (`console` — дефолт `LoggerManagerConfig`,
    # `_real_wired` поднимает настоящий `LoggerManager`), а не самоопределяемое имя:
    # список `scopes.<имя>.channels` сверяется с каталогом известных каналов, а не
    # с наличием `type` у СВОЕЙ записи (та проверка — только для `channels.<имя>`).
    ("scopes",): {"BUSINESS": {"channels": ["console"]}},
    ("loggers",): {"some.prefix": {"level": "DEBUG"}},
    ("logger_groups",): {"noisy": ["some.prefix"]},
    ("errors", "channels"): {"errors_file": {"enabled": False}},
    # `_real_wired` не поднимает StatsManager (см. докстринг класса теста) —
    # каталог известных stats-каналов пуст независимо от имени, поэтому `type`
    # обязателен здесь тем же доводом, что у `channels` выше.
    ("stats", "channels"): {"file_stats": {"enabled": False, "type": "file"}},
    ("documents", "config"): {"db_path": "probe.db"},
    ("observation", "rules"): {"processes.*.state.plugins.*.fps": {"enabled": False}},
}


def _default_at(path: Tuple[str, ...]) -> Any:
    """Схемный дефолт по пути — читается у ЖИВОГО экземпляра (не у ``FieldInfo``):
    под-секции используют ``default_factory``, и обходить разницу default/default_factory
    вручную незачем, когда экземпляр уже умеет её разрешить сам."""
    node: Any = ObservabilityConfig()
    for part in path:
        node = getattr(node, part)
    return node


def _probe_value(path: Tuple[str, ...]) -> Any:
    """Значение запроса — ОТЛИЧНОЕ от схемного дефолта (правило проекта: совпадение
    с дефолтом маскирует «ничего не применилось»). ``_OVERRIDES`` — точечно там, где
    generic-флип невалиден; иначе — по ТИПУ дефолта."""
    if path in _OVERRIDES:
        return _OVERRIDES[path]
    default = _default_at(path)
    if isinstance(default, bool):
        return not default
    if isinstance(default, int):
        return default + 1
    if isinstance(default, float):
        return default + 1.0
    if isinstance(default, str):
        return f"{default}__probe" if default else "probe"
    raise AssertionError(
        f"{'.'.join(path)}: нет ни явного override, ни generic-правила для типа "
        f"{type(default).__name__} — страж не умеет собрать пробное значение"
    )


def _nest(path: Tuple[str, ...], value: Any) -> Dict[str, Any]:
    """``("stats", "enabled")``, ``False`` → ``{"stats": {"enabled": False}}``."""
    out: Dict[str, Any] = {}
    node = out
    for part in path[:-1]:
        child: Dict[str, Any] = {}
        node[part] = child
        node = child
    node[path[-1]] = value
    return out


#: Обход СХЕМЫ, а не переписанный вручную список: 52 листа на дату написания (совпадает
#: со счётом независимого тестера в соседнем файле, посчитанным другим способом —
#: ручным перечислением по чтению кода). Совпадение чисел, посчитанных ДВУМЯ разными
#: методами, — не совпадение: оба метода обходят одну и ту же схему одним и тем же
#: правилом (SchemaBase-рекурсия), разница только в том, кто печатает список.
_LEAF_PATHS = _schema_leaf_paths(ObservabilityConfig)

#: Листья, у которых ``_real_wired`` даёт ЖИВОГО получателя readback'а СЕГОДНЯ
#: (измерено прогоном, не предположено): logger-плоскость (скаляры и
#: dict-секции — их читает настоящий `LoggerManager`), errors.level/
#: include_stacktrace (настоящий `ErrorManager`), commands.log_success
#: (настоящий `CommandManager`), voices.* (механизм процессный, живого объекта
#: не требует вовсе), session_ttl_sec и четыре поля history.* без
#: enabled/db_path (обе бухгалтерии читают разрешённые слои процесса
#: напрямую, живого хаба/heartbeat'а для этого не нужно). Для НИХ страж
#: требует БОЛЬШЕГО, чем «не нигде»: они обязаны остаться ``confirmed`` —
#: иначе инъекция «убрать ветку readback» (акс. критерий Task 2.9, шаг 4)
#: превращала бы `confirmed` в легитимный `unverifiable`, и слабый инвариант
#: ниже её не заметил бы (воспроизведено: убрать ветку `command` в
#: `observability_effective` → `commands.log_success` уходит в `unverifiable`
#: ПОИМЁННО, что само по себе не нарушает «не нигде» — слабый инвариант
#: остался бы зелёным, доказывая, что для ЭТОГО класса регрессии нужна
#: проверка сильнее).
#:
#: Остальные листья (``stats.*``, ``heartbeat_interval_sec``, ``documents.*``,
#: ``errors.enabled``/``errors.channels``, ``events.*``, ``flight.*``,
#: ``observation.*``, ``history.enabled``/``history.db_path``) законно
#: остаются ``unverifiable`` в ЭТОМ харнессе — нет живого StatsManager/
#: heartbeat/hub/document-стока/подходящего канала, а не дефект — на них
#: держит только слабый инвариант «не нигде».
_EXPECTED_CONFIRMED_UNDER_REAL_WIRING: frozenset = frozenset(
    {
        ("log_level",),
        ("log_directory",),
        ("scopes",),
        ("loggers",),
        ("logger_groups",),
        ("session_ttl_sec",),
        ("retention_days",),
        ("retention_total_mb",),
        ("compress_rotated",),
        ("retention_sweep_interval_sec",),
        ("sampling_first_n",),
        ("sampling_every_mth",),
        ("sampling_burst_reset_sec",),
        ("sampling_max_level",),
        ("errors", "level"),
        ("errors", "include_stacktrace"),
        ("commands", "log_success"),
        ("voices", "default_window_sec"),
        ("voices", "escalate_after_repeats"),
        ("voices", "max_tracked_keys"),
        ("voices", "stale_windows"),
        ("history", "level"),
        ("history", "max_rows"),
        ("history", "max_age_sec"),
        ("history", "purge_interval_sec"),
    }
)


class TestSchemaCoverageGuardAgainstRealWiring:
    """Инвариант шага 2/4 Task 2.9 — против ЖИВОЙ проводки, не выдуманного effective.

    Каждый лист схемы, поданный ОДИН РАЗ в ``config.reload`` реального процесса,
    обязан оказаться ЛИБО в ``checked`` (readback его знает и сверил), ЛИБО в
    ``unverifiable`` (readback его не отдаёт — законно для секций без живого
    получателя в ``_real_wired``, например ``documents``/``observation``/``stats``:
    этот харнесс не поднимает StatsManager/heartbeat, только logger/error/command).
    Недопустимо ОДНО: ``checked == 0`` И ``unverifiable == []`` одновременно —
    лист, пропавший из вердикта молча.

    Для подмножества :data:`_EXPECTED_CONFIRMED_UNDER_REAL_WIRING` — заявление
    СИЛЬНЕЕ: не просто «не нигде», а буквально ``confirmed``. Без этой половины
    страж не ловит регрессию класса «readback-ветка удалена у поля, у которого
    БЫЛ живой получатель» — такое поле легитимно превращается в ``unverifiable``
    (слабый инвариант промолчит), а именно эту регрессию называет акс. критерий
    Task 2.9 шага 4 (инъекция «убрать ветку readback у commands.log_success»).
    """

    @pytest.mark.parametrize("path", _LEAF_PATHS, ids=[".".join(p) for p in _LEAF_PATHS])
    def test_leaf_is_checked_or_named_never_nowhere(self, path: Tuple[str, ...]) -> None:
        value = _probe_value(path)
        request = _nest(path, value)
        leaf_name = ".".join(path)

        with _real_wired(f"guard_{'_'.join(path)}") as (_process, _logger, _error, cm):
            res = _reload(cm, request)

        assert res["success"] is True, f"{leaf_name}: config.reload не применился: {res}"
        verified = res["verified"]
        assert not (verified["checked"] == 0 and verified["unverifiable"] == []), (
            f"{leaf_name}: подан {request!r}, а вердикт не проверил ЭТОТ путь и не назвал его "
            f"непроверяемым — лист пропал из вердикта молча (состояние «нигде»): {verified}"
        )
        if path in _EXPECTED_CONFIRMED_UNDER_REAL_WIRING:
            assert verified["checked"] >= 1 and verified["unverifiable"] == [], (
                f"{leaf_name}: у этого листа ЕСТЬ живой получатель readback'а в _real_wired, "
                f"а вердикт не 'confirmed' — похоже, ветка readback пропала: {verified}"
            )
