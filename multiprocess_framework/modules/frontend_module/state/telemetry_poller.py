# -*- coding: utf-8 -*-
"""telemetry_poller.py — опрос уровней телеметрии по видимости (Task 3.3).

Вторая дорога в тот же read-model. Push (``state.changed`` → ``TelemetryViewModel.
on_state_delta``) остаётся дефолтом; поллер добавляет **pull**: пока вкладка
видима, GUI сам спрашивает у процессов пакетный снимок уровней (команда
``introspect.telemetry`` → секция ``levels``, ADR-PM-035) и вливает его в тот
же снимок. Виджеты читают ``view_model.get(path)`` и не различают, push это
был или опрос — путь и значение идентичны.

**Период на цель — НЕ ``interval_sec``, когда целей больше потолка.** Раз в
``interval_sec`` срабатывает ТИК, а за тик уходит не больше ``max_in_flight``
запросов (цели обходятся по кругу). Поэтому каждая отдельная цель опрашивается
раз в::

    interval_sec × ceil(len(targets) / max_in_flight)

Боевая раскладка: 7 процессов топологии минус собственный ``gui`` = 6 целей,
``interval_sec=1.0``, ``max_in_flight=2`` → **период на цель ~3 с**, то есть
~0.33 опроса/с (замерено на стенде: 6–7 опросов на цель за 20.28 с, разброс
между целями 1 — обход равномерный). Оператор, глядя на карточку процесса,
видит числа возрастом до трёх секунд, а не до одной. Так и задумано: изоляция
пула исполнителя (потолок) важнее частоты обновления карточки — см. ADR-139 §5.

Как держатся инварианты ADR-136 — **две разные прочности, и их нельзя путать**:

* **Конструкцией держится ровно одно: серверную подписку создать нечем.**
  Конструктор не принимает ни router, ни state-proxy (enforce —
  ``test_poller_constructor_has_no_router_access``), поэтому «0 серверных
  подписок на открытие» — свойство сигнатуры, а не дисциплины.
* **Off-main — делегирован исполнителю, а не гарантирован здесь.** Поллер лишь
  обещает, что ``poll_fn`` вызывается ИСКЛЮЧИТЕЛЬНО через ``submit`` (проверяется
  двойником-«глотателем»: submit не исполняет работу → ``poll_fn`` не вызван ни
  разу). Уйдёт ли работа с main thread — решает переданный ``submit``. Синхронный
  ``submit`` (такие двойники есть в тестах) исполнит ``poll_fn`` прямо в main
  thread, и поллер этому не помешает. В проде off-main даёт
  ``RequestRunner.submit`` (``QThreadPool``), и отвечает за это composition root.
* **Скрытая вкладка = ноль трафика.** ``set_active(False)`` останавливает
  таймер; ``stop()`` — терминален (см. ниже). Оговорка: сигнала о потере фокуса
  или перекрытии окна другим окном Qt не даёт — трафик гасят скрытие,
  сворачивание и закрытие, но не «окно ушло на задний план».

Чего поллер НЕ делает — и это выбор, а не упущение:

* **Не пишет историю.** Влив идёт отдельным входом read-model
  (``ingest_poll_snapshot`` → ``ingest(record_history=False)``): кольцо истории
  имеет фиксированный ``maxlen``, и второй писатель в те же пути вытеснял бы
  точки push'а, сокращая окно спарклайна пропорционально частоте опроса.
* **Не трогает publisher-gate.** Наблюдение не мутирует наблюдаемое: вариант
  «вкладка открылась → ``telemetry_set(enabled)``» отклонён (два наблюдателя
  спорят за одну ручку). Гейт живёт своей жизнью, опрос работает и при закрытом.
* **Не пишет ключи, которых нет в ответе.** ``levels`` — это то, что собирает
  телеметрийный тик, а не весь ``processes.<name>.state``: соседние ``status``,
  ``pid``, ``frame_count``, ``error``, ``uptime``, ``drops``, ``paused``,
  ``frozen`` пишут ДРУГИЕ публикаторы push'ем (долг K-8, ADR-PM-035). Влив
  опроса кладёт ровно листья ответа и ничего не стирает.
* **Не судит о свежести по ``snapshot_ts``.** Штамп — возраст ОТВЕТА, не чисел
  (ADR-PM-035): у остановленного воркера он идёт, а ``fps`` стоит. Поллер его
  не читает и порядок ответов по нему не восстанавливает; признак движения —
  per-worker ``cycles``, и он едет в read-model как обычный лист. У процесса
  без ``CycleMetricsRecorder`` поля ``cycles`` нет вовсе — это норма (долг K-9),
  а не «завис»: отсутствующий ключ просто не пишется.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from functools import partial
from typing import Any

from PySide6.QtCore import QObject, QTimer

from multiprocess_framework.modules.frontend_module.state.telemetry_view_model import (
    TelemetryViewModel,
)
from multiprocess_framework.modules.logger_module import get_std_logger

__all__ = ["TelemetryPoller"]

_logger = get_std_logger(__name__)

# Тип off-main исполнителя: submit(fn, on_result) — fn крутится вне main thread,
# on_result доставляется обратно в main thread. Ровно форма RequestRunner.submit.
SubmitFn = Callable[[Callable[[], dict], Callable[[dict], None]], None]


def _flatten_levels(prefix: str, node: dict, out: dict[str, Any]) -> None:
    """Разложить снимок уровней в плоские пути read-model.

    Вложенный dict раскрывается точкой, лист кладётся как есть. Ключ, уже
    содержащий точки (``"state.fps"``), просто приклеивается — обе формы дают
    один и тот же путь, поэтому поллеру безразлично, пришёл ответ вложенным
    (боевая форма сборщика: ``{"workers": {...}, "state": {...}}``) или плоским.

    Пустой вложенный dict не даёт ни одного пути — и потому НЕ стирает уже
    лежащее в read-model поддерево.
    """
    for key, value in node.items():
        path = f"{prefix}.{key}"
        if isinstance(value, dict):
            _flatten_levels(path, value, out)
        else:
            out[path] = value


class TelemetryPoller(QObject):
    """Таймер опроса уровней: видимая вкладка опрашивает, скрытая молчит.

    Жизненный цикл — три состояния, и переход между ними односторонний:

    ``неактивен`` ⇄ ``активен`` → ``остановлен``

    ``set_active(True/False)`` ходит туда-обратно (показ/скрытие вкладки),
    ``stop()`` — **терминальное** состояние (аналог ``close()``/``dispose()``):
    после него ``set_active(True)`` опрос НЕ возобновляет. Так выбрано потому,
    что ``stop()`` зовётся при разрушении владельца, и «тихое воскрешение»
    поллера, переживившего свою вкладку, было бы утечкой трафика, которую
    никто не ищет.

    Args:
        poll_fn: ``(process_name) -> dict`` — блокирующий запрос снимка.
            Вызывается ТОЛЬКО внутри ``submit`` (вне main thread).
        submit: ``(fn, on_result)`` — off-main исполнитель; ``on_result``
            обязан приезжать в поток владельца поллера (main thread).
        view_model: приёмник снимка — тот же read-model, что питает push.
        interval_sec: период ТИКА, а не период опроса одной цели. За тик
            уходит не больше ``max_in_flight`` запросов, поэтому конкретная
            цель опрашивается раз в ``interval_sec × ceil(N / max_in_flight)``
            (см. докстроку модуля: живьём 1.0 с × ceil(6/2) = 3 с). Чаще, чем
            меняются метрики (тик телеметрии), смысла не имеет: опрос отдаёт
            уровень, а не поток.
        targets: имена процессов, которые надо опрашивать (обычно — видимые).
        exclude: имена, которые НИКОГДА не опрашиваются, даже если пришли в
            ``set_targets``. В проде сюда идёт собственный процесс GUI: опрос
            самого себя гонит круг ``gui → PM → gui`` по IPC.
        max_in_flight: потолок одновременных запросов. Не декоративный: они
            занимают потоки пула исполнителя, а зависшая цель держит слот до
            своего таймаута. Обход целей круговой, поэтому упёртый потолок
            задерживает опрос хвоста, но не отменяет его. **Потолок держится
            не безусловно:** он ограничивает записи о полётах, а не сами
            задачи в пуле — см. инвариант у ``flight_ttl_sec``.
        flight_ttl_sec: дедлайн записи о полёте. None → ``max(2с, 4×interval)``.
            Нужен потому, что доставка результата НЕ гарантирована (см. ниже).

            **Инвариант: flight_ttl_sec > таймаута запроса в poll_fn.**
            Выселение освобождает слот у поллера, но НЕ снимает задачу с пула:
            она докручивается до своего таймаута. Если TTL меньше таймаута,
            поллер выселит ещё живой запрос и отправит поверх него новый —
            число реально висящих запросов превысит ``max_in_flight``, а
            ``polls_expired`` начнёт считать не потери, а собственную
            нетерпеливость. Воспроизведено ревью (6 целей, потолок 2, ответ
            ровно на таймауте 3.0 с): при ``interval_sec=1.0`` (TTL 4.0)
            пик висящих = 2 и ``polls_expired=0``; при ``interval_sec=0.5``
            (TTL 2.0) пик = 4 при том же потолке и 22 «истечения» из 24
            отправленных, ни одно из которых не было настоящей потерей.
            Опасность прячется в том, что ``interval_sec`` — самая очевидная
            ручка, и её уменьшение вдвое переворачивает инвариант молча.
        parent: Qt-родитель.
    """

    def __init__(
        self,
        *,
        poll_fn: Callable[[str], dict],
        submit: SubmitFn,
        view_model: TelemetryViewModel,
        interval_sec: float = 1.0,
        targets: Sequence[str] = (),
        exclude: Sequence[str] = (),
        max_in_flight: int = 4,
        flight_ttl_sec: float | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._poll_fn = poll_fn
        self._submit = submit
        self._view_model = view_model
        self._interval_sec = float(interval_sec)
        self._exclude: frozenset[str] = frozenset(exclude)
        self._max_in_flight = max(1, int(max_in_flight))
        # Дедлайн, после которого запись о полёте считается потерянной. Дефолт —
        # 4× периода: заведомо больше нормального ответа и заведомо конечен.
        self._flight_ttl_sec = float(flight_ttl_sec) if flight_ttl_sec else max(2.0, 4.0 * self._interval_sec)
        self._targets: tuple[str, ...] = self._filtered(targets)

        self._active = False
        self._stopped = False

        # Цели с незавершённым опросом → monotonic-штамп отправки. Защита от
        # наложения тиков: медленный ответ не должен порождать очередь запросов
        # к тому же процессу — опрос отдаёт УРОВЕНЬ, второй одновременный запрос
        # ничего не добавит, а IPC-нагрузку умножит.
        #
        # Штамп, а не просто множество: доставка результата НЕ гарантирована.
        # Исполнитель может потерять callback (у RequestRunner доставка идёт
        # Qt-сигналом, и на разрушенном источнике сигнала emit поднимает
        # RuntimeError уже ПОСЛЕ успешного запроса). Без дедлайна такая запись
        # осталась бы здесь навсегда и цель молча перестала бы опрашиваться.
        self._in_flight: dict[str, float] = {}
        # Круговой курсор по целям: при упёртом потолке одновременных полётов
        # фиксированный порядок обхода уморил бы хвост списка голодом.
        self._cursor = 0

        self._polls_started = 0
        self._polls_completed = 0
        self._polls_failed = 0
        self._polls_expired = 0
        # Троттл шумного лога: одна строка на ошибку не чаще раза в 10 с.
        self._last_error_log = 0.0

        self._timer = QTimer(self)
        # Период не может быть нулевым: 0 мс = «каждый оборот event loop».
        self._timer.setInterval(max(1, int(round(self._interval_sec * 1000))))
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ #
    #  Управление (видимость вкладки)                                      #
    # ------------------------------------------------------------------ #

    def set_active(self, active: bool) -> None:
        """Включить/выключить опрос (вкладка показана/скрыта).

        Включение делает первый опрос НЕМЕДЛЕННО, не дожидаясь тика: иначе
        показанная вкладка стояла бы с прочерками целый ``interval_sec``.
        После ``stop()`` вызов игнорируется — состояние терминально.
        """
        if self._stopped:
            if active:
                _logger.debug("TelemetryPoller.set_active(True) после stop() — опрос не возобновляется")
            return

        active = bool(active)
        if active == self._active:
            return
        self._active = active

        if active:
            self._timer.start()
            self._tick()
        else:
            self._timer.stop()
            # Записи о полётах не переживают выключение: ответы на них уже
            # никого не интересуют, а оставленные записи заставили бы следующий
            # показ вкладки ждать TTL, прежде чем опросить эти цели.
            self._in_flight.clear()

    def set_targets(self, names: Sequence[str]) -> None:
        """Задать состав опрашиваемых процессов (обычно — видимые).

        Пустой список = активный поллер молчит. Смена состава не делает
        внеочередной опрос: тик и так рядом, а внеочередной сбивал бы потолок
        частоты при частых переключениях nav.
        """
        self._targets = self._filtered(names)

    def stop(self) -> None:
        """Остановить опрос НАВСЕГДА (владелец разрушается)."""
        self._stopped = True
        self._active = False
        self._timer.stop()
        self._in_flight.clear()

    def _filtered(self, names: Sequence[str]) -> tuple[str, ...]:
        """Отсеять исключённые имена (в проде — собственный процесс GUI).

        Опрашивать самого себя значит гнать круг ``gui → PM → gui`` по IPC ради
        чисел, которые процесс и так знает локально.
        """
        return tuple(name for name in names if name not in self._exclude)

    # ------------------------------------------------------------------ #
    #  Счётчики (наблюдаемость самого поллера)                             #
    # ------------------------------------------------------------------ #

    @property
    def polls_started(self) -> int:
        """Сколько опросов ОТПРАВЛЕНО (по одному на цель за тик)."""
        return self._polls_started

    @property
    def polls_completed(self) -> int:
        """Сколько ответов ПРИШЛО — включая ошибочные и отброшенные.

        Отличие от :attr:`polls_started` больше нуля — это либо ответы в
        полёте, либо потерянная работа; вторую видно по :attr:`polls_expired`.
        """
        return self._polls_completed

    @property
    def polls_failed(self) -> int:
        """Сколько ответов пришло с ``success=False`` (подмножество completed).

        На экране неудачный опрос выглядит как удачный — остаются последние
        хорошие числа. Этот счётчик единственный отличает «стабильно» от
        «протухло».
        """
        return self._polls_failed

    @property
    def polls_expired(self) -> int:
        """Сколько записей о полётах снято по дедлайну (ответ не пришёл вовсе).

        Не ноль — значит исполнитель терял callback'и; цель при этом не
        замолчала навсегда только благодаря выселению.
        """
        return self._polls_expired

    @property
    def in_flight(self) -> int:
        """Сколько опросов сейчас в полёте (потолок — ``max_in_flight``)."""
        return len(self._in_flight)

    @property
    def interval_sec(self) -> float:
        """Период ТИКА в секундах — не период опроса одной цели.

        Цель опрашивается раз в ``interval_sec × ceil(N / max_in_flight)``:
        за тик уходит не больше ``max_in_flight`` запросов. Читать это
        свойство как «частоту обновления карточки» неверно — при 6 целях и
        потолке 2 карточка обновляется втрое реже. Фактический период считать
        по :attr:`effective_interval_sec`.
        """
        return self._interval_sec

    @property
    def effective_interval_sec(self) -> float:
        """Расчётный период опроса ОДНОЙ цели — **нижняя граница**, не факт.

        ``interval_sec × ceil(len(targets) / max_in_flight)``. Меняется вместе
        с составом целей: ушёл пользователь в подвкладку одного процесса —
        период схлопывается до ``interval_sec``.

        Точен, пока ответ приходит быстрее тика. Когда процессы отвечают
        медленно, слот занят дольше тика, и настоящий период больше расчётного:
        ревью намерило 7.5–10 с против расчётных 3.0 на стенде, где каждая цель
        отвечала ровно на своём таймауте 3.0 с. То есть в тот самый момент,
        когда на это число смотрят из-за тормозов, оно занижает — поэтому
        «расчётный», а не «фактический».
        """
        if not self._targets:
            return self._interval_sec
        rounds = -(-len(self._targets) // self._max_in_flight)  # ceil без math
        return self._interval_sec * rounds

    @property
    def is_active(self) -> bool:
        """Идёт ли опрос сейчас."""
        return self._active

    # ------------------------------------------------------------------ #
    #  Механизм                                                            #
    # ------------------------------------------------------------------ #

    def _evict_stale_flights(self, now: float) -> None:
        """Снять записи о полётах, ответ на которые уже не придёт.

        Единственная дорога назад для цели, чей callback потерялся. Потеря
        реальна: доставка результата идёт через чужой исполнитель, и у
        ``RequestRunner`` она делается Qt-сигналом — на разрушенном источнике
        сигнала ``emit`` поднимает ``RuntimeError`` уже после того, как запрос
        отработал. Без выселения такая цель замолчала бы навсегда, а
        единственным следом осталась бы разность счётчиков, которую никто не
        смотрит. Выселение — число (:attr:`polls_expired`), а не тишина.
        """
        stale = [name for name, sent_at in self._in_flight.items() if now - sent_at > self._flight_ttl_sec]
        for name in stale:
            del self._in_flight[name]
            self._polls_expired += 1
        if stale:
            _logger.debug("TelemetryPoller: выселены зависшие опросы %s (TTL %.1fс)", stale, self._flight_ttl_sec)

    def _tick(self) -> None:
        """Один оборот: запросы целям без опроса в полёте, не больше потолка.

        Обход круговой: при упёртом потолке фиксированный порядок оставил бы
        хвост списка целей без опроса навсегда.
        """
        if self._stopped or not self._active:
            return

        now = time.monotonic()
        self._evict_stale_flights(now)

        names = self._targets
        if not names:
            return

        start = self._cursor % len(names)
        started = 0
        for offset in range(len(names)):
            if len(self._in_flight) >= self._max_in_flight:
                break
            name = names[(start + offset) % len(names)]
            if name in self._in_flight:
                continue
            self._in_flight[name] = now
            self._polls_started += 1
            started += 1
            self._submit(partial(self._poll_fn, name), partial(self._on_result, name))
        self._cursor = start + started

    def _on_result(self, name: str, response: Any) -> None:
        """Приём ответа в main thread: разобрать и влить в read-model.

        Ответ по снятой цели отбрасывается: пока запрос летел, вкладка могла
        переключиться, и вливать чужие числа в снимок нельзя — виджет показал
        бы значение процесса, который сейчас не показан.
        """
        self._in_flight.pop(name, None)
        self._polls_completed += 1

        if not (isinstance(response, dict) and response.get("success")):
            self._note_failure(name, response)

        if self._stopped or name not in self._targets:
            return

        levels = self._extract_levels(response)
        if not levels:
            return

        flat: dict[str, Any] = {}
        _flatten_levels(f"processes.{name}", levels, flat)
        if not flat:
            return

        try:
            # Отдельный вход read-model: снимок обновляется, кольцо истории —
            # нет. Опрос отдаёт УРОВЕНЬ; вливаясь через общий push-вход, он
            # вытеснял бы точки push'а из deque фиксированной длины и молча
            # сокращал окно спарклайна (ADR-139).
            self._view_model.ingest_poll_snapshot(flat)
        except RuntimeError as exc:  # C++-объект read-model уже удалён (вкладка закрыта в полёте)
            _logger.debug("TelemetryPoller: влив снимка %s пропущен — приёмник разрушен: %s", name, exc)

    def _note_failure(self, name: str, response: Any) -> None:
        """Учесть неудачный опрос числом и (с троттлом) строкой лога.

        Без этого неудача неотличима от удачи: на экране остаются последние
        хорошие числа, а «протухло» выглядит как «стабильно». Лог троттлится —
        падающая цель при 1 Гц иначе залила бы журнал.
        """
        self._polls_failed += 1
        now = time.monotonic()
        if now - self._last_error_log < 10.0:
            return
        self._last_error_log = now
        if isinstance(response, dict):
            reason = response.get("error") or response.get("reason") or "success=False без причины"
        else:
            reason = f"ответ не dict: {type(response).__name__}"
        _logger.debug(
            "TelemetryPoller: опрос %s неудачен (%s); всего неудач %d из %d",
            name,
            reason,
            self._polls_failed,
            self._polls_completed,
        )

    @staticmethod
    def _extract_levels(response: Any) -> dict | None:
        """Достать ``levels`` из ответа, не веря его форме.

        Разбираются обе формы: транспортный конверт ``{"success", "result":
        {...}}`` (так приходит с ``router.request``) и голый ответ команды.
        ``levels=None`` — легальное «сенсоров нет» (процесс без heartbeat'а),
        а не сбой: возвращаем None и молчим.
        """
        if not isinstance(response, dict) or not response.get("success"):
            return None
        payload = response.get("result")
        if not isinstance(payload, dict):
            payload = response
        levels = payload.get("levels")
        return levels if isinstance(levels, dict) and levels else None
