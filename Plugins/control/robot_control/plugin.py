"""RobotControlPlugin — управление отбраковкой по результатам детекции.

Processing-плагин: принимает item с detections (от blob_detector),
фильтрует дефекты по min_defect_area, принимает решение reject/pass.
Ведёт статистику: total_inspected, total_rejected, reject_rate, total_not_inspected.

Task 4.7d-4: принимает маркер ``not_inspected`` (кадр выброшен при переполнении и НЕ
проверен): по умолчанию reject («непроверенное = брак»), регистр
``not_inspected_action`` может заменить на pass. Маркер — не осмотр: он не входит в
total_inspected/total_rejected, не пишет вердикт-документ и не трогает фронт решения.

Ф8.7: решение об отбраковке — **вердикт о качестве**, и он уходит документом в
плоскость документов (``ctx.write_document``), а не строкой в диагностический
журнал. Причина в сроках: файлы логов ротируются за 7 суток / 200 МБ (Ф6.9), а
вердикт о браке в промышленности спрашивают годами. Плоскость даёт ему свой
срок (``retention_sec.verdict``), и чистка логов его не касается.

Ф4 (задача 4.1): на КАЖДУЮ единицу пишется одна широкая запись
(``ctx.write_event``) — вердикт, счётчики, ROI и порог в ОДНОЙ строке плоскости
логов. Она отвечает на «почему изделие N забраковано» без сборки ответа по
россыпи записей, а с вердикт-документом сходится по ``trace_id``. Поток этих
записей прорежен настройкой ``observability.events`` (по умолчанию не пишется
вовсе); фронт решения идёт мимо отбора всегда.

Ф5 (задача 5.1): на фронте pass→reject, ПОСЛЕ широкой записи и вердикта,
вызывается ``ctx.flight_dump("reject", trace_id=…)`` — кольцо последних записей
процесса уходит в файл ``<логи>/<процесс>/flight/``. Это ответ на «что
происходило вокруг момента брака», которого не даёт ни одна отдельная запись.
По умолчанию механизм выключен (``observability.flight.enabled``), и выключенный
он отвечает названным отказом, а не тишиной.

Task 5.2 (контракт привода, ADR-PM-051): конвейер не ждёт механизма. В ``process()``
нет ``time.sleep``: отбраковка ставится в планировщик процесса (``ctx.scheduler``)
целью ``capture_ts + transit_ms`` и исполняется его воркером. Устаревшая цель не
стреляет, а считается (``actuation_missed_items``). ``transit_ms == 0`` — привод
срабатывает сразу на решении (``immediate``), планировщик не создаётся.

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import threading

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin
from multiprocess_framework.modules.router_module.middleware.not_inspected_marker import is_marker
from Services.documents.interfaces import KIND_VERDICT

from .registers import RobotControlRegisters


@register_plugin(
    "robot_control",
    category="processing",
    description="Управление отбраковкой по результатам детекции",
)
class RobotControlPlugin(ProcessModulePlugin):
    """Плагин принятия решений об отбраковке.

    Получает список detections от blob_detector, фильтрует дефекты
    по минимальной площади и выдаёт inspection_result с решением reject/pass.
    """

    name = "robot_control"
    category = "processing"
    # Task 4.7d-4: плагин принимает маркер not_inspected (проверка портов маркера — 4.7d-2).
    accepts_markers = True

    inputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="Кадр",
        ),
        Port(
            name="detections",
            dtype="list[dict]",
            shape="N",
            description="Детекции от blob_detector",
        ),
    ]
    outputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="Кадр (без изменений)",
        ),
        Port(
            name="inspection_result",
            dtype="dict",
            shape="1",
            description="Результат инспекции",
        ),
    ]

    commands = {
        "enable": "cmd_enable",
        "disable": "cmd_disable",
        "set_delay": "cmd_set_delay",
        "reset_counters": "cmd_reset_counters",
        "get_stats": "cmd_get_stats",
    }
    register_class = RobotControlRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        # Счётчики статистики (не в register — runtime-only)
        self._total_inspected: int = 0
        self._total_rejected: int = 0
        # Task 4.7d-4: маркеры not_inspected — отдельный счёт, в total_inspected не входят.
        self._total_not_inspected: int = 0

        # Ф8.7 — вердикты. `_rejecting` держит ФРОНТ решения: документ пишется
        # на переходе pass→reject, а не на каждом кадре брака (см. _write_verdict).
        self._rejecting: bool = False
        self._verdicts_written: int = 0
        self._verdicts_unwritten: int = 0
        self._verdict_gap_reported: bool = False

        # Task 5.2 — счётчики привода этого плагина. fired пишут ДВА потока
        # (immediate — поток исполнителя, scheduled — воркер actuation), поэтому
        # под замком; missed/unscheduled пишет только поток исполнителя.
        self._actuation_lock = threading.Lock()
        self._actuation_fired_items: int = 0
        self._actuation_missed_items: int = 0
        self._actuation_unscheduled_items: int = 0
        # Планировщик процесса тронут этим плагином: тогда stats() читается в
        # cmd_get_stats. Без этого флага get_stats создавал бы планировщик сам.
        self._scheduler_used: bool = False
        # WARNING об устаревшем reject_delay_ms — один раз на экземпляр плагина.
        self._reject_delay_warned: bool = False

        ctx.log_info(
            f"RobotControlPlugin: enabled={self._reg.enabled}, "
            f"min_defect_area={self._reg.min_defect_area}, "
            f"transit_ms={self._reg.transit_ms}, "
            f"reject_delay_ms={self._reg.reject_delay_ms}, "
            f"not_inspected_action={self._reg.not_inspected_action}"
        )

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        """Принять решение reject/pass по списку detections.

        Алгоритм:
        0. Маркер not_inspected → своя ветка (_process_marker), дальше не идём
        1. Инкремент total_inspected
        2. Если disabled → pass (reason=disabled)
        3. Фильтрация detections по min_defect_area
        4. Ограничение по max_detections_for_reject (если > 0)
        5. Если есть дефекты → reject + постановка привода (без ожидания)
        6. Запись inspection_result в item
        """
        # Task 4.7d-4: маркер переполнения — ПЕРВАЯ ветка, до счётчика осмотренных.
        # Это не кадр, а «кадр не проверен»: total_inspected, _total_rejected, вердикт-
        # документы и фронт _rejecting в любом режиме не трогаем (иначе маркер посреди
        # серии брака сбросил бы фронт, и следующий кадр дал бы второй вердикт).
        if is_marker(item):
            return self._process_marker(item)

        self._total_inspected += 1

        # Плагин отключён — всегда пропускаем
        if not self._reg.enabled:
            # Фронт сбрасывается и здесь: выключение посреди брака завершает
            # текущую отбраковку. Иначе повторное включение на том же дефекте
            # не дало бы вердикта вовсе — фронта-то не было.
            self._rejecting = False
            result = {
                "action": "pass",
                "reason": "disabled",
            }
            item["inspection_result"] = result
            # Ф4: выключенный плагин — тоже состояние линии, и единица через него
            # прошла. Молчание здесь означало бы «изделий не было», тогда как их
            # просто никто не судил.
            self._write_unit_event(item, result, (), decisive=False, **self._no_actuation())
            return item

        # Получаем список детекций
        detections: list[dict] = item.get("detections", [])

        # Фильтруем дефекты по минимальной площади
        defects = [d for d in detections if d.get("area", 0) >= self._reg.min_defect_area]

        # Ограничиваем количество дефектов для анализа (если задано)
        if self._reg.max_detections_for_reject > 0:
            defects = defects[: self._reg.max_detections_for_reject]

        # Принимаем решение
        front = False
        if len(defects) > 0:
            action = "reject"
            self._total_rejected += 1
            # Вердикт — на ФРОНТЕ решения, до срабатывания привода: оно наступит
            # через transit_ms, и документ, записанный по выстрелу, нёс бы
            # время механизма, а не время решения (решение 6: fire пишет только
            # счётчики).
            front = not self._rejecting
            if front:
                self._write_verdict(item, defects)
            self._rejecting = True
            capture_ts = item.get("capture_ts")
            actuation = self._actuate(1, capture_ts, capture_ts)
        else:
            action = "pass"
            self._rejecting = False
            actuation = self._no_actuation()

        # Вычисляем коэффициент отбраковки
        rate = self._total_rejected / self._total_inspected if self._total_inspected > 0 else 0.0

        result = {
            "action": action,
            "defect_count": len(defects),
            "total_inspected": self._total_inspected,
            "total_rejected": self._total_rejected,
            "reject_rate": round(rate, 4),
        }
        item["inspection_result"] = result

        # Ф4: широкая запись — ОДНА на единицу, и её решительность совпадает с
        # фронтом вердикта. Две записи (фронт + поток) на одном кадре означали бы
        # два ответа на вопрос «что было с этим изделием», а вопрос один.
        self._write_unit_event(item, result, defects, decisive=front, **actuation)

        # Ф5 (5.1): дамп кольца — ПОСЛЕДНИМ из трёх жестов фронта, и порядок
        # несущий (Р5.1-11). Кольцо снимается в момент вызова: позови мы дамп
        # раньше `_write_unit_event`, широкой записи забракованной единицы в
        # нём бы не было — а приёмка требует именно её, и пункт был бы зелёным
        # на пустом месте.
        if front:
            self._dump_flight(item, defects)

        return item

    def _process_marker(self, item: dict) -> dict:
        """Решение по маркеру not_inspected: политика «непроверенное = брак» (по умолчанию reject).

        Task 5.2: читает ОБЕ формы — маркер 4.7d-1 (один кадр, ``capture_ts``) и
        запись о разрыве 5.3 (``count``, ``first/last_capture_ts``, гистограммы
        ``reasons``/``sources``, список ``trace_ids``). Запись о разрыве — ОДНА
        постановка с окном ``[first + transit, last + transit]``, а не по кадру.
        """
        count = int(item.get("count", 1) or 1)
        first = item.get("first_capture_ts", item.get("capture_ts"))
        last = item.get("last_capture_ts", item.get("capture_ts"))
        self._total_not_inspected += count
        # Причина и источник: у записи о разрыве со смешанными причинами одного
        # `reason` нет — едет гистограмма, а не None.
        origin = {
            "origin": item["reason"] if "reason" in item else item.get("reasons"),
            "source": item["source"] if "source" in item else item.get("sources"),
        }
        if not self._reg.enabled:
            result = {"action": "pass", "reason": "disabled", **origin}
        else:
            result = {"action": self._reg.not_inspected_action, "reason": "not_inspected", **origin}
        item["inspection_result"] = result
        # Привод — как у обычного брака; pass-маркер в очередь не ставится.
        actuation = self._actuate(count, first, last) if result["action"] == "reject" else self._no_actuation()
        extra = {"count": count, **actuation}
        if "trace_ids" in item:
            # Поимённый поиск у записи о разрыве — по trace_ids; trace_id пуст.
            extra["trace_ids"] = list(item.get("trace_ids") or [])
        # Одна широкая запись на исход (учёт по trace_id, 4.7d-5); не решающая — вердикта нет.
        self._write_unit_event(item, result, [], decisive=False, **extra)
        return item

    # --- Привод (Task 5.2, ADR-PM-051) ---

    def _transit_ms(self) -> int:
        """``effective_transit = transit_ms or reject_delay_ms`` — читается на каждом вызове."""
        return int(self._reg.transit_ms or self._reg.reject_delay_ms or 0)

    def _no_actuation(self) -> dict:
        """Поля широкой записи для исхода без привода (pass, выключенный плагин)."""
        return {"actuation": "none", "fire_at": None, "transit_ms": self._transit_ms()}

    def _actuate(self, count: int, first_ts: float | None, last_ts: float | None) -> dict:
        """Поставить срабатывание привода на ``count`` единиц; вернуть поля широкой записи.

        Ожидания здесь нет: при ``transit > 0`` цель уходит в ``ctx.scheduler`` и
        метод сразу возвращается. Значения ``actuation``: ``immediate`` (transit 0,
        выстрел синхронно), ``unscheduled`` (нет ``capture_ts``), ``scheduled`` /
        ``missed`` (ответ планировщика).
        """
        if self._reg.reject_delay_ms and not self._reject_delay_warned:
            self._reject_delay_warned = True
            self._ctx.log_warning(
                f"RobotControlPlugin: регистр reject_delay_ms={self._reg.reject_delay_ms} устарел — "
                "это алиас transit_ms (действует при transit_ms=0), сна в process() больше нет"
            )
        transit_ms = self._transit_ms()
        if transit_ms <= 0:
            # Решение 8: без транзита планировщик не нужен и не создаётся.
            self._on_actuation_fire(count)
            return {"actuation": "immediate", "fire_at": None, "transit_ms": 0}
        if first_ts is None or last_ts is None:
            self._actuation_unscheduled_items += count
            return {"actuation": "unscheduled", "fire_at": None, "transit_ms": transit_ms}
        transit_s = transit_ms / 1000.0
        fire_at = float(first_ts) + transit_s
        self._scheduler_used = True
        status = self._ctx.scheduler.schedule(
            fire_at,
            float(last_ts) + transit_s,
            count,
            self._on_actuation_fire,
            tolerance_s=self._reg.actuation_tolerance_ms / 1000.0,
        )
        if status == "missed":
            self._actuation_missed_items += count
        return {"actuation": status, "fire_at": fire_at, "transit_ms": transit_ms}

    def _on_actuation_fire(self, count: int) -> None:
        """Выстрел привода. Пишет ТОЛЬКО счётчики (решение 6): вердикт уже записан на решении.

        Зовётся из потока исполнителя (``immediate``) или из воркера ``actuation``
        (``payload(count)`` диспетчера планировщика процесса).
        """
        with self._actuation_lock:
            self._actuation_fired_items += count

    # --- Дамп кольца записей (Ф5, задача 5.1) ---

    def _dump_flight(self, item: dict, defects: list[dict]) -> None:
        """Выгрузить кольцо записей процесса на фронте pass→reject.

        **На фронте, а не на кадре брака** — та же арифметика, что у вердикта:
        дефектное изделие видно детектору десятки кадров подряд (живой прогон:
        95 кадров брака → 1 срабатывание), а дамп кладёт на диск сотни строк.
        Дамп на каждый кадр превратил бы улику в шум и съел бы ретеншен за одну
        серию.

        **``trace_id`` в шапке — не украшение.** Он единственное, что связывает
        дамп с широкой записью и вердикт-документом той же единицы; без него три
        свидетельства об одном изделии сходятся сверкой времени, то есть
        догадкой. Пусто — если кадр пришёл без следа, подделывать нечем.

        Отказ дампа линию не роняет и решения не меняет: ``inspection_result``
        уже собран и уедет своей дорогой (Р5.1-14). Своего счёта потерь здесь
        нет намеренно — три класса отказа считает сам рекордер, и второй счётчик
        того же события разошёлся бы с первым (тот же довод, что у
        ``note_document_refused``); смотреть их в
        ``introspect.observability -> flight``.
        """
        self._ctx.flight_dump(
            "reject",
            trace_id=str(item.get("trace_id") or "") if isinstance(item, dict) else "",
            reject_seq=self._total_rejected,
            inspected_seq=self._total_inspected,
            defect_count=len(defects),
            min_defect_area=self._reg.min_defect_area,
        )

    # --- Широкая запись о единице (Ф4, задача 4.1) ---

    #: Сколько bbox'ов дефектов уезжает в запись. Кадр с шумной маской даёт сотни
    #: блобов, и список без потолка сделал бы вес записи функцией шума — ровно на
    #: потоковом пути, чью цену эта задача обязана назвать числом. Опущенное
    #: считается вслух (`roi_omitted`), молчаливое усечение врало бы о числе
    #: дефектов.
    ROI_LIMIT = 8

    def _write_unit_event(
        self,
        item: dict,
        result: dict,
        defects,
        *,
        decisive: bool,
        **extra,
    ) -> None:
        """Одна широкая запись обо всей единице работы.

        **Чего здесь нет и не будет — ``confidence``.** У площадного детектора
        (blob_detector: ``bbox``/``center``/``area``) вероятностной модели нет по
        построению, и написать ``confidence: 1.0`` значило бы соврать уверенно.
        Решение выносит ПОРОГ, поэтому в записи едут ``defect_area_max`` и
        ``min_defect_area`` — то, чем вердикт можно оспорить.

        Отказ записи линию не роняет и решения не меняет: ``inspection_result``
        уже собран и уедет своей дорогой.
        """
        areas = [float(d.get("area", 0) or 0) for d in defects]
        boxes = [d.get("bbox") for d in defects if isinstance(d.get("bbox"), (list, tuple))]
        fields = {
            **result,
            "roi": [list(b) for b in boxes[: self.ROI_LIMIT]],
            "roi_omitted": max(0, len(boxes) - self.ROI_LIMIT),
            "defect_area_max": max(areas) if areas else 0.0,
            "min_defect_area": self._reg.min_defect_area,
            # Task 5.2: actuation / fire_at / transit_ms; у маркеров ещё count / trace_ids.
            **extra,
        }
        if decisive:
            # Ключ к вердикт-документу той же единицы: у документа он тоже есть
            # (см. _write_verdict), и по паре «trace_id + reject_seq» две записи
            # сходятся без догадок.
            fields["reject_seq"] = self._total_rejected
        # Маркер (в result есть ключ origin — и при not_inspected, и при disabled) называет
        # свой тип прямо в тексте: «reject: дефектов 0» читалось бы как брак без дефектов,
        # а FTS ищет только по тексту (message/module/process), не по полям записи.
        if "origin" in result:
            summary = f"{result.get('action')}: не проверен ({result.get('origin')}@{result.get('source')})"
        else:
            summary = f"{result.get('action')}: дефектов {len(areas)}"
        self._ctx.write_event(
            "inspection",
            summary,
            unit=item,
            decisive=decisive,
            **fields,
        )

    # --- Вердикт как документ (Ф8.7) ---

    def _write_verdict(self, item: dict, defects: list[dict]) -> None:
        """Записать вердикт об отбраковке в плоскость документов.

        **Почему на фронте, а не на каждом кадре брака.** Дефектное изделие
        видно детектору десятки кадров подряд, а ``append`` идёт синхронно в
        SQLite: медиана 3.6 мс, p95 82 мс, max 928 мс под конкуренцией шести
        процессов. Бюджет кадра на 25 FPS — 40 мс. Документ на каждый кадр
        останавливал бы линию и давал бы вместо одного решения десятки строк
        об одном и том же. Фронт pass→reject — одно решение, один документ.

        **Чего здесь честно нет.** Идентификатора изделия: конвейер его не
        несёт, и связать вердикт с конкретной деталью нечем. ``reject_seq`` —
        порядковый номер отбраковки в этом запуске процесса, а не номер
        изделия; переживает он ровно столько, сколько процесс. Per-part
        traceability уровня MES потребует внешнего идентификатора и в объём
        задачи не входит.

        **``trace_id`` (Ф4, 4.1).** След КАДРА, на котором вынесено решение, — то
        единственное, что связывает документ с широкой записью той же единицы и с
        её строками журнала. До Ф4 его здесь не было, и «покажи всё про это
        изделие» отвечалось сверкой времени, то есть догадкой. Пусто — если кадр
        пришёл без следа (источник его не назначил); подделывать нечем.

        Отказ записи линию не роняет: решение об отбраковке уже принято и
        уедет по своей дороге (``inspection_result``) независимо от того,
        удалось ли записать документ.
        """
        areas = [float(d.get("area", 0) or 0) for d in defects]
        summary = f"отбраковка #{self._total_rejected}: дефектов {len(defects)}"
        written = self._ctx.write_document(
            KIND_VERDICT,
            summary,
            action="reject",
            trace_id=str(item.get("trace_id") or "") if isinstance(item, dict) else "",
            reject_seq=self._total_rejected,
            inspected_seq=self._total_inspected,
            defect_count=len(defects),
            defect_area_max=max(areas) if areas else 0.0,
            defect_area_total=sum(areas),
            # Порог, по которому вынесено решение: без него вердикт нечем
            # оспорить — «почему брак» отвечается только вместе с ним.
            min_defect_area=self._reg.min_defect_area,
        )
        if written:
            self._verdicts_written += 1
            return

        self._verdicts_unwritten += 1
        if not self._verdict_gap_reported:
            # Ровно один раз на запуск: причина не меняется от кадра к кадру,
            # а линия выдаёт брак сериями — повтор дал бы шторм на пути,
            # который и без того признан отказавшим.
            self._verdict_gap_reported = True
            self._ctx.log_error(
                "RobotControlPlugin: вердикт не записан — плоскость документов "
                "не настроена (ключ observability.documents) либо запись отказала; "
                "счёт потерь в get_stats.verdicts_unwritten"
            )

    # --- Команды ---

    def cmd_enable(self, data: dict) -> dict:
        """Включить отбраковку."""
        self._reg.enabled = True
        self._ctx.log_info("RobotControlPlugin: отбраковка включена")
        return {"status": "ok", "enabled": True}

    def cmd_disable(self, data: dict) -> dict:
        """Выключить отбраковку."""
        self._reg.enabled = False
        self._ctx.log_info("RobotControlPlugin: отбраковка выключена")
        return {"status": "ok", "enabled": False}

    def cmd_set_delay(self, data: dict) -> dict:
        """Устарело (Task 5.2): пишет ``transit_ms``, а не ``reject_delay_ms``."""
        delay_ms = max(0, int(data.get("delay_ms", 0)))
        self._reg.transit_ms = delay_ms
        self._ctx.log_warning(f"RobotControlPlugin: set_delay устарела, пишет transit_ms={delay_ms} мс")
        return {"status": "ok", "delay_ms": delay_ms, "transit_ms": delay_ms}

    def cmd_reset_counters(self, data: dict) -> dict:
        """Обнулить счётчики статистики.

        Фронт решения (``_rejecting``) НЕ трогается: он часть текущего состояния
        линии, а не статистики. Сбрось его здесь — и следующий кадр той же
        отбраковки выдал бы второй вердикт об одном изделии.
        """
        self._total_inspected = 0
        self._total_rejected = 0
        self._total_not_inspected = 0
        self._verdicts_written = 0
        self._verdicts_unwritten = 0
        with self._actuation_lock:
            self._actuation_fired_items = 0
        self._actuation_missed_items = 0
        self._actuation_unscheduled_items = 0
        self._ctx.log_info("RobotControlPlugin: счётчики сброшены")
        return {"status": "ok"}

    def cmd_get_stats(self, data: dict) -> dict:
        """Вернуть текущую статистику инспекции.

        ``verdicts_written`` / ``verdicts_unwritten`` — путь наружу для Ф8.7:
        расхождение с ``total_rejected`` видно без похода в БД. Ненастроенная
        плоскость и отказавшая запись здесь неразличимы намеренно — плагин
        различить их не может, а причину называет разовая строка журнала.
        """
        rate = self._total_rejected / self._total_inspected if self._total_inspected > 0 else 0.0
        # late_fires / unfired_on_stop_items — счёт ПЛАНИРОВЩИКА ПРОЦЕССА (он один на
        # процесс): плагин не видит, опоздал ли выстрел. fired/missed/unscheduled — свои.
        sched = self._ctx.scheduler.stats() if self._scheduler_used else {}
        with self._actuation_lock:
            fired = self._actuation_fired_items
        return {
            "status": "ok",
            "actuation_fired_items": fired,
            "actuation_missed_items": self._actuation_missed_items,
            "actuation_late_fires": int(sched.get("late_fires", 0)),
            "actuation_unscheduled_items": self._actuation_unscheduled_items,
            "actuation_unfired_on_stop_items": int(sched.get("unfired_on_stop_items", 0)),
            "total_inspected": self._total_inspected,
            "total_rejected": self._total_rejected,
            "reject_rate": round(rate, 4),
            "total_not_inspected": self._total_not_inspected,
            "verdicts_written": self._verdicts_written,
            "verdicts_unwritten": self._verdicts_unwritten,
        }
