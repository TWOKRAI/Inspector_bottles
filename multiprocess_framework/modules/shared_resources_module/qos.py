"""QoS-профили сообщений по классу груза (Ф7 G.4.a, ADR-SRM-012).

**Единый источник правды** для политики переполнения гнёзд доставки. Три поверхности
переполнения ссылаются на ОДИН профиль вместо трёх раздельных хардкодов:

  1. **Очереди** (`QueueRegistry.remove_old_if_full`) — system=never-drop (reliable),
     data=drop_oldest + счётчик потерь.
  2. **Кадровые кольца SHM** (`FrameShmMiddleware`, G.4.b) — глубина кольца настраивается
     per-camera (дефолт = `history_depth` профиля data). Под copy-out (до G.5): гонка
     reader↔writer при перезаписи слота на wrap ловится **seqlock**'ом → drop, виден в
     `frame_torn_reads` (G.3); глубже кольцо → реже. Occupancy-детект «writer перезаписал
     НЕпрочитанный слот» (громкий drop-на-источнике по исчерпанию пула) требует владения
     слотом (refcount/release) → **G.5**, здесь его НЕТ.
  3. **Наблюдаемость** (`channel_routing_module/observability/BoundedChannel`) —
     drop_oldest + `dropped` (уже так исторически; профиль документирует и унифицирует
     семантику).

**Сквозной инвариант Ф7 (правило исполнения п.2):** `system` НИКОГДА не дропается молча
(reliable → backpressure/явная ошибка отправителю); `data`/наблюдаемость — `drop_oldest`
+ монотонный счётчик потерь. «Терять можно, молчать — нельзя» (урок Ф3.3).

Ключи `QOS_PROFILES` СОВПАДАЮТ с именами kind (`resolve_channel_kind`: system/data/state)
и с `queue_type` (`_select_queue_type`: system/data) — один словарь обслуживает обе
поверхности. Профиль — чистые данные (frozen dataclass, pickle-safe, без зависимостей),
поэтому живёт в низком `shared_resources_module` (и очередь тут же, и router дотянется по
существующему ребру router→shared_resources).

Профили — дефолты движка; приложение может переопределить глубину data per-camera в рецепте
(G.4.b, ключ `frame_ring_depth`). Формат структуры сразу совместим с DDS/iceoryx2 QoS
(reliability/history/deadline) — миграция транспорта потом будет заменой бэкенда под тем же
контрактом (frame-pool-idea, «Аналоги в индустрии»).
"""

from __future__ import annotations

from dataclasses import dataclass

# --- reliability ---
RELIABLE = "reliable"
BEST_EFFORT = "best_effort"

# --- drop_policy ---
DROP_NEVER = "never"
DROP_OLDEST = "drop_oldest"
DROP_NEWEST = "drop_newest"

_RELIABILITIES = (RELIABLE, BEST_EFFORT)
_DROP_POLICIES = (DROP_NEVER, DROP_OLDEST, DROP_NEWEST)


@dataclass(frozen=True)
class QoSProfile:
    """Профиль качества обслуживания класса груза.

    Args:
        reliability:   ``reliable`` (никогда не терять молча) | ``best_effort`` (можно
                       ронять с учётом потерь).
        history_depth: keep_last N — глубина буфера/кольца (0 = неограниченно/дефолт гнезда).
        drop_policy:   ``never`` | ``drop_oldest`` | ``drop_newest`` — что делать при
                       переполнении.
        deadline_ms:   мягкая подсказка дедлайна доставки, мс (0 = без дедлайна). Пока
                       информационное поле (для будущего deadline-миссед-счётчика/трейса).
    """

    reliability: str
    history_depth: int
    drop_policy: str
    deadline_ms: int

    def __post_init__(self) -> None:
        if self.reliability not in _RELIABILITIES:
            raise ValueError(f"reliability должен быть из {_RELIABILITIES}, получено {self.reliability!r}")
        if self.drop_policy not in _DROP_POLICIES:
            raise ValueError(f"drop_policy должен быть из {_DROP_POLICIES}, получено {self.drop_policy!r}")
        if self.history_depth < 0:
            raise ValueError(f"history_depth должен быть >= 0, получено {self.history_depth}")
        if self.deadline_ms < 0:
            raise ValueError(f"deadline_ms должен быть >= 0, получено {self.deadline_ms}")
        # Инвариант: reliable ⇒ never-drop; never-drop ⇒ reliable (иначе противоречие).
        if (self.reliability == RELIABLE) != (self.drop_policy == DROP_NEVER):
            raise ValueError(
                f"противоречие профиля: reliability={self.reliability!r} vs drop_policy={self.drop_policy!r} "
                "(reliable ⟺ never)"
            )

    @property
    def never_drop(self) -> bool:
        """True — груз нельзя ронять молча (system/command). Единственный источник этого
        решения для всех трёх поверхностей переполнения."""
        return self.drop_policy == DROP_NEVER


# --- Реестр: класс груза (kind == queue_type) → профиль -----------------------------

# system/command — control-plane: process.stop/heartbeat терять нельзя.
_SYSTEM = QoSProfile(RELIABLE, history_depth=0, drop_policy=DROP_NEVER, deadline_ms=0)
# data — кадры/данные: старый кадр конвейеру бесполезен → drop_oldest, живую камеру не
# тормозим. history_depth=4 — дефолт глубины кольца (несколько кадров на джиттер, G.4.b);
# deadline 33 мс ≈ бюджет 30 FPS.
_DATA = QoSProfile(BEST_EFFORT, history_depth=4, drop_policy=DROP_OLDEST, deadline_ms=33)
# state — реактивное дерево: важен ПОСЛЕДНИЙ снимок (coalesce), keep_last=1.
_STATE = QoSProfile(BEST_EFFORT, history_depth=1, drop_policy=DROP_OLDEST, deadline_ms=0)
# observability/log — телеметрия: буфер 1024 (капасити BoundedChannel), drop_oldest.
_OBSERVABILITY = QoSProfile(BEST_EFFORT, history_depth=1024, drop_policy=DROP_OLDEST, deadline_ms=0)

QOS_PROFILES: dict[str, QoSProfile] = {
    "system": _SYSTEM,
    "command": _SYSTEM,
    "data": _DATA,
    "state": _STATE,
    "observability": _OBSERVABILITY,
    "log": _OBSERVABILITY,
}

# Неизвестный класс груза → data-политика (best_effort, drop_oldest): безопасный дефолт,
# который НЕ роняет молча system (system всегда в реестре), но и не блокирует неизвестное.
_DEFAULT_PROFILE = _DATA


def qos_for(kind_or_queue_type: str) -> QoSProfile:
    """Профиль по классу груза (kind ``resolve_channel_kind`` ИЛИ ``queue_type`` — общий
    словарь). Неизвестный ключ → data-дефолт (best_effort/drop_oldest)."""
    return QOS_PROFILES.get(kind_or_queue_type, _DEFAULT_PROFILE)
