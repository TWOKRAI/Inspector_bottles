# -*- coding: utf-8 -*-
"""
Спутник рецепта — machine-owned файл слоя L2 (Task 5.12, шаг 7).

``recipes/foo.yaml`` (пишет человек) ↔ ``recipes/foo.observability.yaml``
(пишет машина). Граница проходит по ФАЙЛАМ, а не по дисциплине «аккуратно
патчить чужой YAML»: аккуратность уже подводила — GUI-save round-трипнул
``system.yaml`` через ``safe_dump(model_dump)`` и стёр все комментарии
(зафиксировано отдельным уроком проекта). Разделив файлы, мы делаем этот класс
ошибки невозможным, а не маловероятным.

Форма спутника — та же секция ``observability``, что в рецепте
(``defaults`` + ``processes[<имя>]``), поэтому загрузка не требует отдельной
ветки: он читается тем же ``resolve_recipe_section``.

**Спутник не входит в БАЗУ слоя L2 (ФР-3).** База — долька самого рецепта; её
собирают ассемблеры, конверт switch'а и ``orchestrator_observability_config``,
и все они спутника не читают. Наложение живёт ровно в одном месте —
:func:`compose_over_base`, и оно исполняется последним у каждого потребителя.
Причина в том, что слой заменяется целиком, а база — нет: попади спутник в
базу, снятый из него ключ остался бы в конфиге процесса навсегда.

Запись атомарная (tmp рядом + ``os.replace``) и идемпотентная: одинаковое
содержимое файл не трогает вовсе. Идемпотентность здесь не оптимизация — за
файлом следит watcher, и запись, меняющая mtime без изменения содержимого,
дала бы петлю «применили → записали → увидели → применили».
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

#: Суффикс спутника. Именно ``.observability.yaml``, а не ``.obs.yml``:
#: имя файла — единственная подсказка человеку, кто его хозяин.
COMPANION_SUFFIX = ".observability.yaml"

#: Шапка файла. Спутник machine-owned, и это должно быть написано В НЁМ —
#: не только в документации, которую при отладке никто не открывает.
COMPANION_HEADER = (
    "# Спутник рецепта: слой L2 наблюдаемости (Task 5.12).\n"
    "# ФАЙЛ MACHINE-OWNED — его перезаписывает команда observability.persist.\n"
    "# Правки руками переживут ровно до следующего сохранения из пульта.\n"
    "# Человеческие настройки конвейера — в самом рецепте, рядом.\n"
)


def companion_path(recipe_path: str | os.PathLike[str]) -> Path:
    """``recipes/foo.yaml`` → ``recipes/foo.observability.yaml``."""
    p = Path(recipe_path)
    return p.with_name(p.stem + COMPANION_SUFFIX)


def load_companion(recipe_path: str | os.PathLike[str]) -> Dict[str, Any]:
    """Прочитать секцию спутника. Нет файла / нечитаем → ``{}``.

    Отсутствие спутника — штатное состояние (его создаёт первое «сохранить»),
    поэтому это не ошибка. А вот битый YAML — ошибка, и она пробрасывается
    наверх: молча стартовать без сохранённых настроек хуже, чем отказать.
    """
    path = companion_path(recipe_path)
    if not path.exists():
        return {}
    from ...data_schema_module.serialization.converter import DataConverter

    loaded = DataConverter.load_from_file(path)
    if not isinstance(loaded, dict):
        return {}
    section = loaded.get("observability")
    return section if isinstance(section, dict) else {}


def build_companion_section(
    current: Dict[str, Any],
    process_name: str,
    delta: Dict[str, Any],
) -> Dict[str, Any]:
    """Вложить дельту процесса в секцию спутника (per-process, поверх текущей).

    Правка ОДНОГО процесса не имеет права переписать соседей — поэтому дельта
    кладётся в ``processes[<имя>]``, а не в ``defaults``: ``defaults`` — то, что
    человек решил про весь конвейер, и машине там не место.
    """
    from ...data_schema_module import deep_merge

    section = dict(current or {})
    processes = dict(section.get("processes") or {})
    processes[process_name] = deep_merge(processes.get(process_name) or {}, delta)
    section["processes"] = processes
    return section


def write_companion(
    recipe_path: str | os.PathLike[str],
    section: Dict[str, Any],
) -> Tuple[Path, bool]:
    """Записать секцию в спутник атомарно и идемпотентно.

    Returns:
        ``(путь, была_ли_запись)``. ``False`` — содержимое уже совпадало, файл
        не тронут (и watcher не разбужен).

    Note:
        ``os.replace`` на Windows уже давал ``WinError 5`` в этом проекте, когда
        целевой файл держит другой процесс. Здесь цель — machine-owned спутник,
        которого никто не держит открытым, а tmp кладётся В ТОТ ЖЕ каталог
        (замена между томами не атомарна). Отказ не глушится: вызывающий обязан
        узнать, что «сохранить» не сохранило.
    """
    import yaml

    path = companion_path(recipe_path)
    body = yaml.safe_dump(
        {"observability": section},
        allow_unicode=True,
        sort_keys=True,
        default_flow_style=False,
    )
    payload = COMPANION_HEADER + body

    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == payload:
                return path, False
        except OSError:
            pass  # нечитаем — перезапишем

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return path, True


def compose_over_base(
    base: Optional[Dict[str, Any]],
    recipe_path: Optional[str | os.PathLike[str]],
    process_name: str,
) -> Tuple[Dict[str, Any], str]:
    """Слой L2 = БАЗА (долька рецепта) + спутник ПОВЕРХ. Единственная реализация.

    **Спутник входит в слой L2 только здесь (ФР-3).** База — это то, что сказал
    сам рецепт: её собирают ассемблеры (``proc_dict["config"]``), конверт switch'а
    и ``orchestrator_observability_config``, и ни один из них спутника не знает.
    До ФР-3 прикладная дорога домерживала спутник в базу ещё ДО резолва, и
    расхождение было не косметическим: слой заменяется целиком, но БАЗА живёт
    в конфиге процесса — снятый из спутника ключ оставался в ней навсегда и
    воскресал при каждой пересборке. На generic-дороге тот же ключ честно
    исчезал (возврат к рецепту). Один дефект, две разные системы.

    Порядок «спутник сверху» не обсуждается: спутник пишет пульт
    (``observability.persist``), его правка новее той, что человек написал в
    рецепте руками. Будь порядок обратным, «сохранить» отменялось бы switch'ем.

    Гранулярность — УЖЕ РАЗРЕШЁННАЯ per-process долька с обеих сторон: и база, и
    спутник резолвятся по имени процесса одним и тем же
    :func:`~.observability_layers.resolve_recipe_section`. Прежняя секционная
    гранулярность (мерж до резолва) давала ещё и второе, тихое расхождение:
    ``defaults`` спутника проигрывал ``processes[<имя>]`` рецепта, то есть
    направление «спутник сверху» на той дороге НЕ держалось.

    Исключения (битый спутник) пробрасываются: политику отказа решает вызывающий —
    на boot уместен отказ, на switch он снёс бы работающую систему.

    Args:
        base: долька рецепта для ЭТОГО процесса (сырая, уже разрешённая).
        recipe_path: адрес рецепта; спутник лежит рядом с ним.
        process_name: имя процесса-адресата — по нему резолвится спутник.

    Returns:
        ``(тело слоя, источник)``. Источник — файл спутника, если он что-то
        сказал про ЭТОТ процесс, иначе адрес рецепта: оператору нужно знать,
        какой из двух файлов править.
    """
    from ..configs.observability_layers import resolve_recipe_section
    from ...data_schema_module import deep_merge

    body = dict(base) if isinstance(base, dict) else {}
    if not recipe_path:
        return body, ""
    persisted = resolve_recipe_section(load_companion(recipe_path), process_name)
    if not persisted:
        return body, str(recipe_path)
    return deep_merge(body, persisted), str(companion_path(recipe_path))


def compose_recipe_layer(svc: Any) -> Tuple[Dict[str, Any], str, Dict[str, list]]:
    """Слой L2 процесса из ДВУХ его источников: дельта рецепта + спутник.

    У слоя рецепта два хозяина: сам рецепт (его дольку ассемблер кладёт процессу
    в конфиг на сборке) и спутник (его пишет ``observability.persist`` уже после
    старта). Спутник ложится ПОВЕРХ — он новее.

    Функция одна на два пути (boot и живая перечитка по команде) намеренно:
    разойдись они, «перечитать» и «стартовать» трактовали бы одну и ту же пару
    файлов по-разному — тот самый класс расхождения, который 5.12 закрывала как
    «boot ≡ reload». Возвращается ПОЛНЫЙ слой, а не дельта: слой заменяется
    целиком, иначе снятый из спутника ключ не исчез бы уже никогда.

    Здесь только ЧТЕНИЕ базы из конфига процесса; сам мерж — в
    :func:`compose_over_base`. Разделены они потому, что у оркестратора база
    приезжает не конфигом, а конвертом switch'а: третьей реализации мержа быть
    не должно, а «прочитать откуда» у них честно разное.

    **ФР-2: здесь же проверяются ссылки без приёмника.** Место выбрано не по
    удобству. Ровно три дороги кладут тело в слой L2 у живого процесса — конверт
    switch'а, перечитка спутника по команде и boot, — и все три собирают это тело
    ЭТОЙ функцией. Поставь проверку у каждой из них — их станет четыре на
    следующей правке, и одна снова окажется тихой (ровно так и появился ФР-2:
    проверка стояла на двух дорогах из пяти). Проверка здесь означает, что
    собрать слой L2, не узнав про сироты, больше нельзя.

    Отказа тут нет и быть не может: эта функция работает и на boot, и на switch,
    где падение из-за опечатки в machine-owned файле дороже самой опечатки.
    Громкая строка пишется внутри (см. ``report_unknown_refs``), список — наружу.

    Returns:
        ``(тело слоя, источник, сироты)``. Первые два — см.
        :func:`compose_over_base`; третий пуст, когда все ссылки разрешимы.
    """
    from ..configs.observability_layers import (
        OVERRIDE_CONFIG_KEY,
        RECIPE_PATH_CONFIG_KEY,
        read_process_config,
    )
    from ..configs.observability_refs import report_unknown_refs

    body, source = compose_over_base(
        read_process_config(svc, OVERRIDE_CONFIG_KEY) or {},
        read_process_config(svc, RECIPE_PATH_CONFIG_KEY) or "",
        getattr(svc, "name", ""),
    )
    # Проверяется СОБРАННОЕ тело, а не спутник отдельно: в слой въезжает именно
    # оно, и опечатка в рецепте ничем не лучше опечатки в спутнике. Источник в
    # строке называет файл, который вероятнее правит человек.
    return body, source, report_unknown_refs(svc, body, source=source)


def persist_session_to_companion(
    recipe_path: Optional[str],
    process_name: str,
    session: Dict[str, Any],
) -> Dict[str, Any]:
    """Перенести слой сессии процесса в спутник рецепта.

    Returns:
        Отчёт: ``{"success", "path", "written", "keys"}`` либо
        ``{"success": False, "reason": ...}``.
    """
    from .observability_layers import flatten_section

    if not recipe_path:
        return {"success": False, "reason": "путь к рецепту неизвестен — некуда сохранять"}
    if not session:
        return {"success": False, "reason": "слой сессии пуст — сохранять нечего"}

    section = build_companion_section(load_companion(recipe_path), process_name, session)
    path, written = write_companion(recipe_path, section)
    return {
        "success": True,
        "path": str(path),
        "written": written,
        "keys": sorted(flatten_section(session).keys()),
    }
