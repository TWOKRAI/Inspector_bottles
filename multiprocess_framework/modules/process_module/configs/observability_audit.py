# -*- coding: utf-8 -*-
"""
Аудит смен наблюдаемости (Task 5.9) — «когда и чем», а не только «кто владеет».

Провенанс (Task 5.12) отвечает на вопрос «каким слоём задан этот ключ». Он не
отвечает на вопросы, которые задают в инциденте: *когда* правку сделали, *чем*
именно (командой, правкой файла, подметальщиком сроков, `switch` рецепта) и что
из этого **не удалось**. До этого модуля частичные ответы давали три разных
механизма — кольцо возвратов, строки журнала и журнал драйвера, — и ни один не
видел смены, пришедшие с других сторон.

Один писатель
-------------
Кольцо здесь **единственное**. ``ObservabilityLayers.session_reverts`` больше не
хранит свои записи, а выбирает из этого кольца записи с ``action="expire"``: два
кольца, пишущие пересекающиеся факты, немедленно порождают вопрос «почему в одном
есть, а в другом нет».

Долговечности своего файла не заводится. Каждая запись кладёт **одну** строку в
журнал процесса — он уже долговечен, уже ротируется и уже единственный писатель
на диск. Кольцо отвечает на «что сейчас», журнал — на «что было до рестарта».

Полнота — сигнатурой, а не дисциплиной
--------------------------------------
``origin`` объявлен **обязательным** keyword-параметром у каждого примитива
мутации L3 (:mod:`.observability_layers`) и у пересборки. Забыть его нельзя:
будет ``TypeError`` на вызове, а не тихая запись «источник неизвестен». Скрытого
контекста (thread-local с дефолтом) здесь сознательно нет — дефолт и есть та
ложь, которую задача устраняет.

``origin`` называет **механизм**, не человека: ``command:config.reload``,
``watcher:app``, ``ttl-sweeper``, ``switch``. Графы «кто» нет вовсе — её не несёт
ни один конверт команды, и пустое поле всегда врало бы молчанием.

Форма записи взята у ``backend_ctl/audit.py`` (``seq`` / ``ts`` / ``ok`` /
``error`` + усечение крупных значений), но не место: драйверный журнал стоит у
ОДНОГО клиента и не видит ни watcher'а, ни подметальщика, ни второго потребителя.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

#: Глубина кольца. Сотни хватает на разбор инцидента (смены наблюдаемости —
#: событие редкое); вытесненное не пропадает бесследно — его считает ``dropped``.
AUDIT_HISTORY = 100

#: Потолок сериализации значения в записи. Секция ``observability`` целиком может
#: быть большой, а аудит не имеет права стать вторым местом хранения конфига.
_VALUE_CAP = 1024

#: Действия. Список закрытый: новое действие должно быть добавлено осознанно,
#: иначе оно появится в ответе как незнакомая строка у первого же потребителя.
ACTION_SET = "set"  # ключ записан в L3
ACTION_TOUCH = "touch"  # ключам L3 проставлен срок (секция приехала целиком)
ACTION_RESET = "reset"  # ключ/ветка удалены из L3 руками
ACTION_CLEAR = "clear"  # L3 сброшен целиком (switch рецепта)
ACTION_EXPIRE = "expire"  # авто-возврат по истечении срока
ACTION_PERSIST = "persist"  # ключи переехали из L3 в L2 (срок снят)
ACTION_LAYER = "layer"  # заменён слой L1/L2 (файл, рецепт)
ACTION_REBUILD = "rebuild"  # конфиг пересобран из слоёв и применён

#: «Аргумент не передан» — отдельно от ``None``. Значение ``None`` в слое
#: осмысленно (маркер снятия правила у троттла), и запись обязана отличать его от
#: «значения у этой смены нет».
_UNSET = object()

ACTIONS = (
    ACTION_SET,
    ACTION_TOUCH,
    ACTION_RESET,
    ACTION_CLEAR,
    ACTION_EXPIRE,
    ACTION_PERSIST,
    ACTION_LAYER,
    ACTION_REBUILD,
)


def _clip(value: Any) -> Any:
    """Сжать значение до безопасного размера: длинное → усечённая строка-маркер.

    Форма маркера повторяет ``backend_ctl.audit._clip`` — потребитель, читающий
    оба журнала, не должен разбирать два разных признака усечения.
    """
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 — несериализуемое → repr
        text = repr(value)
    if len(text) <= _VALUE_CAP:
        return value
    return {"_truncated": True, "size": len(text), "head": text[:_VALUE_CAP]}


#: Поля, принадлежащие САМОМУ аудиту, а не описываемой смене: они меняются от
#: вхождения к вхождению по построению и в сравнении условий не участвуют.
#: ``log_failed`` дописывается уже после публикации (``_announce``), поэтому тоже
#: здесь — иначе повтор перестал бы схлопываться ровно тогда, когда сломался ещё
#: и журнал.
#:
#: ``document_failed``/``document_error`` — того же сорта отметки, но от ``_emit_document``
#: (M-1 ревью Ф8, репро: падающий сток давал ``ring=10`` вместо ``ring=1, repeats=10``).
#: Механика дефекта общая для всех «отметок после публикации»: отметка попадает в
#: запись, УЖЕ лежащую в кольце, следующая запись приходит без неё — и сравнение
#: условий видит разные наборы ключей. Схлопывание отключалось ровно на отказе, то
#: есть тогда, когда поток повторов максимален, а место в кольце дороже всего.
_AUDIT_OWNED_FIELDS = frozenset({"seq", "ts", "repeats", "last_ts", "log_failed", "document_failed", "document_error"})


def _same_condition(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """Описывают ли две записи ОДНО И ТО ЖЕ условие (A-A6-1).

    Сравниваются все поля, кроме принадлежащих самому аудиту
    (:data:`_AUDIT_OWNED_FIELDS`). Сравнение полное, а не по выбранным ключам, и
    это осознанно: перечень «значимых» полей пришлось бы держать в аудите, то есть
    аудит знал бы про поля своих писателей — и первое же новое поле схлопывалось
    бы молча. Полное сравнение ошибается в безопасную сторону: лишнее различие
    схлопывание просто прекращает.
    """
    if left.keys() - _AUDIT_OWNED_FIELDS != right.keys() - _AUDIT_OWNED_FIELDS:
        return False
    return all(left[name] == right[name] for name in left.keys() - _AUDIT_OWNED_FIELDS)


@dataclass
class ObservabilityAudit:
    """Кольцо смен наблюдаемости одного процесса — единственный писатель.

    Attributes:
        ring: последние :data:`AUDIT_HISTORY` записей, новейшие в конце.
        seq: сквозной номер. Считает **все** записи, включая вытесненные, —
            поэтому ``dropped`` вычисляется, а не хранится вторым счётчиком,
            который мог бы разойтись с кольцом.
        log: колбэк долговечного следа ``(сообщение, ошибка?) -> None``.
            ``None`` — процесс без журнала (тесты, одиночный запуск): кольцо
            работает, долговечности нет, и это видно по отсутствию строк.
        clock: стенные часы КАК ЗАВИСИМОСТЬ ОБЪЕКТА. Глобальный патч
            ``time.time`` в тестах доедают чужие потоки — на этом проекте уже
            ловили флейк в невиновном тесте.
    """

    ring: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=AUDIT_HISTORY))
    seq: int = 0
    log: Optional[Callable[[str, bool], None]] = None
    #: Н2-3: голос о вытеснении сказан. ОДИН НА УСЛОВИЕ (не на запись и не на
    #: процесс-в-целом-навсегда по смыслу, а до конца жизни объекта — кольцо, раз
    #: заполнившись, теряет с каждой новой сменой, и повторять это нечего). Счёт
    #: остаётся за :meth:`dropped`; второй счётчик разошёлся бы с кольцом.
    _overflow_announced: bool = False
    #: Отказ журнала на этой строке — именной, а не проглоченный (класс
    #: «проглоченный сбой»): «голоса не было» и «голос не смог записаться» лечатся
    #: разным.
    _overflow_log_failed: Optional[str] = None
    #: Приёмник ДОКУМЕНТА: ``(dict) -> Any``. ``None`` — плоскость документов не
    #: подключена, поведение прежнее (кольцо + строка журнала).
    #:
    #: Тип намеренно структурный, а не импортированный: фреймворк не имеет права
    #: знать про ``Services`` (правило слоёв 9), поэтому здесь один вызов с ``dict``,
    #: а реализацию поверх SQL приносит композиционный корень.
    sink: Optional[Callable[[Dict[str, Any]], Any]] = None
    #: Кто породил документ — имя процесса. Пустая строка означает «процесс себя не
    #: назвал», а не «источник неизвестен вообще»: плоскость документов ОДНА на
    #: систему, и восемь процессов пишут в один файл. Без этого поля документы
    #: неразличимы, и вопрос «где включили DEBUG» остаётся без ответа ровно там, где
    #: заведён механизм, чтобы отвечать. В кольцо и в журнал не идёт: там источник
    #: и так известен — это журнал ЭТОГО процесса.
    source: str = ""
    clock: Callable[[], float] = time.time
    _lock: Any = field(default_factory=threading.Lock, repr=False, compare=False)

    def __getstate__(self) -> Dict[str, Any]:
        """Лок и колбэки непиклимы — стек слоёв едет в снимок процесса без них."""
        state = dict(self.__dict__)
        state.pop("_lock", None)
        state.pop("log", None)
        # sink выбрасывается по той же причине, что и log: это замыкание на
        # соединение с БД. Забыть его здесь — значит уронить пиклинг всего стека
        # слоёв, а стек едет в снимок процесса на каждом boot/switch.
        state.pop("sink", None)
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__.update(state)
        self.__dict__.setdefault("log", None)
        self.__dict__.setdefault("sink", None)
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        *,
        origin: str,
        key: Optional[str] = None,
        keys: Optional[Any] = None,
        value: Any = _UNSET,
        ttl_sec: Optional[float] = None,
        ok: bool = True,
        error: Optional[str] = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        """Записать одну смену. Возвращает записанное (для тестов и ответов команд).

        Args:
            action: одно из :data:`ACTIONS`. Неизвестное принимается и помечается
                ``action_unknown``: аудит не имеет права отказать смене, которая
                уже произошла, но и молча узаконивать опечатку он не должен.
            origin: механизм смены (``command:config.reload``, ``watcher:app``,
                ``ttl-sweeper``, ``switch``). Обязателен — см. модульный docstring.
            value: записанное значение (усекается). Не переданное — отсутствует
                в записи; переданное ``None`` записывается как ``None``: у
                троттла это осмысленный маркер снятия правила, и слить его с
                «значения не было» значило бы записать не то, что произошло.

        Долговечная строка кладётся в журнал **вне лока**: I/O не должно держать
        кольцо, а сбой журнала не должен ронять смену (форма ``AuditLog``).
        """
        entry: Dict[str, Any] = {"action": str(action), "origin": str(origin)}
        if str(action) not in ACTIONS:
            entry["action_unknown"] = True
        if key is not None:
            entry["key"] = str(key)
        if keys is not None:
            entry["keys"] = [str(k) for k in keys]
        if value is not _UNSET:
            entry["value"] = _clip(value)
        if ttl_sec is not None:
            entry["ttl_sec"] = ttl_sec
        # ``ok`` пишется ВСЕГДА, включая успех. Экономия одного поля стоила бы
        # того, что «удалось» опознавалось бы по ОТСУТСТВИЮ ключа: читатель,
        # ищущий отказы, не отличил бы успешную запись от записи, сделанной
        # версией, которая про исход ещё не знала.
        entry["ok"] = bool(ok)
        if not ok and error:
            entry["error"] = str(error)
        for name, item in extra.items():
            if item is not None:
                entry[name] = _clip(item)

        with self._lock:
            last = self.ring[-1] if self.ring else None
            if last is not None and _same_condition(last, entry):
                # Схлопывание ПОДРЯД идущих одинаковых записей (A-A6-1). Повтор —
                # не новая смена, а то же условие, всё ещё длящееся: подметальщик
                # повторяет попытку каждый такт, и сотня отказов выедала кольцо за
                # ~8 минут, унося с собой причину. Держим ПЕРВОЕ вхождение (когда
                # началось) и отмечаем последнее.
                last["repeats"] = int(last.get("repeats", 1)) + 1
                last["last_ts"] = self.clock()
                # `seq` НЕ растёт: он считает записи кольца, и на нём держится
                # `dropped()` = seq − len(ring). Считай повтор новым seq — и
                # счётчик отрапортовал бы вытеснение, которого не было, то есть
                # соврал бы ровно там, где заведён, чтобы не врать.
                return dict(last)
            self.seq += 1
            entry["seq"] = self.seq
            entry["ts"] = self.clock()
            # Задача Н2-3 (переприёмка F2 раунд 2): вытеснение из кольца считалось,
            # но НЕ озвучивалось. Живьём: 60 законных `config.reload` на `devices` →
            # `audit.dropped` 0 → 22, контроль `seg` = 0, и ни одного слова в логах.
            # Мерило 1 требует счёт И голос: «кто поставил ключ» уезжает из кольца
            # первым, и узнаётся это в инциденте — то есть позже всего.
            #
            # Голос ОДИН НА УСЛОВИЕ, а не на запись: озвучь каждое вытеснение — и
            # поток смен превратится в поток строк о потоке смен (тот же довод, по
            # которому подряд идущие записи схлопываются абзацем выше).
            overflowing = self.ring.maxlen is not None and len(self.ring) >= self.ring.maxlen
            first_overflow = overflowing and not self._overflow_announced
            if first_overflow:
                self._overflow_announced = True
            self.ring.append(entry)

        if first_overflow:
            self._announce_overflow()

        # Повтор в журнал не пишется: он и есть тот самый поток строк, ради
        # которого схлопывание заведено. Первое вхождение объявлено громко, а
        # то, что условие ещё держится, видно счётчиком `repeats` в readback'е
        # `introspect.observability`.
        self._announce(entry)
        self._emit_document(entry)
        return entry

    def _announce_overflow(self) -> None:
        """Сказать вслух, что кольцо аудита начало терять старые записи (Н2-3).

        Строка идёт тем же путём, что и записи (``self.log``), и помечена как
        ошибочная: это ПОТЕРЯ, а не смена. Считать её нечем отдельно —
        :meth:`dropped` уже считает, и второй счётчик разошёлся бы с кольцом.

        Вне лока: строка делает файловое I/O, а держать на нём лок кольца,
        которого ждут писатели смен, незачем (тот же довод, что у ``_announce``).
        """
        if self.log is None:
            return
        try:
            self.log(
                f"[observability-audit] кольцо заполнено ({self.ring.maxlen} записей) — "
                f"старые смены вытесняются; счёт вытесненных спрашивать у "
                f"introspect.observability (audit.dropped)",
                True,
            )
        except Exception as exc:  # noqa: BLE001 — журнал не имеет права ронять смену
            self._overflow_log_failed = repr(exc)

    def _emit_document(self, entry: Dict[str, Any]) -> None:
        """Отдать запись в плоскость документов — долговечный запрашиваемый след.

        **Писатель один, носителей два, и это не два реестра.** Строка журнала и
        документ рождаются здесь, из ОДНОЙ ``entry``, и потому разойтись по содержанию
        не могут. Разные у них не факты, а сроки и способ чтения: журнал ротируется за
        дни и читается глазами, документ живёт по своему сроку и отвечает на запрос.
        Именно поэтому «когда включили DEBUG» перестаёт быть вопросом к grep'у.

        Повтор сюда не попадает по той же причине, что и в журнал: схлопнутая запись —
        не новая смена, а то же условие, всё ещё длящееся (см. ``record``).

        Отказ приёмника глушится: аудит наблюдает, а не мешает — он зовётся из пути
        смены конфигурации, и падение БД не имеет права отменить уже случившуюся смену.
        Но глушение **именное**: отказ помечается в самой записи, как у журнала, иначе
        документ считался бы записанным, а его бы не было.

        **Бюджет вызова (m-3 ревью Ф8, замерено).** Сток зовётся СИНХРОННО из пути
        смены конфигурации. Под конкуренцией 6 процессов-писателей в один файл SQLite:
        медиана 3.6 мс, p95 82 мс, **max 928 мс** (под WAL max 712 мс — WAL снимает
        блокировку читателя, но не конкуренцию писателей). Столько может занять
        `config.reload`. Терпимо ровно потому, что смены наблюдаемости редки: аудит —
        единицы записей на инцидент, а не поток. Писателя-посредника поэтому не
        заводится (замер воспроизведён дважды, 300/300 без потерь). Если у плоскости
        появится клиент с частотой выше единиц в секунду — бюджет придётся пересчитать,
        и вот тогда посредник окупится.

        **Конверт кладётся ПОСЛЕ ``**entry`` (m-4).** ``kind``/``ts``/``summary`` — не
        поля смены, а идентичность записи в плоскости документов, и писатель не вправе
        их перебить своим ``extra``: запись аудита с ключом ``kind`` уехала бы в чужой
        род, где её не найдёт ни ретеншен аудита, ни чтение вкладки.
        """
        if self.sink is None:
            return
        document = {
            **entry,
            "kind": "audit",
            "ts": entry.get("ts", self.clock()),
            "source": self.source,
            "summary": f"{entry.get('action', '?')} {entry.get('key', '')}".strip(),
        }
        try:
            if self.sink(document) is False:
                entry["document_failed"] = True
        except Exception as exc:  # noqa: BLE001 — см. докстринг
            entry["document_failed"] = True
            entry["document_error"] = str(exc)[:200]

    def _announce(self, entry: Dict[str, Any]) -> None:
        """Одна строка в журнал процесса — долговечный след записи.

        Best-effort по контракту: аудит наблюдает, а не мешает. Но проглатывание
        здесь **именное**: отказ журнала помечается в самой записи
        (``log_failed``), иначе «следа нет» и «след не смог записаться» стали бы
        неотличимы — ровно класс «проглоченный сбой», задокументированный на
        этом проекте.
        """
        if self.log is None:
            return
        try:
            self.log(format_entry(entry), not entry.get("ok", True))
        except Exception as exc:  # noqa: BLE001 — журнал не имеет права ронять смену
            entry["log_failed"] = repr(exc)

    def entries(self, limit: Optional[int] = None, action: Optional[str] = None) -> List[Dict[str, Any]]:
        """Хвост кольца, новейшие в конце. ``action`` — фильтр по виду смены.

        ``limit=0`` → пустой список (а не всё кольцо: срез ``items[-0:]`` ==
        ``items[0:]``), ``limit<0`` — тоже пустой. Зеркало контракта
        ``backend_ctl.audit.AuditLog.records``, чтобы два журнала не отвечали
        по-разному на один и тот же вопрос.
        """
        # Копии, а не ссылки на живые записи кольца (advisory A4 ревью 5.9):
        # `_announce` дописывает в запись `log_failed` УЖЕ после публикации, и
        # сериализация ответа `introspect.observability` могла бы застать
        # мутацию словаря, который она в этот момент обходит.
        with self._lock:
            items = [dict(e) for e in self.ring]
        if action is not None:
            items = [e for e in items if e.get("action") == action]
        if limit is not None:
            items = items[-limit:] if limit > 0 else []
        return items

    def dropped(self) -> int:
        """Сколько записей вытеснено из кольца.

        Вычисляется, а не хранится: второй счётчик рано или поздно разошёлся бы
        с кольцом, и тогда «аудит полон» стало бы неотличимо от «смен не было» —
        то есть ровно та невидимость, ради которой поле и заведено.
        """
        with self._lock:
            return max(0, self.seq - len(self.ring))

    def view(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Блок аудита для ``introspect.observability``.

        Все три поля снимаются ОДНИМ взятием лока (advisory A5 ревью 5.9): под
        конкурентной записью тройка «seq / entries / dropped», собранная тремя
        заходами, могла бы содержать запись с номером БОЛЬШЕ объявленного ``seq``
        — то есть ответ противоречил бы сам себе.
        """
        with self._lock:
            items = [dict(e) for e in self.ring]
            total = self.seq
            dropped = max(0, total - len(items))
        if limit is not None:
            items = items[-limit:] if limit > 0 else []
        return {"entries": items, "seq": total, "dropped": dropped}


