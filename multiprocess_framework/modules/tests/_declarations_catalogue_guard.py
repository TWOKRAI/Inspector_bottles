# -*- coding: utf-8 -*-
"""Страж сетки каталога метрик фреймворка — тело вердикта (Ф0.1 «trust gate»).

Не тест (имя начинается с подчёркивания — pytest его не собирает), а два
предмета, которыми пользуются страж в ``conftest.py`` рядом и тесты в
``test_declarations_registry_hazards.py``: :func:`warm_producers` и
:func:`catalogue_verdict`.

**Почему вердикт вынесен в функцию, а не написан внутри фикстуры.** Сторож живёт
в teardown session-фикстуры, то есть срабатывает один раз за прогон и только
если что-то сломалось. Проверить сам сторож на такой площадке нечем: чтобы
увидеть его красноту, надо испортить прогон. Отдельная функция от состояния
процесса не зависит и проверяется обычными тестами — включая тот случай,
который сторож обязан РАЗЛИЧАТЬ (см. ниже).

**Два разных факта под одним симптомом.** Пустой (или неполный) каталог значит
либо «объявления утекли», либо «производителей никто не импортировал». Второе —
не дефект, а несобранная сцена: реестр наполняется ИМПОРТОМ, и прогон одного
файла тестов законно живёт без единого производителя. Сторож, который краснеет
на обоих, так же легко и позеленеет, ничего не проверив (класс «ноль наблюдений
выглядит результатом наблюдения»), поэтому здесь эти факты разведены:

1. Перед снятием каталога сцена ДОБИРАЕТСЯ до полной —
   :func:`~...configs.telemetry_publish_config.ensure_framework_producers`.
2. Догрев **не может замаскировать утечку**, и это не рассуждение, а свойство
   ``import``: после первого раза оператор модуль не исполняет, а значит
   стёртое из реестра имя повторным импортом не возвращается. Свойство
   сторожит тест ``test_warm_up_cannot_resurrect_a_wiped_declaration``.
3. Вердикт всё равно спрашивает ОТДЕЛЬНО, загрузились ли производители, и при
   «нет» говорит про несобранную сцену, а не про утечку: догрев может оказаться
   заглушкой (ровно эта инъекция описана в
   ``process_module/tests/test_metric_catalog_producer_hazards.py``), и тогда
   слово «утечка» отправило бы читателя искать несуществующего виновника.
"""

from __future__ import annotations

import sys
from typing import Optional, Sequence, Tuple

from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    ensure_framework_producers,
)

#: Пять метрик фреймворка — ЛИТЕРАЛ из задачи 0.1, а не значение, вычисленное тем
#: же кодом, который проверяется: ожидание, выведенное из проверяемого, согласится
#: с любым ответом, включая пустой. Сверено чтением: ``fps``, ``latency_ms``,
#: ``effective_hz``, ``cycle_duration_ms`` объявляет ``heartbeat/telemetry.py``,
#: ``shm`` — ``heartbeat/process_heartbeat.py``.
EXPECTED_FRAMEWORK_METRICS: Tuple[str, ...] = (
    "cycle_duration_ms",
    "effective_hz",
    "fps",
    "latency_ms",
    "shm",
)

#: Хвосты имён модулей-производителей. Хвосты, а не полные имена: каталог
#: ``modules/`` лежит в ``sys.path`` (см. conftest'ы), поэтому один и тот же файл
#: живёт в ``sys.modules`` под двумя написаниями — ``multiprocess_framework.
#: modules.process_module.heartbeat.telemetry`` и ``process_module.heartbeat.
#: telemetry``. Проверка по полному имени объявила бы «не загружен» там, где
#: модуль загружен под вторым написанием.
_PRODUCER_SUFFIXES = (
    "process_module.heartbeat.telemetry",
    "process_module.heartbeat.process_heartbeat",
)


def loaded_producers() -> Tuple[str, ...]:
    """Какие модули-производители метрик реально лежат в ``sys.modules``.

    Положительное свидетельство, а не отсутствие жалоб: пустой кортеж означает
    «сцена не собрана» и запрещает вердикту говорить слово «утечка».
    """
    return tuple(name for name in list(sys.modules) if name.endswith(_PRODUCER_SUFFIXES))


def warm_producers() -> Tuple[str, ...]:
    """Добрать каталог до полного и вернуть загруженных производителей.

    Идемпотентна ровно настолько, насколько идемпотентен ``import``: первый раз
    исполняет модули (и их объявления), дальше — поиск в ``sys.modules``.
    Воскресить стёртое объявление НЕ может — см. шапку, пункт 2.
    """
    ensure_framework_producers()
    return loaded_producers()


def catalogue_verdict(catalogue: Sequence[str], *, producers: Sequence[str]) -> Optional[str]:
    """``None``, если каталог совпал с литералом; иначе — текст жалобы.

    Args:
        catalogue: то, что вернул ``declared_metrics()``.
        producers: то, что вернул :func:`loaded_producers` — ОТДЕЛЬНЫЙ факт,
            без которого расхождение не читается однозначно.

    Returns:
        ``None`` при совпадении. Иначе строка, называющая лишнее и пропавшее
        ПОИМЁННО — «каталог разошёлся» без имён отправляет читателя грепать
        весь прогон.
    """
    expected = set(EXPECTED_FRAMEWORK_METRICS)
    actual = set(catalogue)
    extra = sorted(actual - expected)
    missing = sorted(expected - actual)
    if not extra and not missing:
        return None

    if not producers:
        return (
            "каталог метрик фреймворка не совпал с литералом "
            f"{EXPECTED_FRAMEWORK_METRICS!r} (получили {tuple(catalogue)!r}), НО модули-"
            "производители не загружены (sys.modules пуст на "
            f"{_PRODUCER_SUFFIXES!r}). Это НЕ утечка объявлений, а несобранная сцена: "
            "реестр наполняется импортом. Чинить нужно догрев "
            "(ensure_framework_producers), а не искать тест-виновник — "
            f"лишние={extra!r}, пропавшие={missing!r}"
        )

    return (
        "каталог метрик фреймворка на закрытии сессии разошёлся с литералом "
        f"{EXPECTED_FRAMEWORK_METRICS!r}: получили {tuple(catalogue)!r}. "
        f"лишние={extra!r}, пропавшие={missing!r}. "
        f"Производители загружены ({sorted(producers)!r}), значит расхождение — УТЕЧКА "
        "объявления из какого-то теста этой сессии, а не несобранная сцена. "
        "Пропавшее имя повторным импортом не вернётся (модуль уже в sys.modules): "
        "виновник — тест, унёсший чужое объявление сплошной очисткой плоскости "
        "(forget_declarations(kind=...)) без снимка. Лишнее имя — тест, объявивший "
        "своё и не убравший за собой forget_declarations(names=[...])"
    )
