"""GC-дисциплина процесса (Ф7 G.9(a)).

Проблема (перф-ревью 2026-07-12 п.2): CPython запускает сборку мусора «когда захочет» —
по порогам поколений. На hot-path кадров это даёт непредсказуемые паузы = выбросы p99.

Дисциплина (за флагами, дефолт off = штатный GC бит-в-бит):

1. **``gc.freeze()`` после старта воркеров** (``FW_GC_FREEZE``). Все долгоживущие
   startup-объекты (менеджеры, плагины, роутер, кэши) уже созданы → переносим их в
   permanent-поколение: сборщик их больше НЕ сканирует на каждом цикле. Меньше объектов в
   обходе → короче каждая пауза GC. Безопасно и почти без риска — cadence сборки не
   меняется, только объём обхода.

2. **Сборка по расписанию** (``collect_scheduled``, отдельный флаг ``FW_GC_SCHEDULED``) —
   ``gc.disable()`` автоматики + явный ``gc.collect()`` по дедлайну в паузах воркера, чтобы
   пауза случалась в ИЗВЕСТНЫЙ момент (idle), а не посреди кадра. **Measurement-gated:**
   отключать автоматику рискованно (рост RSS при протечке ссылок), поэтому включаем только
   ПОСЛЕ замера harness'ом G.9(b), доказавшего снижение p99-выбросов. По умолчанию — off.

Pydantic остаётся на конфигах/границах (правила 1/5); per-frame путь уже без Pydantic-
пересборки (G.5 ``FW_DATA_PLANE_DICTS``) — эта дисциплина ортогональна и про сам GC.
"""

from __future__ import annotations

import gc
from typing import Callable, Optional


class GcDiscipline:
    """GC-дисциплина одного процесса. Держит состояние (заморожен ли, дедлайн сборки)."""

    def __init__(self, log: Optional[Callable[[str], None]] = None) -> None:
        self._log = log or (lambda _m: None)
        self._frozen = False
        self._scheduled = False
        self._next_collect_at: float = 0.0

    @staticmethod
    def _flag(name: str) -> bool:
        from ...config_module.tools.env import env_flag

        return env_flag(name)

    def freeze_after_startup(self) -> bool:
        """``gc.freeze()`` после старта воркеров (``FW_GC_FREEZE``). Идемпотентно.

        Сначала ``gc.collect()`` — собрать мусор старта, чтобы НЕ заморозить его в
        permanent (иначе он никогда не соберётся). Затем ``gc.freeze()`` — живые объекты
        в permanent-поколение. Возвращает True, если заморозка применена.
        """
        if self._frozen:
            return False
        if not self._flag("FW_GC_FREEZE"):
            # Ф7 ревью фазы G: FW_GC_SCHEDULED без FW_GC_FREEZE — расписание НЕ
            # применяется (сборка по расписанию имеет смысл только после заморозки
            # стартовых объектов). Раньше это был ТИХИЙ no-op — оператор включал
            # расписание и не получал ничего без единого лога («терять можно,
            # молчать нельзя», ADR-SRM-012).
            if self._flag("FW_GC_SCHEDULED"):
                self._log(
                    "GcDiscipline: FW_GC_SCHEDULED запрошен БЕЗ FW_GC_FREEZE — "
                    "расписание НЕ применено (авто-GC остаётся); включите оба флага"
                )
            return False
        gc.collect()
        gc.freeze()
        self._frozen = True
        permanent = gc.get_freeze_count()
        self._log(f"GcDiscipline: gc.freeze применён после старта (permanent-объектов={permanent})")
        # FW_GC_SCHEDULED: перевести сборку в ручной режим (сборка только в паузах воркера).
        if self._flag("FW_GC_SCHEDULED"):
            gc.disable()
            self._scheduled = True
            self._log("GcDiscipline: авто-GC отключён — сборка по расписанию в паузах (FW_GC_SCHEDULED)")
        return True

    def collect_scheduled(self, now: float, *, interval_s: float = 2.0) -> bool:
        """Явная сборка по дедлайну — зовётся из ПАУЗЫ воркера (idle), не на hot-path.

        No-op, если расписание не включено (``FW_GC_SCHEDULED`` off) — тогда работает
        штатный авто-GC. При включённом: собирает не чаще, чем раз в ``interval_s``, и
        только когда воркер в паузе (вызывающий гарантирует). ``now`` — монотонное время
        (инжектируется вызывающим; тестируемо). Возвращает True, если собрал.
        """
        if not self._scheduled:
            return False
        if now < self._next_collect_at:
            return False
        self._next_collect_at = now + max(0.1, interval_s)
        gc.collect()
        return True


__all__ = ["GcDiscipline"]