def format_entry(entry: Dict[str, Any]) -> str:
    """Запись → строка журнала. Читаемая человеком, а не JSON-дамп.

    Формат один на все действия: в инциденте строки этих смен читают глазами
    вперемешку с остальным журналом, и разный синтаксис у каждого действия
    заставлял бы вспоминать, какое поле где.
    """
    parts = [f"[observability-audit] {entry.get('action')} origin={entry.get('origin')}"]
    if "key" in entry:
        parts.append(f"key={entry['key']}")
    if "keys" in entry:
        listed = ", ".join(entry["keys"]) or "—"
        parts.append(f"keys=[{listed}]")
    if "value" in entry:
        parts.append(f"value={entry['value']!r}")
    # Задача 5.4: ключи вне контракта — в СТРОКЕ, а не только в кольце. Поле
    # кладёт `replace_layer` на всех пяти файловых дорогах (файлу не отказывают —
    # опечатка в спутнике не имеет права валить switch рецепта), и без вывода
    # здесь единственным следом остался бы readback, куда за ним никто не пойдёт:
    # спрашивают обычно «почему настройка не действует», а не «что в кольце».
    if entry.get("unknown_keys"):
        parts.append(f"ВНЕ КОНТРАКТА (ключ есть, эффекта нет): [{', '.join(entry['unknown_keys'])}]")
    if entry.get("ttl_sec") is not None:
        parts.append(f"ttl={entry['ttl_sec']}с")
    if not entry.get("ok", True):
        parts.append(f"НЕ УДАЛОСЬ: {entry.get('error', 'причина не названа')}")
    return " ".join(parts)


