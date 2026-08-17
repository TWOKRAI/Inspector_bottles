# -*- coding: utf-8 -*-
"""
Flight recorder процесса: дамп кольца ЗАПИСЕЙ по требованию (Ф5, задача 5.1).

**Что это.** Кольцо последних записей плоскости логов уже живёт в процессе —
это ``MemoryChannel`` логгера (приёмник ``type: memory``, ретроспективное чтение
``observability.sink.tail``). Задача 5.1 добавляет ровно две вещи: (1) выгрузку
этого кольца в файл и (2) вызов выгрузки от прикладного триггера
(``ctx.flight_dump(reason)``). Ни нового кольца, ни новой плоскости, ни второй
дороги чтения здесь нет.

**Граница с чужим одноимённым механизмом** (Р5.1-13). В репозитории уже живут
две вещи, которые зовут «flight recorder», и склеить их по имени — вопрос
времени:

===================================== ================================ ==========================
Механизм                              Что кольцует                      Кто читает
===================================== ================================ ==========================
``backend_ctl record_*``              ТЕЛЕМЕТРИЮ системы                оператор, offline-реплей
``telemetry_readmodel.export_history``ТЕЛЕМЕТРИЮ уровней дерева         оператор, offline-реплей
**этот модуль**                       **ЗАПИСИ одного процесса**        сам процесс, по триггеру
===================================== ================================ ==========================

Первые два стоят СНАРУЖИ процесса и отвечают на «как менялись показания»; этот —
внутри и отвечает на «что процесс писал вокруг момента X». JFR-класс, а не
видеорегистратор: пикселей кадра в дампе нет и не будет.

**Дорога чтения кольца — существующая** (Р5.1-3):
``ChannelRoutingManager.read_sink_tail(sink, limit)`` у ``logger_manager``. В
процессный реестр колец (``log_channel._memory_rings``) мы не лезем: реестр —
внутренность канала, а по этой дороге уже ходит команда
``observability.sink.tail``. Второй способ прочитать одно кольцо разошёлся бы с
первым молча.

**Дорога записи файла — тоже существующая** (Р5.1-8):
``log_paths.process_log_directory`` → ``resolve_log_file_path``, то есть ровно
то, чем резолвится ``<база>/<процесс>/system.log``. Относительный путь от cwd
здесь запрещён не вкусом, а замером: он уже стоил проекту 467 МиБ в дереве
репозитория (урок 3.3, «материализованный дефолт»).

**Секреты дамп не открывает — на ТРЁХ поверхностях, и каждая отредактирована
явно** (Р5.1-12, доведено задачей S-2). ТЕЛО дампа секретов не несёт по
построению: кольцо кормится ПОСЛЕ цепочки процессоров логгера
(``LoggerCore._run_processors`` стоит до раздачи по каналам), то есть
``SecretRedactor`` отработал раньше кольца, и дамп своей дороги записи не
заводит — читает то, что уже отредактировано.

Но у ``ctx.flight_dump(reason, **fields)`` есть ДВЕ прикладные строки, которые
до кольца никогда не доходят и до задачи S-2 редактору не показывались вовсе —
``reason`` и ``fields``. Приёмка (``test_flight_manifest_redaction_acceptance.py``)
воспроизвела дефект: секрет из ``reason`` был виден в ИМЕНИ ФАЙЛА без открытия
дампа (:func:`reason_slug` — санитайзер для файловой системы, а не для
секретов), а из ``reason``/``fields`` — в шапке (``_write`` клал их в
``_dumps`` напрямую). Обе строки редактируются ОДИН раз, до попадания и в путь,
и в шапку:

* ``reason`` — ``redaction.redact_text`` (форма ``ключ=значение`` в тексте, та
  же цепочка, что применяется к ``message`` внутри ``SecretRedactor``);
* ``fields`` — ``redaction.redact_mapping`` (по ТОЧНОМУ имени ключа, та же
  цепочка, что применяется к ``extra``) — это ДВЕ разных поверхности с разными
  движками (имя ключа против формы ``ключ=значение`` в тексте), и нужны обе;
* :meth:`FlightRecorder._resolve_path` строит слаг из УЖЕ отредактированного
  ``reason``, полученного от :meth:`FlightRecorder.dump` одним значением —
  второй, независимой редакции для имени файла в модуле нет: разъедься она с
  редакцией шапки, это был бы тот же класс дефекта, что уже ловили на
  ``document_sink`` (Н-9).

Значение маскируется, а НЕ выбрасывается: ключ поля остаётся в шапке (факт
наличия поля — тоже улика), маскируется только значение.

Обходная дорога в модуле, куда редактор НЕ дотягивается никогда, — только
``frame_trace``: он пишет в свой канал, в кольцо не попадает, и редактор там
зовётся явно отдельным вызовом.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .observability_wiring import process_say

#: Адрес ручек в конфиге — он же то, что печатается в каждом отказе. Константа,
#: а не строка по месту: оператор получает адрес, по которому можно грепнуть
#: конфиг, и этот адрес обязан совпадать с тем, что читает код.
FLIGHT_CONFIG_ADDRESS = "observability.flight"

#: Ключ под-секции внутри разрешённых слоёв ``observability``.
FLIGHT_SECTION_KEY = "flight"

#: Атрибут процесса, на котором живёт рекордер. Имя объявлено ЗДЕСЬ и читается
#: отсюда и фасадом (``PluginContext.flight_dump``), и протоколом
#: (``IProcessServices.flight_recorder``): две рукописные копии имени
#: разъезжаются молча — этим уже был дефект ``document_sink`` (Н-9).
FLIGHT_RECORDER_ATTR = "flight_recorder"

#: Подкаталог дампов внутри каталога логов процесса.
FLIGHT_SUBDIR = "flight"

#: Расширение и шаблон отбора при ретеншене. Одна константа на запись и на
#: подметание: разойдись они — ретеншен считал бы не те файлы, что пишет дамп,
#: и «держим последние 5» означало бы «держим сколько получится».
FLIGHT_SUFFIX = ".jsonl"

#: Род первой строки дампа. Не «заголовок» и не комментарий: строка такая же
#: JSON-запись, как остальные, и читается тем же построчным разбором.
MANIFEST_KIND = "flight_manifest"

#: Род строки-заглушки на месте записи, которую не удалось сериализовать.
#: Молча пропустить её нельзя: счёт строк в дампе — то, чем судят полноту.
UNREADABLE_KIND = "flight_record_unreadable"

#: Предел длины ``reason`` в ИМЕНИ файла. Причина — прикладная строка, и она
#: бывает фразой; имя файла у неё не обязано быть полным (полная причина лежит
#: в шапке дампа), но обязано быть коротким и безопасным на любой ФС.
REASON_SLUG_MAX = 40

#: Чем заменяется всё, что не годится в имя файла. Диапазон намеренно узкий
#: (ASCII-буквы, цифры, точка, дефис, подчёркивание): дамп забирают с машины
#: скриптами и архиваторами, и кириллица в имени уже стоила проекту разбора
#: кодировок (cp866 в выводе консоли).
_SLUG_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

#: Счётчики отказов живут на ПРОЦЕССЕ, а не на рекордере, и это не стиль:
#: рекордера может не быть вовсе (сшивка не проходила), а отказ при этом
#: обязан быть посчитан — иначе «выключено» и «механизма нет» слились бы в
#: одинаковую тишину. Тот же довод, что у ``_DOCS_WITHOUT_SINK_ATTR``.
_REFUSED_DISABLED_ATTR = "_flight_refused_disabled"
_REFUSED_NO_RING_ATTR = "_flight_refused_no_ring"
_REFUSED_FAILED_ATTR = "_flight_refused_failed"

#: «Уже сказали» — по флагу на КАЖДЫЙ класс отказа, а не один на все три:
#: голос про выключённый рекордер не имеет права заглушить голос про
#: недоступное кольцо. Ровно та же раскладка, что у плоскости документов.
_WARNED_DISABLED_ATTR = "_flight_warned_disabled"
_WARNED_NO_RING_ATTR = "_flight_warned_no_ring"
_WARNED_FAILED_ATTR = "_flight_warned_failed"


def _bump(svc: Any, attr: str) -> None:
    """Прибавить единицу к счётчику на процессе. Иммутабельный дубль не роняет линию."""
    try:
        setattr(svc, attr, int(getattr(svc, attr, 0) or 0) + 1)
    except Exception:  # noqa: BLE001 — дубль без сеттеров в тесте не стоит линии
        pass


def _say_once(svc: Any, flag: str, message: str) -> None:
    """Сказать ОДИН раз на процесс. Счётчик при этом ведётся всегда.

    Довод тот же, что у ``note_document_without_sink``: причина отказа дампа не
    меняется от вызова к вызову (она в конфиге, а не в данных), и строка на
    каждый вызов превратила бы ненастроенный механизм в поток, к которому
    перестают прислушиваться. Число при этом не теряется — его отдаёт
    :func:`flight_plane_report`.
    """
    if getattr(svc, flag, False):
        return
    try:
        setattr(svc, flag, True)
    except Exception:  # noqa: BLE001
        pass
    process_say(svc, message, "WARNING")


def note_flight_disabled(svc: Any, reason: str) -> None:
    """Отказ (а) по Р5.1-6: механизм выключен ручкой. Адрес ручки — в тексте."""
    _bump(svc, _REFUSED_DISABLED_ATTR)
    _say_once(
        svc,
        _WARNED_DISABLED_ATTR,
        f"[flight] дамп {reason!r} НЕ сделан: flight recorder выключен, ручка "
        f"{FLIGHT_CONFIG_ADDRESS}.enabled — дальше считаем молча, "
        f"счётчик в introspect.observability -> flight.refused_disabled",
    )


def note_flight_no_ring(svc: Any, reason: str, detail: str) -> None:
    """Отказ (б) по Р5.1-6: включён, а кольца нет либо оно записей не хранит.

    ``detail`` — текст ``read_sink_tail`` (он несёт И имя приёмника, И имя
    менеджера, у которого его искали). Свой пересказ здесь не сочиняется: два
    описания одного отказа разошлись бы, а лечится он по чужому тексту.
    """
    _bump(svc, _REFUSED_NO_RING_ATTR)
    _say_once(
        svc,
        _WARNED_NO_RING_ATTR,
        f"[flight] дамп {reason!r} НЕ сделан: {detail} — проверь, что приёмник объявлен с "
        f"type: memory и смаршрутизирован скоупами ({FLIGHT_CONFIG_ADDRESS}.sink). "
        f"Дальше считаем молча, счётчик в introspect.observability -> flight.refused_no_ring",
    )


def note_flight_failed(svc: Any, reason: str, detail: str) -> None:
    """Третий класс: кольцо прочитано, а файл не написан (диск, права, ФС).

    Отдельный счётчик, потому что отдельный диагноз: два первых лечатся
    конфигом, этот — машиной. Слить его с ними значило бы отправить оператора
    править ключ, который в порядке. Р5.1-14 при этом соблюдён буквально —
    линия не падает, решение не меняется: дамп это улика, а не часть решения.
    """
    _bump(svc, _REFUSED_FAILED_ATTR)
    _say_once(
        svc,
        _WARNED_FAILED_ATTR,
        f"[flight] дамп {reason!r} НЕ записан: {detail} — кольцо прочитано, отказала ЗАПИСЬ файла. "
        f"Дальше считаем молча, счётчик в introspect.observability -> flight.refused_failed",
    )


def reason_slug(reason: Any) -> str:
    """Прикладная причина → безопасный кусок имени файла.

    Пустая причина даёт ``dump``, а не пустоту: имя вида ``20260816_101112_.jsonl``
    читается как ошибка сборки имени, хотя ею не является.

    **Точки снимаются с краёв вместе с подчёркиваниями.** Внутри имени они
    безобидны (``frame.drop``), а по краям дают ``..`` и ``.`` — имена, которые
    ФС и архиваторы трактуют особым образом. Разделителя пути в результате нет
    по построению (``/`` и ``\\`` не входят в разрешённый набор), так что это не
    защита от обхода каталога, а гигиена имени.

    **Кириллическая причина вырождается, и это названо.** Разрешённый набор —
    ASCII, поэтому ``"брак линии 7"`` даёт ``"7"``. Имя от этого не ломается
    (уникальность и порядок держит метка времени, а не причина), а полная
    причина лежит в шапке дампа. Транслитерации не заводим: это механизм ради
    красоты имени файла.
    """
    slug = _SLUG_UNSAFE.sub("_", str(reason or "")).strip("._")
    return slug[:REASON_SLUG_MAX] or "dump"


class FlightRecorder:
    """Живой хозяин дампов процесса: ручки, счётчики, сама выгрузка (Ф5, 5.1).

    Живёт на процессе один экземпляр, создаётся сшивкой на старте
    (:func:`wire_flight_recorder`) и переживает пересборку конфига: правка ручек
    меняет ПАРАМЕТРЫ, а не состояние — счёт дампов продолжается. Тот же довод,
    что у :class:`WideEventSelector` и ``RateSampler.configure``.

    **Своих данных не хранит.** Кольцо принадлежит логгеру, каталог — плоскости
    логов; здесь только политика и бухгалтерия. Поэтому рекордер безопасно
    переживает и ``config.reload``, и пересоздание каналов: пересобираться нечему.

    **Весь дамп идёт под локом — но держит лок не то, что кажется.**

    Первая редакция этого докстринга объясняла лок «перевытеснением»: два потока
    посчитали бы файлы каждый до записи соседа и удалили бы вдвое больше, чем
    просили. **Замер это опроверг** (ревью 5.1, 100 раундов: 8 потоков/``keep=4``
    и 32 потока/``keep=2``) — **ни одного раунда ниже ``keep``**. Перевытеснение
    невозможно по построению: каждый поток удаляет ``files[:len-keep]``, то есть
    ПРЕФИКС глобально отсортированного списка, а объединение префиксов не длиннее
    ``N-keep``. Уверенное неверное объяснение живёт дольше бага, поэтому оно
    здесь заменено, а не подправлено.

    Настоящих причин две, и обе — про ОКНО между шагами, а не про ретеншен:

    * **бухгалтерия.** ``self.dumps += 1`` и ``self.evicted_files += 1`` —
      неатомарные read-modify-write (факт о байткоде CPython, а не гипотеза), и
      потерянный инкремент ломает инвариант ``dumps == файлов на диске +
      evicted_files``. Счётчик, который врёт под нагрузкой, хуже отсутствующего:
      по нему судят полноту улик;
    * **TOCTOU имени.** ``_resolve_path`` проверяет ``path.exists()``, а пишет
      файл ``_write`` — два разных шага. Без взаимного исключения между ними
      второй поток успевает выбрать то же имя, и дамп молча перезаписывает
      чужую улику.

    **Насколько часто окно ловится — числа расходятся по машинам, и это сказано
    прямо.** Ревьюер намерил 7 нарушений инварианта из 40 раундов (32 потока,
    ``keep=2``) при снятом локе; на машине автора тот же арм дал **0 из 20**.
    Механизм от этого не исчезает — его прячет GIL, — но и «без лока обязательно
    сломается» утверждать нельзя. Отсюда форма сторожей: взаимное исключение
    доказывается ДЕТЕРМИНИРОВАННО барьером внутри критической секции
    (``test_the_dump_is_mutually_exclusive_end_to_end`` — красный 5/5 при снятом
    локе), а инвариант бухгалтерии проверяется как СВОЙСТВО, без претензии на
    воспроизводимую поломку. Шторм потоков сам по себе лок не доказывает: прежний
    «сторож конкуренции» оставался зелёным при полностью снятом локе.

    Триггер по построению редкий (фронт вердикта: 95 кадров брака → одно
    срабатывание), поэтому сериализация здесь ничего не стоит.

    **Дамп сам себя не видит.** Кольцо снимается ОДИН раз, в начале; голоса
    вытеснения (INFO) уходят в тот же логгер и потому попадут в СЛЕДУЮЩИЙ дамп, а
    не в этот. Это названо, а не случайно: увидев в дампе строки о вытеснении
    файлов, читатель обязан понимать, что они от прошлого раза.
    """

    __slots__ = (
        "_knobs",
        "_lock",
        "dumps",
        "records",
        "unreadable",
        "evicted_files",
        "last_path",
    )

    def __init__(self, enabled: bool = False, sink: str = "", keep: int = 5, limit: int = 0) -> None:
        self._lock = threading.RLock()
        self.dumps = 0
        self.records = 0
        self.unreadable = 0
        self.evicted_files = 0
        self.last_path = ""
        self._knobs: Tuple[bool, str, int, int] = (False, "", 5, 0)
        self.configure(enabled, sink, keep, limit)

    # -- Конфигурация ---------------------------------------------------

    def configure(self, enabled: Any, sink: Any, keep: Any, limit: Any) -> Tuple[bool, str, int, int]:
        """Применить ручки БЕЗ сброса счётчиков. Возвращает применённую четвёрку.

        Подмена — ОДНИМ кортежем, а не четырьмя присваиваниями: читатель снимает
        политику одним чтением и не может застать полусмену («новый ``sink`` со
        старым ``keep``»). Тот же приём, что у ``WideEventSelector.configure`` и
        у мутабельного publisher-гейта телеметрии (PC 3.1).

        Отрицательное приводится к нулю, а не отвергается: границы держит схема
        (``ObservabilityFlightConfig``, ``min=0``) на входе в слой, и второй
        предохранитель здесь сделал бы неизвестным, который из них держит.
        """
        knobs = (bool(enabled), str(sink or "").strip(), max(0, int(keep)), max(0, int(limit)))
        self._knobs = knobs
        return knobs

    @property
    def knobs(self) -> Tuple[bool, str, int, int]:
        """Действующая четвёрка ``(enabled, sink, keep, limit)`` — одним чтением."""
        return self._knobs

    # -- Дамп -----------------------------------------------------------

    def dump(
        self,
        svc: Any,
        reason: str = "",
        fields: Optional[Dict[str, Any]] = None,
        source: str = "",
    ) -> bool:
        """Выгрузить кольцо в ``<база>/<процесс>/flight/<ts>_<reason>.jsonl``.

        Args:
            svc: процесс (нужен логгер, имя и голос). Параметром, а не полем:
                рекордер живёт НА процессе, и ссылка назад завела бы цикл ради
                удобства, которого нет — фасад всё равно держит ``services``.
            reason: прикладная причина. Едет и в имя файла (усечённая, см.
                :func:`reason_slug`), и в шапку целиком.
            fields: прикладная шапка — прежде всего ``trace_id`` единицы. Без
                неё дамп и вердикт связывались бы догадкой по времени.
            source: кто позвал (имя плагина). В шапке, чтобы у дампа было «кем».

        Returns:
            ``True`` — файл записан. ``False`` — один из трёх названных отказов
            (см. :func:`note_flight_disabled` / :func:`note_flight_no_ring` /
            :func:`note_flight_failed`). Ни один из них не тишина, и ни один не
            роняет линию.
        """
        enabled, sink, keep, limit = self._knobs
        if not enabled:
            note_flight_disabled(svc, reason)
            return False

        logger = getattr(svc, "logger_manager", None)
        read = getattr(logger, "read_sink_tail", None)
        if not callable(read):
            note_flight_no_ring(
                svc,
                reason,
                f"у процесса нет logger_manager с чтением приёмников (искали {sink!r})",
            )
            return False
        try:
            answer = read(sink, limit or None)
        except Exception as exc:  # noqa: BLE001 — отказ чтения кольца не роняет линию
            note_flight_no_ring(svc, reason, f"чтение приёмника {sink!r} отказало ({exc!r})")
            return False
        if not isinstance(answer, dict) or not answer.get("success"):
            detail = (answer or {}).get("reason") if isinstance(answer, dict) else None
            note_flight_no_ring(svc, reason, str(detail or f"приёмник {sink!r} недоступен"))
            return False

        records = list(answer.get("records") or [])
        info = answer.get("info") if isinstance(answer.get("info"), dict) else {}

        # Редакция ``reason`` — ОДИН раз, здесь, до пути и до шапки (см.
        # модульный докстринг, Р5.1-12/S-2). Раздельная редакция в
        # `_resolve_path` и в `_write` разъехалась бы молча тем же классом
        # дефекта, что уже ловили на `document_sink` (Н-9).
        from ...logger_module.core.redaction import redact_text

        safe_reason = redact_text(str(reason))
        with self._lock:
            try:
                path = self._resolve_path(svc, logger, safe_reason)
                written, unreadable = self._write(path, svc, safe_reason, source, records, info, fields)
            except Exception as exc:  # noqa: BLE001 — см. note_flight_failed
                note_flight_failed(svc, reason, repr(exc))
                return False
            self.dumps += 1
            self.records += written
            self.unreadable += unreadable
            self.last_path = str(path)
            self._retain(svc, path.parent, keep)
        return True

    # -- Путь -----------------------------------------------------------

    def _resolve_path(self, svc: Any, logger: Any, reason: str) -> Path:
        """``<база>/<имя процесса>/flight/<ts>_<reason>.jsonl`` — дорогой файлов журнала.

        ``reason`` приходит от :meth:`dump` УЖЕ отредактированным
        (``redaction.redact_text``, один раз, на входе) — вторая редакция здесь
        не заводится (см. модульный докстринг, S-2). :func:`reason_slug` при
        этом остаётся санитайзером ИМЕНИ ФАЙЛА, а не редактором секретов: он
        режет небезопасные для ФС символы, ничего не зная про секретные имена.

        Метка времени фиксированной ширины (``ГГГГММДД_ЧЧММСС_мкс``) не ради
        красоты: по ней же идёт ретеншен, и лексикографический порядок имён
        обязан совпадать с хронологическим. Микросекунды — потому что серия
        отбраковок укладывается в одну секунду, а перезаписать чужой дамп значит
        уничтожить улику.
        """
        from ...logger_module.core.log_paths import process_log_directory, resolve_log_file_path

        config = getattr(logger, "config", None)
        base = process_log_directory(getattr(config, "log_directory", None), getattr(svc, "name", "") or "process")
        moment = time.time()
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(moment)) + f"_{int(moment % 1 * 1_000_000):06d}"
        name = f"{stamp}_{reason_slug(reason)}{FLIGHT_SUFFIX}"
        path = Path(
            resolve_log_file_path(
                f"{FLIGHT_SUBDIR}/{name}",
                fallback=f"{FLIGHT_SUBDIR}/{name}",
                log_directory=str(base),
            )
        )
        # Столкновение по микросекунде — край, но молчаливая перезапись улики
        # хуже уродливого имени. Суффикс, а не отказ: дамп нужен именно сейчас.
        bump = 0
        while path.exists():
            bump += 1
            path = path.with_name(f"{stamp}_{reason_slug(reason)}-{bump}{FLIGHT_SUFFIX}")
        return path

    # -- Запись ---------------------------------------------------------

    def _write(
        self,
        path: Path,
        svc: Any,
        reason: str,
        source: str,
        records: List[Dict[str, Any]],
        info: Dict[str, Any],
        fields: Optional[Dict[str, Any]],
    ) -> Tuple[int, int]:
        """JSONL: шапка первой строкой, дальше записи кольца как есть (Р5.1-9).

        Возвращает ``(сколько записей легло, сколько заменено заглушкой)``.

        **Шапка редактируется ПЕРЕД сборкой, а не после** (S-2). ``reason``
        приходит от :meth:`dump` уже отредактированным одним вызовом
        ``redaction.redact_text``; ``fields`` редактируется здесь же —
        ``redaction.redact_mapping`` копирует словарь и маскирует значения
        секретных ключей ПО ИМЕНИ, оставляя сам ключ в шапке (значение
        маскируется, а не выбрасывается — факт наличия поля тоже улика). Две
        разных поверхности (текст причины и имена полей) редактируются двумя
        разными движками сознательно: они ловят разные формы.

        **Шапка обязательна и потому пишется в два захода.** Она несёт
        прикладные ``**fields``, а туда кладут что угодно — но дамп без шапки
        нечитаем: по ней отличают «в дампе 12 записей, потому что столько было»
        от «потому что 488 вытеснено». Не сериализовалась с полями — пишем без
        них, назвав причину прямо в шапке, а не роняем дамп целиком.

        **Отказ ОДНОЙ записи не стоит дампа.** ``extra`` держит ссылки на
        произвольные объекты вызывающего (сказано прямо в докстринге редактора
        записей), и одна циклическая ссылка не имеет права унести с собой все
        499 соседей. На месте такой записи остаётся строка-заглушка с индексом:
        счёт строк — то, чем судят полноту, и молчаливый пропуск сдвинул бы его.
        """
        from ...logger_module.core.redaction import redact_mapping

        envelope = {
            **(redact_mapping(fields) if fields else {}),
            "kind": MANIFEST_KIND,
            "reason": str(reason),
            "process": str(getattr(svc, "name", "") or ""),
            "source": str(source or ""),
            "ts": time.time(),
            "records": len(records),
            "ring": {key: info.get(key) for key in ("capacity", "size", "written", "evicted") if key in info},
            "sink": self._knobs[1],
            "limit": self._knobs[3],
        }
        try:
            header = _dumps(envelope)
        except Exception as exc:  # noqa: BLE001 — прикладные поля не стоят дампа
            envelope = {key: value for key, value in envelope.items() if key in _MANIFEST_OWN_KEYS}
            envelope["fields_unreadable"] = repr(exc)
            header = _dumps(envelope)

        unreadable = 0
        lines = [header]
        for index, record in enumerate(records):
            try:
                lines.append(_dumps(record))
            except Exception as exc:  # noqa: BLE001 — см. докстринг
                unreadable += 1
                lines.append(_dumps({"kind": UNREADABLE_KIND, "index": index, "error": repr(exc)}))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return len(records), unreadable

    # -- Ретеншен -------------------------------------------------------

    def _retain(self, svc: Any, directory: Path, keep: int) -> None:
        """Оставить в каталоге не больше ``keep`` дампов. ``keep=0`` — без предела.

        **Голос на КАЖДОЕ вытеснение** (Р5.1-10), а не «один раз на условие», как
        у отказов выше. Довод обратный и потому явный: отказ повторяется на
        каждом такте линии, а вытеснение — событие настолько же редкое, насколько
        редок сам дамп, и молчаливое удаление улики хуже строки в журнале.

        Порядок — по ИМЕНИ файла. Метка времени в имени фиксированной ширины,
        поэтому лексикографический порядок равен хронологическому; ``mtime`` дал
        бы то же самое, но зависел бы от копирования файлов и от разрешения ФС.

        Отказ удаления не роняет уже записанный дамп: файл на диске есть, и это
        главное. Но и не молчит.
        """
        if keep <= 0:
            return
        try:
            files = sorted(p for p in directory.glob(f"*{FLIGHT_SUFFIX}") if p.is_file())
        except OSError as exc:
            process_say(svc, f"[flight] каталог дампов не прочитан ({exc!r}) — ретеншен пропущен", "WARNING")
            return
        for victim in files[: max(0, len(files) - keep)]:
            try:
                victim.unlink()
            except OSError as exc:
                process_say(svc, f"[flight] старый дамп не удалён: {victim.name} ({exc!r})", "WARNING")
                continue
            self.evicted_files += 1
            process_say(
                svc,
                f"[flight] вытеснен старый дамп {victim.name}: держим последние {keep} ({FLIGHT_CONFIG_ADDRESS}.keep)",
                "INFO",
            )

    # -- Readback -------------------------------------------------------

    def counters(self) -> Dict[str, Any]:
        """Снимок бухгалтерии — копия, снятая под локом (как у селектора)."""
        with self._lock:
            return {
                "dumps": self.dumps,
                "records": self.records,
                "unreadable": self.unreadable,
                "evicted_files": self.evicted_files,
                "last_path": self.last_path,
            }


#: Собственные ключи шапки — те, что кладёт механизм, а не приложение. Нужны
#: ровно в одном месте: когда прикладные поля не сериализуются и шапку надо
#: пересобрать без них. Список, а не «всё кроме fields»: ключи приложения могут
#: совпасть с нашими по имени, и вычитание по множеству имён вернуло бы наши же.
_MANIFEST_OWN_KEYS = (
    "kind",
    "reason",
    "process",
    "source",
    "ts",
    "records",
    "ring",
    "sink",
    "limit",
)


def _dumps(obj: Any) -> str:
    """JSON одной строкой. ``default=str`` — потому что в ``extra`` кладут объекты.

    ``ensure_ascii=False``: дамп читают глазами, и кириллица в ``\\uXXXX``
    превратила бы улику в ребус. Файл пишется в UTF-8 явно.
    """
    return json.dumps(obj, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Дорога ручки: схема → сшивка (старт) + пересборка → readback живого объекта
# ---------------------------------------------------------------------------


def _flight_knobs(
    section: Any,
    svc: Any,
    fallback: Tuple[bool, str, int, int],
) -> Tuple[bool, str, int, int]:
    """Разобрать под-секцию ``observability.flight`` схемой. Мусор → ``fallback`` + голос.

    Отказ здесь НЕ роняет пересборку целиком: ручки дампа едут в одной секции с
    уровнем логирования и каталогом логов, и опечатка в них не имеет права
    стоить оператору применения всего остального. Дорога дословно та же, что у
    ``_events_knobs``, — и это не копипаста, а одинаковое правило у соседних
    под-секций одной двери: разойдись они, мусор в ``flight`` и мусор в
    ``events`` вели бы себя по-разному в одной команде.
    """
    from ..configs.observability_config import ObservabilityFlightConfig

    if section is None:
        return (False, "", 5, 0)
    if not isinstance(section, dict):
        process_say(
            svc,
            f"[observability] {FLIGHT_CONFIG_ADDRESS} не словарь ({type(section).__name__}) "
            f"— политика дампа остаётся прежней {fallback}",
        )
        return fallback
    try:
        cfg = ObservabilityFlightConfig.model_validate(section)
    except Exception as exc:  # noqa: BLE001 — см. докстринг
        process_say(
            svc,
            f"[observability] {FLIGHT_CONFIG_ADDRESS} не принят ({exc!r}) — политика дампа остаётся прежней {fallback}",
        )
        return fallback
    return (bool(cfg.enabled), str(cfg.sink), int(cfg.keep), int(cfg.limit))


def wire_flight_recorder(svc: Any) -> Optional[FlightRecorder]:
    """Ф5 (5.1): создать рекордер и опубликовать его на процессе.

    Зовётся у КАЖДОГО процесса и создаёт рекордер ВСЕГДА — по тому же доводу,
    что :func:`wire_event_selector`: отсутствие секции означает не «механизма
    нет», а «дампы выключены», то есть ровно дефолт ``enabled=False``. Создай мы
    рекордер только при наличии ключа — у «выключено» стало бы ДВА исполнения
    (``None`` и настроенный ``enabled=False``), и Р5.1-5 нарушился бы в первой
    же строке кода, который его декларирует.

    Возвращает рекордер либо ``None`` — если слои не прочитались или объект
    процесса не принимает атрибут (иммутабельный дубль в тесте). ``None``
    наблюдаем: ``introspect.observability -> flight.declared`` отвечает
    ``false``, и это отличает «рекордера нет» от «рекордер есть и выключен».
    """
    from ..configs.observability_layers import process_observability_layers

    try:
        layers = process_observability_layers(svc)
        section = layers.resolve().get(FLIGHT_SECTION_KEY)
    except Exception as exc:  # noqa: BLE001 — процесс без конфига живёт без дампов
        process_say(svc, f"[observability] секция {FLIGHT_CONFIG_ADDRESS} не прочитана: {exc!r}")
        return None

    recorder = FlightRecorder(*_flight_knobs(section, svc, (False, "", 5, 0)))
    try:
        setattr(svc, FLIGHT_RECORDER_ATTR, recorder)
    except Exception:  # noqa: BLE001 — объект без сеттеров: дампов нет, линия жива
        return None
    return recorder


def apply_flight_recorder(recorder: Any, section: Any, svc: Any = None) -> Optional[Dict[str, Any]]:
    """Пересборка: применить ручки к ЖИВОМУ рекордеру. Возвращает применённое.

    Третья точка дороги ручки (после схемы и сшивки) — та, без которой
    ``config.reload`` менял бы слой и не менял поведение. Рекордер создаётся один
    раз на старте, и правка, не дошедшая до него, осталась бы видимой в
    провенансе и не действующей: ровно находка №1 задачи 4.1, где ручка
    действовала через ``config.reload`` и НЕ действовала через правку файла, а
    обе дороги отвечали «применено».

    Счётчики при этом НЕ сбрасываются (см. :meth:`FlightRecorder.configure`).
    ``None`` на входе (рекордера нет) — не отказ: пересборка идёт и на процессах,
    где дампов никто не просил.
    """
    configure = getattr(recorder, "configure", None)
    if not callable(configure):
        return None
    fallback = getattr(recorder, "knobs", (False, "", 5, 0))
    enabled, sink, keep, limit = _flight_knobs(section, svc, fallback)
    applied = configure(enabled, sink, keep, limit)
    return {"enabled": applied[0], "sink": applied[1], "keep": applied[2], "limit": applied[3]}


def flight_effective(recorder: Any) -> Optional[Dict[str, Any]]:
    """Действующие ручки живого рекордера — для ``observability_effective``.

    Отдельно от :func:`flight_plane_report`, потому что отвечает на другой
    вопрос и читается другим потребителем: здесь ровно четыре ЗАПРОШЕННЫХ пути,
    по которым ``config.reload`` выносит вердикт. Не будь их — правка отвечала
    бы ``unverifiable`` при ``checked=0``, то есть «подано, подтвердить нечем»;
    на живом стенде 2026-08-16 это уже случилось с ручками ``events`` на всех
    восьми процессах.
    """
    knobs = getattr(recorder, "knobs", None)
    if not (isinstance(knobs, tuple) and len(knobs) == 4):
        return None
    return {"enabled": bool(knobs[0]), "sink": str(knobs[1]), "keep": int(knobs[2]), "limit": int(knobs[3])}


def flight_plane_report(svc: Any) -> Dict[str, Any]:
    """Секция ``flight`` для ``introspect.observability`` (Р5.1-4).

    Читает ЖИВОЙ рекордер, а не пересчитывает ручки из конфига: расхождение «в
    слое одно, в работе другое» и есть тот дефект, ради которого readback
    заводится — пересчёт из того же источника показывал бы согласие всегда.

    Числа, и каждое отвечает на своё:

    * ``declared`` — рекордер поднят. Разделитель «механизма нет» и «есть, но
      выключен»: без него ноль дампов читался бы как здоровье в обоих случаях;
    * ``enabled`` / ``sink`` / ``keep`` / ``limit`` — что действует СЕЙЧАС;
    * ``dumps`` / ``records`` — сколько файлов написано и сколько записей в них
      легло. Второе без первого не даёт судить о глубине кольца;
    * ``unreadable`` — сколько записей заменено заглушкой (несериализуемое
      в ``extra``). Ненулевое означает, что в дампе есть дырки, и они видны;
    * ``evicted_files`` — сколько дампов вытеснено ретеншеном;
    * ``refused_disabled`` / ``refused_no_ring`` / ``refused_failed`` — три
      РАЗНЫХ диагноза: ручка, конфиг кольца, машина. Слить их значило бы
      отправить оператора чинить не то;
    * ``last_path`` — где лежит последний дамп. Вопрос «а куда оно пишется»
      иначе отвечается чтением исходников.
    """
    recorder = getattr(svc, FLIGHT_RECORDER_ATTR, None)
    counters = getattr(recorder, "counters", None)
    refusals = {
        "refused_disabled": int(getattr(svc, _REFUSED_DISABLED_ATTR, 0) or 0),
        "refused_no_ring": int(getattr(svc, _REFUSED_NO_RING_ATTR, 0) or 0),
        "refused_failed": int(getattr(svc, _REFUSED_FAILED_ATTR, 0) or 0),
    }
    if not callable(counters):
        return {
            "flight": {
                "declared": False,
                "enabled": False,
                "sink": "",
                "keep": 0,
                "limit": 0,
                "dumps": 0,
                "records": 0,
                "unreadable": 0,
                "evicted_files": 0,
                "last_path": "",
                **refusals,
            }
        }
    enabled, sink, keep, limit = recorder.knobs
    return {
        "flight": {
            "declared": True,
            "enabled": bool(enabled),
            "sink": str(sink),
            "keep": int(keep),
            "limit": int(limit),
            **counters(),
            **refusals,
        }
    }
