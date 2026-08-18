# -*- coding: utf-8 -*-
"""Авторские тесты на ОПАСНОСТИ механизма провенанса при горячей пересборке (S-26).

Приёмочный набор рядом (``test_hot_rebuild_provenance_acceptance.py``) написан
независимым тестером по критериям и охраняет заявленное свойство: ключ, которого
нет в ``system.yaml``, приписан слою ``framework``. Этот файл охраняет другое —
то, что видно только изнутри механизма и чего критерии не спрашивали. Границу
провели инъекциями: кампания против приёмочного набора (6 поломок, все шесть
предсказаний совпали) оставила И5 **зелёной на всех пяти критериях** — приёмка
пришпиливает результат, но не дверь, в которую он вошёл. Тесты ниже начинаются
ровно с этой дыры.

Гарнитура общая с приёмочным файлом намеренно: два дублёра оркестратора значили
бы две модели одного шва, и они бы разошлись. Дублёр здесь один, чинить его — в
одном месте.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from multiprocess_framework.modules.process_module.configs.observability_layers import (
    APP_CONFIG_KEY,
    process_observability_layers,
)
from multiprocess_prototype.backend.config.schemas import SystemConfig, load_system_config
from multiprocess_prototype.backend.launch import load_topology_dict, sys_config_for_orchestrator
from multiprocess_prototype.backend.orchestrator_hooks import configure_topology_engine

from ._orchestrator_stub_contract import assert_stub_speaks_the_real_class_surface
from .test_hot_rebuild_provenance_acceptance import (
    BASE_TOPOLOGY_PATH,
    PROCESS_NAME,
    SYSTEM_YAML_PATH,
    _FakeChildProcess,
    _StubOrchestrator,
)

#: Ключи, которые в боевом ``system.yaml`` записаны СО ЗНАЧЕНИЕМ, равным дефолту
#: схемы: ``log_level``, ``console``, ``file``, ``retention_sweep_interval_sec``,
#: ``errors``. Литерал, а не вычисление: смысл теста в том, чтобы поймать шов,
#: который начнёт выбрасывать «значение как у дефолта» — а вычисленный из той же
#: схемы список сжался бы вместе с ним и промолчал.
#:
#: **Мерить надо ВАЛИДИРОВАННЫЕ значения**, а не сырой YAML против дефолта:
#: ``exclude_defaults`` сравнивает поля модели. Первый замер (2026-08-18) сравнил
#: ``raw["errors"]`` с ``ObservabilityConfig().errors.model_dump()`` и насчитал
#: четыре — сырая секция ``errors:`` частичная, полный дамп дефолта ей не равен
#: никогда, хотя после валидации значения совпадают. Ошибку нашло ревью; метод
#: сверки: ``getattr(sys_config.observability, k) == getattr(ObservabilityConfig(), k)``.
KEYS_WRITTEN_BUT_EQUAL_TO_DEFAULT = ("log_level", "console", "file", "retention_sweep_interval_sec", "errors")

#: Те же пять потерь, но в ПЛОСКОМ пространстве провенанса — девять ключей.
#: Пространства два и они не совпадают: ``errors`` — контейнер, в провенансе его
#: нет вовсе (есть листья ``errors.*``), а ``stats`` из верхнего списка не выпадает,
#: но два его листа выпадают: ``exclude_defaults`` рекурсивен и режет внутри
#: под-моделей тоже. Ассерт на ``prov["errors"]`` был бы поэтому вечно красным —
#: спрашивал бы у карты листьев про имя ветки.
PROVENANCE_LEAVES_LOSING_THE_APP_LAYER = (
    "console",
    "errors.enabled",
    "errors.include_stacktrace",
    "errors.level",
    "file",
    "log_level",
    "retention_sweep_interval_sec",
    "stats.enabled",
    "stats.log_level",
)


def _hot_proc_dict(sys_config: SystemConfig, *, twice: bool = False) -> tuple[dict, dict | None]:
    """Прогнать ГОРЯЧУЮ дорогу и вернуть ``proc_dict`` (и второй, если ``twice``).

    Тот же шов, что у приёмки: результат ``sys_config_for_orchestrator`` едет в
    дублёр оркестратора, ``configure_topology_engine`` конфигурирует настоящий
    ``FullReplacePlanner``, и ``proc_dict`` достаётся из его команд провизии.
    """
    orchestrator = _StubOrchestrator(
        sys_config_for_orchestrator(sys_config),
        app_config_path=str(SYSTEM_YAML_PATH),
        recipe_path=str(BASE_TOPOLOGY_PATH),
    )
    configure_topology_engine(orchestrator)
    planner = orchestrator._full_replace_planner
    assert planner is not None, "планировщик не сконфигурирован — дорога не поехала"

    def _one() -> dict:
        # Свежая топология на каждый вызов: normalize_blueprint мутирует вход.
        commands = planner.commands({"has_changes": True}, load_topology_dict(BASE_TOPOLOGY_PATH))
        by_name = {c["process_name"]: c["proc_dict"] for c in commands if c["cmd"] == "process.provision"}
        assert PROCESS_NAME in by_name, f"процесс {PROCESS_NAME!r} не пересобран"
        return by_name[PROCESS_NAME]

    first = _one()
    return first, (_one() if twice else None)


def _provenance(proc_dict: dict) -> dict[str, dict[str, str]]:
    return process_observability_layers(_FakeChildProcess(proc_dict)).provenance()


# --------------------------------------------------------------------------- Х1


def test_the_shipped_config_wins_over_the_file_on_disk() -> None:
    """Х1: ПМ обязан собирать из ДОСТАВЛЕННОГО конфига, а не перечитывать файл.

    Дыра, которую приёмка не видит (инъекция И5: подмена
    ``SystemConfig.model_validate(доставленный)`` на ``load_system_config()``
    оставила все пять критериев зелёными). Зелёными — потому что в этом
    репозитории дефолтный путь и путь из манифеста указывают на ОДИН файл.

    Цена в проде другая: лончер читает ``system.yaml`` **по пути из манифеста**
    (``launch.py``: ``load_system_config(app.system)``), а ``load_system_config()``
    без аргумента резолвит свой дефолт. Стенд с манифестом, указывающим на другой
    system.yaml, получил бы у ПМ ЧУЖОЙ слой L1 — и провенанс называл бы файл,
    которого оператор не правил, слоем ``app``, а его собственные правки —
    несуществующими. Ошибка не упала бы: она бы просто отвечала не про тот файл.

    Тест поэтому доставляет секцию, которой на диске НЕТ: ключ ``session_ttl_sec``
    в боевом файле отсутствует (это же свидетель К1 приёмки — там он обязан быть
    ``framework``), здесь он задан явно и обязан стать ``app``.
    """
    raw = yaml.safe_load(SYSTEM_YAML_PATH.read_text(encoding="utf-8"))
    raw["observability"] = {**(raw.get("observability") or {}), "session_ttl_sec": 111.0}
    shipped = SystemConfig.model_validate(raw)

    proc_dict, _ = _hot_proc_dict(shipped)
    section = proc_dict["config"][APP_CONFIG_KEY]

    assert section.get("session_ttl_sec") == 111.0, (
        "доставленный ключ не доехал до ребёнка — похоже, ПМ собрал не из того, что ему передали, "
        f"а из файла на диске (секция у ребёнка: {sorted(section)})"
    )
    entry = _provenance(proc_dict).get("session_ttl_sec")
    assert entry == {"layer": "app", "source": str(SYSTEM_YAML_PATH)}, (
        f"провенанс доставленного ключа: {entry!r}; ожидался слой app с адресом файла — иначе "
        "оператор увидит 'дефолт фреймворка' там, где значение задано конфигом"
    )


# --------------------------------------------------------------------------- Х2


def test_a_key_written_with_the_default_value_still_belongs_to_the_app() -> None:
    """Х2: «написано в файле» и «отличается от дефолта» — разные факты.

    ``exclude_unset`` (шов S-24) оставляет ключ, который оператор НАПИСАЛ, даже
    если значение совпало с дефолтом схемы. Соседний ``exclude_defaults`` выглядит
    почти так же и выбросил бы такие ключи молча — а на боевом файле их **пять из
    двенадцати**, и в плоском пространстве провенанса слой ``app`` теряют **девять**
    ключей: ``console``, ``file``, ``log_level``, ``retention_sweep_interval_sec``,
    ``errors.enabled``, ``errors.include_stacktrace``, ``errors.level``,
    ``stats.enabled``, ``stats.log_level`` (измерено ревью 2026-08-18: слои
    30/22 → 21/31). Провенанс ответил бы ``framework`` на ключ, который оператор
    видит собственными глазами в своём ``system.yaml``: он пошёл бы менять значение
    там, где, по ответу системы, значения нет.

    Замена ``exclude_unset`` на ``exclude_defaults`` — не выдумка: ровно этой
    подменой ревьюер проверял приёмку соседней задачи (S-25).
    """
    sys_config = load_system_config(SYSTEM_YAML_PATH)
    proc_dict, _ = _hot_proc_dict(sys_config)
    prov = _provenance(proc_dict)
    written = set((yaml.safe_load(SYSTEM_YAML_PATH.read_text(encoding="utf-8")).get("observability") or {}))
    shipped = proc_dict["config"][APP_CONFIG_KEY]

    # 1. Верхний уровень секции L1 — место, куда бьёт exclude_defaults.
    for key in KEYS_WRITTEN_BUT_EQUAL_TO_DEFAULT:
        assert key in written, (
            f"{key!r} больше не написан в system.yaml — свидетель протух, перемерьте список "
            "сравнением ВАЛИДИРОВАННЫХ значений с ObservabilityConfig() и объясните правку "
            "в том же коммите"
        )
        assert key in shipped, (
            f"{key!r} записан в system.yaml, но до ребёнка не доехал: шов выбросил ключ, "
            f"чьё значение совпало с дефолтом схемы (доехало: {sorted(shipped)})"
        )

    # 2. Плоское пространство провенанса — место, где это увидит оператор.
    for leaf in PROVENANCE_LEAVES_LOSING_THE_APP_LAYER:
        assert prov.get(leaf, {}).get("layer") == "app", (
            f"{leaf!r} задан в system.yaml, но провенанс называет слой {prov.get(leaf)!r} — "
            "оператору сказали 'дефолт фреймворка' про строку, которую он видит в своём файле"
        )


# --------------------------------------------------------------------------- Х3


def test_a_second_hot_rebuild_answers_exactly_like_the_first() -> None:
    """Х3: вторая пересборка подряд не меняет ни одного ответа провенанса.

    Секция L1 живёт в замыкании ``_build_proc_dicts`` и переиспользуется КАЖДЫМ
    switch за всю жизнь ПМ, а в ``proc_dict`` она попадает поверхностной копией
    (``dict(self._observability_section)``). Мутируй её кто-нибудь ниже по течению
    — второй switch раздал бы уже испорченную, и дефект был бы виден только на
    системе, которую переключали дважды. Такое ловится живьём и не ловится
    тестом, который собирает один раз.
    """
    sys_config = load_system_config(SYSTEM_YAML_PATH)
    first, second = _hot_proc_dict(sys_config, twice=True)
    assert second is not None

    assert first["config"][APP_CONFIG_KEY] == second["config"][APP_CONFIG_KEY], (
        "секция L1 второй пересборки отличается от первой — замыкание раздаёт мутированную копию"
    )
    prov_first, prov_second = _provenance(first), _provenance(second)
    diff = {k for k in set(prov_first) | set(prov_second) if prov_first.get(k) != prov_second.get(k)}
    assert not diff, f"провенанс разошёлся между первой и второй пересборкой по ключам: {sorted(diff)}"


# --------------------------------------------------------------------------- Х4


def test_two_processes_of_one_build_do_not_share_mutable_layer_state() -> None:
    """Х4: два процесса одной сборки не делят вложенные словари слоя L1.

    Гарантия есть, но она ПОБОЧНАЯ, и это главное, что стоит здесь записать.
    Кладётся секция поверхностной копией (``assembler``: ``dict(section)``), то
    есть вложенный ``channels`` был бы общим объектом на все процессы; разводит
    их шаг нормализации в конце сборки — ``merge_with_defaults`` делегирует
    каноническому ``deep_merge``, а тот делает deepcopy (``helpers.py``, там это
    сказано словами). Сделай кто-нибудь этот шаг условным или поверхностным ради
    скорости — процессы начали бы делить изменяемое состояние конфига, и правка
    у одного проявлялась бы у соседа.

    Измерено (2026-08-18): сегодня не делят ни верхний словарь, ни ``channels``.
    """
    sys_config = load_system_config(SYSTEM_YAML_PATH)
    orchestrator = _StubOrchestrator(
        sys_config_for_orchestrator(sys_config),
        app_config_path=str(SYSTEM_YAML_PATH),
        recipe_path=str(BASE_TOPOLOGY_PATH),
    )
    configure_topology_engine(orchestrator)
    planner = orchestrator._full_replace_planner
    assert planner is not None

    topology = load_topology_dict(BASE_TOPOLOGY_PATH)
    # Второй процесс — копия первого под другим именем: топология фундамента несёт
    # один процесс, а свойство «не делят» проверяется минимум на двух.
    procs = topology.get("processes") or []
    assert procs, "в базовой топологии нет процессов — проверять разделение не на чем"
    twin = {**procs[0], "process_name": procs[0]["process_name"] + "_двойник"}
    topology["processes"] = [*procs, twin]

    commands = planner.commands({"has_changes": True}, topology)
    built = {c["process_name"]: c["proc_dict"] for c in commands if c["cmd"] == "process.provision"}
    a, b = built[PROCESS_NAME], built[twin["process_name"]]
    sec_a: dict[str, Any] = a["config"][APP_CONFIG_KEY]
    sec_b: dict[str, Any] = b["config"][APP_CONFIG_KEY]

    assert sec_a is not sec_b, "верхний словарь L1 — один объект на два процесса"
    nested = next((k for k, v in sec_a.items() if isinstance(v, dict)), None)
    assert nested is not None, "в секции L1 не осталось вложенных словарей — свидетель протух"
    assert sec_a[nested] is not sec_b[nested], (
        f"вложенный {nested!r} — общий объект: правка конфига у одного процесса видна у другого"
    )

    sec_a[nested]["_проверка_разделения"] = 1
    assert "_проверка_разделения" not in sec_b[nested], "изменение у одного процесса протекло к соседу"


# --------------------------------------------------------------------------- Х5


#: Поверхность оркестратора и сама проверка берутся из ОДНОГО места —
#: ``_orchestrator_stub_contract`` (импорт выше). Список имён здесь не дублируется
#: с 2026-08-18 (S-29); тело проверки — тоже с 2026-08-18 (ревью, находки Д1/З2):
#: до этой правки здесь жила самостоятельная копия ``assert_stub_speaks_the_real_
#: class_surface`` (заведена первой, S-26, до появления общего хелпера в S-29) —
#: те же 137 строк, тот же текстовый поиск по ``blob`` исходников, та же слепота к
#: комментарию, упоминающему старое имя текстом (парная инъекция 2026-08-18 красила
#: эту копию так же ложно-зелёно, как и хелпер). Две копии одного факта — ровно тот
#: класс дефекта, который закрывает S-29, поэтому копия снята в пользу вызова
#: общей функции; докстринг теста сохранён — история и цена измерения остаются
#: здешними, а не хелпера.


def test_the_stub_orchestrator_speaks_the_real_class_surface() -> None:
    """Х5: дублёр оркестратора обязан совпадать по именам с НАСТОЯЩИМ классом.

    Дублёр — это фейк-гарнитура, а фейк доказывает сам себя. Цена измерена
    ревью 2026-08-18: переименование ``live_process_config`` в
    ``process_manager_process.py`` оставило зелёными **все 69** тестов каталога
    ``backend/tests``, включая девять здешних, — при том что в проде
    ``orchestrator_hooks`` берёт это имя на КАЖДОМ switch и упал бы
    ``AttributeError``. Живой вызывающий у имени один, дублёров с его копией —
    пять; молчание пятерых перевешивает.

    Тест сверяет имена, а не поведение: поведение дублёра намеренно куцее.
    Именно имена и уезжают при рефакторинге незамеченными.

    Известное расхождение, которое тест НЕ закрывает и закрывать не должен:
    ``_active_recipe_from_manifest`` у настоящего класса есть, а у дублёра нет,
    поэтому ``_active_recipe_path()`` в тестах идёт фолбэком на
    ``observability_recipe_path``, а в проде — веткой манифеста. На здешние
    ассерты это не влияет (``recipe_source`` никто не проверяет), но ветка
    исполняется не та, и знать об этом лучше из теста, чем из инцидента.
    """
    assert_stub_speaks_the_real_class_surface(_StubOrchestrator)


if __name__ == "__main__":  # pragma: no cover — ручной прогон
    raise SystemExit(pytest.main([__file__, "-v"]))
