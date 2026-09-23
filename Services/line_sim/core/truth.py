# -*- coding: utf-8 -*-
"""Правда на проводе (Task 5.2 + 5.1b) — ``TruthLedger``: исход по каждому объекту/заданию.

Чистый класс без IPC, без лока (лок — у владельца-плагина, ``_truth_lock`` в
``Plugins.sim.scene_source.plugin``), без часов (свои часы не заводит — время
берёт из ``job.t``, см. ниже). Владелец плагина зовёт три события ровно в том
порядке, в котором они происходят на ленте: ``on_spawn`` (объект появился),
``on_match`` (исход сопоставления задания — Task 3.5, ``Services.line_sim.core.
matching.match_job``), ``on_despawn`` (объект уехал со сцены).

Контракт лида 5.2 — ``plans/line-sim/phase-5-contract-5.2.md`` §1, дословно.
Контракт лида 5.1b — ``plans/line-sim/phase-5-contract-5.1b.md`` §2: причина
«те же X/Y с новым энкодером» (была ``SimJournal.repeats_frozen_xy``, ушла
оттуда — см. ``Services/robot_comm/server/sim_journal.py``) переехала сюда,
на сторону сцены, потому что только сцена знает реальные координаты объектов;
на проводе робота разные диски у триггера снимаются в одной точке кадра и
ложно принимались за повтор.

Pre:
  - ``on_match`` получает реальный ``MatchResult`` (``Services.line_sim.core.
    matching``) — ``outcome`` один из ``"matched"``/``"dup"``/``"no_object"``.
  - события приходят в порядке появления на ленте: ``on_spawn(X)`` раньше
    любого ``on_match``/``on_despawn``, ссылающегося на ``X``.
  - ``job`` (опционален, §2 контракта 5.1b) — ``JobDone`` задания, приславшего
    этот исход (координаты, ``ecap``, ``t``); без него поведение — ровно как
    в 5.2 (frozen-xy не считается).
Post:
  - исход объекта решается НЕ БОЛЬШЕ одного раза: как только объект попал в
    ``caught`` (matched, под учётом) или ``missed`` (despawn, под учётом), он
    снимается с учёта — повторный ``on_despawn``/попадание в ``matched`` того
    же id больше не меняет счётчики (пойман и пропущен одновременно не
    бывает).
  - ``caught == caught_defect + caught_ok``; ``missed == missed_defect +
    missed_ok`` — всегда, на любом префиксе событий.
  - ``on_belt`` — число объектов под учётом с ещё не решённым исходом; растёт
    на ``on_spawn`` нового id, падает на решённый исход, сверху ограничена
    ``max_active`` спавнера (память ledger не больше памяти спавнера).
  - ``pick_error_mean_mm``/``pick_error_max_mm`` — ``None``, пока не было ни
    одного ``matched`` под учётом; после первого — среднее/максимум по всем
    невязкам ``matched`` под учётом (бегущая сумма/счётчик/максимум, не
    список — плоская память).
  - ``false_alarm_frozen_xy <= false_alarm`` всегда — подмножество, не
    отдельный исход (§2 контракта 5.1b): каждый заход в эту причину также
    увеличивает ``false_alarm``.
  - ``reset()`` зануляет все счётчики (включая ``false_alarm_frozen_xy``) и
    ``pick_error``, забывает память недавних заданий, но НЕ трогает объекты
    под учётом — их исход после сброса решается как обычно.
"""

from __future__ import annotations

import math
from collections import deque

from Services.line_sim.core.matching import JobDone, MatchResult
from Services.line_sim.interfaces import ObjectPassport

#: Дефолты §2 контракта 5.1b — те же значения, что были у SimJournal (dup_radius_mm/
#: dup_window_s), но независимая пара параметров: смысл другой (плоское расстояние
#: без поправки на проезд ленты, а не невязка трекинга).
_DEFAULT_FROZEN_WINDOW_S = 10.0
_DEFAULT_FROZEN_RADIUS_MM = 5.0


