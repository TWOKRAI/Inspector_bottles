"""RobotControlPlugin — управление отбраковкой по результатам детекции.

Processing-плагин: принимает item с detections (от blob_detector),
фильтрует дефекты по min_defect_area, принимает решение reject/pass.
Ведёт статистику: total_inspected, total_rejected, reject_rate.

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

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin
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

        # Ф8.7 — вердикты. `_rejecting` держит ФРОНТ решения: документ пишется
        # на переходе pass→reject, а не на каждом кадре брака (см. _write_verdict).
        self._rejecting: bool = False
        self._verdicts_written: int = 0
        self._verdicts_unwritten: int = 0
        self._verdict_gap_reported: bool = False

        ctx.log_info(
            f"RobotControlPlugin: enabled={self._reg.enabled}, "
            f"min_defect_area={self._reg.min_defect_area}, "
            f"reject_delay_ms={self._reg.reject_delay_ms}"
        )

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        """Принять решение reject/pass по списку detections.

        Алгоритм:
        1. Инкремент total_inspected
        2. Если disabled → pass (reason=disabled)
        3. Фильтрация detections по min_defect_area
        4. Ограничение по max_detections_for_reject (если > 0)
        5. Если есть дефекты → reject + задержка
        6. Запись inspection_result в item
        """
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
            self._write_unit_event(item, result, (), decisive=False)
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
            # Вердикт — на ФРОНТЕ решения, до задержки: она может длиться
            # сотни миллисекунд, и документ, записанный после неё, нёс бы
            # время механизма, а не время решения.
            front = not self._rejecting
            if front:
                self._write_verdict(item, defects)
            self._rejecting = True
            # Задержка перед отбраковкой (например, для синхронизации с механизмом)
            if self._reg.reject_delay_ms > 0:
                time.sleep(self._reg.reject_delay_ms / 1000.0)
        else:
            action = "pass"
            self._rejecting = False

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
        self._write_unit_event(item, result, defects, decisive=front)

        return item

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
        }
        if decisive:
            # Ключ к вердикт-документу той же единицы: у документа он тоже есть
            # (см. _write_verdict), и по паре «trace_id + reject_seq» две записи
            # сходятся без догадок.
            fields["reject_seq"] = self._total_rejected
        self._ctx.write_event(
            "inspection",
            f"{result.get('action')}: дефектов {len(areas)}",
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
        """Установить задержку отбраковки в миллисекундах."""
        delay_ms = max(0, int(data.get("delay_ms", 0)))
        self._reg.reject_delay_ms = delay_ms
        self._ctx.log_info(f"RobotControlPlugin: задержка установлена {delay_ms} мс")
        return {"status": "ok", "delay_ms": delay_ms}

    def cmd_reset_counters(self, data: dict) -> dict:
        """Обнулить счётчики статистики.

        Фронт решения (``_rejecting``) НЕ трогается: он часть текущего состояния
        линии, а не статистики. Сбрось его здесь — и следующий кадр той же
        отбраковки выдал бы второй вердикт об одном изделии.
        """
        self._total_inspected = 0
        self._total_rejected = 0
        self._verdicts_written = 0
        self._verdicts_unwritten = 0
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
        return {
            "status": "ok",
            "total_inspected": self._total_inspected,
            "total_rejected": self._total_rejected,
            "reject_rate": round(rate, 4),
            "verdicts_written": self._verdicts_written,
            "verdicts_unwritten": self._verdicts_unwritten,
        }