def make_audit_log(svc: Any) -> Optional[Callable[[str, bool], None]]:
    """Колбэк долговечного следа для процесса ``svc`` (``None`` — журнала нет).

    Уровень выбирается записью, а не вызывающим: успешная смена — INFO, неудачная
    — WARNING. Смена наблюдаемости штатна, но её **провал** обязан быть заметен в
    журнале без фильтра по модулю.
    """
    info = getattr(svc, "_log_info", None) or getattr(svc, "log_info", None)
    warn = getattr(svc, "_log_warning", None) or getattr(svc, "log_warning", None) or info
    if not callable(info):
        return None

    def _log(message: str, failed: bool) -> None:
        sink = warn if (failed and callable(warn)) else info
        try:
            sink(message, module="observability")
        except TypeError:  # логгер без kwarg `module` — сообщение важнее формы
            sink(message)

    return _log


__all__ = [
    "ObservabilityAudit",
    "AUDIT_HISTORY",
    "ACTIONS",
    "ACTION_SET",
    "ACTION_TOUCH",
    "ACTION_RESET",
    "ACTION_CLEAR",
    "ACTION_EXPIRE",
    "ACTION_PERSIST",
    "ACTION_LAYER",
    "ACTION_REBUILD",
    "format_entry",
    "make_audit_log",
]