class TruthLedger(object):
    """Счётчики поймал/пропустил/дубль/ложная тревога/ошибка захвата — см. докстринг модуля.

    Args:
        frozen_window_s: Окно памяти недавних заданий, сек, по полю ``job.t``
            (§2 контракта 5.1b) — свои часы ledger не заводит.
        frozen_radius_mm: Порог плоского расстояния «та же точка», мм.
    """

    def __init__(
        self,
        *,
        frozen_window_s: float = _DEFAULT_FROZEN_WINDOW_S,
        frozen_radius_mm: float = _DEFAULT_FROZEN_RADIUS_MM,
    ) -> None:
        #: object_id -> признак брака (``passport.defect is not None``) — только объекты
        #: под учётом, с ещё не решённым исходом.
        self._tracked: dict[str, bool] = {}

        self._caught = 0
        self._caught_defect = 0
        self._caught_ok = 0
        self._missed = 0
        self._missed_defect = 0
        self._missed_ok = 0
        self._dup_jobs = 0
        self._false_alarm = 0
        self._untracked_jobs = 0
        self._false_alarm_frozen_xy = 0

        #: Бегущие сумма/счётчик/максимум невязки — плоская память, не список.
        self._pick_error_sum_mm = 0.0
        self._pick_error_count = 0
        self._pick_error_max_mm: float | None = None

        #: Недавние задания (§2 контракта 5.1b) — окно по job.t, чистится на каждом
        #: on_match с job слева (протухшие первыми).
        self._frozen_window_s = frozen_window_s
        self._frozen_radius_mm = frozen_radius_mm
        self._recent_jobs: deque[JobDone] = deque()

    def on_spawn(self, passport: ObjectPassport) -> None:
        """Взять объект под учёт. Идемпотентно — повторный вызов для уже учтённого
        ``object_id`` ничего не делает (§1 контракта)."""
        if passport.object_id in self._tracked:
            return
        self._tracked[passport.object_id] = passport.defect is not None

    def on_match(self, result: MatchResult, job: JobDone | None = None) -> None:
        """Исход сопоставления задания (``match_job``) — §1 контракта 5.2 + §2 контракта 5.1b:

        - ``matched``, объект под учётом -> ``caught`` (+ ``caught_defect``/``caught_ok``),
          невязка в ``pick_error``, объект снимается с учёта (исход решён);
        - ``matched``, объект НЕ под учётом (появился раньше ledger) -> только
          ``untracked_jobs``;
        - ``dup`` -> ``dup_jobs``;
        - ``no_object`` -> ``false_alarm``, и если среди недавних заданий (в пределах
          ``frozen_window_s`` по ``job.t``) есть одно на расстоянии
          ``hypot(Δx, Δy) < frozen_radius_mm`` с ДРУГИМ ``ecap`` -> ``false_alarm_frozen_xy``
          тоже растёт (подмножество ``false_alarm``, §2 контракта 5.1b).

        ``job`` — опционален (обратная совместимость с 5.2): без него частота
        frozen-xy не считается, недавние задания не запоминаются. С ``job`` —
        протухшие (``job.t - entry.t > frozen_window_s``) записи чистятся слева
        ПЕРЕД проверкой исхода, и сам ``job`` кладётся в недавние ПОСЛЕ неё,
        независимо от исхода.
        """
        if job is not None:
            while self._recent_jobs and job.t - self._recent_jobs[0].t > self._frozen_window_s:
                self._recent_jobs.popleft()

        if result.outcome == "matched":
            object_id = result.object_id
            if object_id is not None and object_id in self._tracked:
                is_defect = self._tracked.pop(object_id)
                self._caught += 1
                if is_defect:
                    self._caught_defect += 1
                else:
                    self._caught_ok += 1
                if result.residual_mm is not None:
                    self._pick_error_sum_mm += result.residual_mm
                    self._pick_error_count += 1
                    if self._pick_error_max_mm is None or result.residual_mm > self._pick_error_max_mm:
                        self._pick_error_max_mm = result.residual_mm
            else:
                self._untracked_jobs += 1
        elif result.outcome == "dup":
            self._dup_jobs += 1
        elif result.outcome == "no_object":
            self._false_alarm += 1
            if job is not None and self._is_frozen_xy(job):
                self._false_alarm_frozen_xy += 1

        if job is not None:
            self._recent_jobs.append(job)

    def _is_frozen_xy(self, job: JobDone) -> bool:
        """Среди недавних (уже прорежены окном) — та же точка (X/Y), но ДРУГОЙ
        ``ecap`` (§2 контракта 5.1b). Плоское расстояние, БЕЗ поправки на проезд
        ленты — это НЕ невязка трекинга ``match_job``, а симптом повторного кадра
        или энкодера, замороженного на момент постановки задания в очередь."""
        for entry in self._recent_jobs:
            if entry.ecap == job.ecap:
                continue
            if math.hypot(job.x_mm - entry.x_mm, job.y_mm - entry.y_mm) < self._frozen_radius_mm:
                return True
        return False

    def on_despawn(self, object_id: str) -> None:
        """Объект покинул сцену — §1 контракта: под учётом с нерешённым исходом ->
        ``missed`` (+ ``missed_defect``/``missed_ok``), снимается с учёта. Неизвестный
        или уже решённый (пойманный) id -> no-op."""
        if object_id not in self._tracked:
            return
        is_defect = self._tracked.pop(object_id)
        self._missed += 1
        if is_defect:
            self._missed_defect += 1
        else:
            self._missed_ok += 1

    def counters(self) -> dict[str, int | float | None]:
        """Новый плоский словарь — см. Post докстринга модуля. Мутация возвращённого
        словаря не отражается на ledger (свежий словарь на каждый вызов)."""
        pick_error_mean_mm = self._pick_error_sum_mm / self._pick_error_count if self._pick_error_count > 0 else None
        return {
            "caught": self._caught,
            "caught_defect": self._caught_defect,
            "caught_ok": self._caught_ok,
            "missed": self._missed,
            "missed_defect": self._missed_defect,
            "missed_ok": self._missed_ok,
            "dup_jobs": self._dup_jobs,
            "false_alarm": self._false_alarm,
            "false_alarm_frozen_xy": self._false_alarm_frozen_xy,
            "untracked_jobs": self._untracked_jobs,
            "on_belt": len(self._tracked),
            "pick_error_mean_mm": pick_error_mean_mm,
            "pick_error_max_mm": self._pick_error_max_mm,
        }

    def reset(self) -> None:
        """Зануляет все счётчики и ``pick_error``, забывает недавние задания (§2
        контракта 5.1b) — объекты под учётом ОСТАЮТСЯ (§1 контракта 5.2: их исход
        после сброса решается как обычно)."""
        self._caught = 0
        self._caught_defect = 0
        self._caught_ok = 0
        self._missed = 0
        self._missed_defect = 0
        self._missed_ok = 0
        self._dup_jobs = 0
        self._false_alarm = 0
        self._false_alarm_frozen_xy = 0
        self._untracked_jobs = 0
        self._pick_error_sum_mm = 0.0
        self._pick_error_count = 0
        self._pick_error_max_mm = None
        self._recent_jobs.clear()
