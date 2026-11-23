"""ObjectSpawner — непрерывный поток объектов на ленте: спавн по интервалу ИЛИ по шагу
ленты в мм, деспавн за границей сцены, пауза, форс-хук брака.

Часы и очередь спавна принадлежат спавнеру целиком (LS-008): `tick()` — единственная
точка входа, вызывающий передаёт только "что сейчас" (`now_encoder`, `now_wall_s`, `rng`).
Единственный producer — поток-продюсер кадров (Task 3.4); сам спавнер по-прежнему однопоточный,
лок ему не нужен (если появится второй вызывающий — тогда лок). Лок (`threading.Lock`) есть только
у `DiscSequence` (Task R1, подача дисков по списку) — это единственное состояние, общее с потоком
команд: команда плагина меняет список, воркер `tick()` берёт голову и снимает её.

Два режима отсчёта следующего спавна (Task 3.3a, LS-010) — ровно один задан в конструкторе:
`interval_s` (по настенному времени, исходный режим Task 3.3) или `spacing_mm` (по пути
ленты — тот же `encoder_to_offset_mm`, которым уже пользуется деспавн). Режим `interval_s`
на стоящей ленте продолжает спавнить объекты в одну точку (известный дефект, воспроизведён
на живом стенде 2026-09-23 — три объекта с одинаковым `spawn_encoder`); `spacing_mm`
привязан к пути ленты, поэтому на стоящей ленте новые объекты не появляются сами собой.
"""

from __future__ import annotations

import math
import threading
from dataclasses import replace
from typing import NamedTuple

import numpy as np

from Services.line_sim.core.belt import encoder_to_offset_mm
from Services.line_sim.core.factory import ObjectFactory
from Services.line_sim.core.layered_object import LayeredObject
from Services.line_sim.interfaces import ObjectPassport

#: Минимум настенного времени между двумя спавнами при подаче списка (решение 1.0: `state` word_layout
#: не чаще раза в секунду, `design.md` §2.9). Константа, не ключ конфига; время — `time.monotonic()` воркера.
SEQUENCE_MIN_INTERVAL_S = 1.0

#: Максимальная длина списка дисков: `max_active=200` спавнера по умолчанию — список длиннее на стоящей
#: ленте упёрся бы в потолок активных объектов.
SEQUENCE_MAX_LEN = 200


class SequenceBusy(Exception):
    """`DiscSequence.load()` без `replace` при неисчерпанном списке; `remaining` — сколько дисков осталось."""

    def __init__(self, remaining: int) -> None:
        super().__init__(f"подаётся список, осталось {remaining}")
        self.remaining = remaining


class SequenceHead(NamedTuple):
    """Снимок головы списка (`DiscSequence.next()`): `mode` `"random"` | `"list"`, `generation` — номер
    поколения списка на момент снимка (меняется при `load`/`set_random`), `pos`/`letter`/`angle_deg` —
    голова. У `"random"` и у исчерпанного/пустого `"list"` последние три — `None`."""

    mode: str
    generation: int
    pos: int | None
    letter: str | None
    angle_deg: float | None


class DiscSequence:
    """Список дисков `[(буква, угол), ...]` — ЕДИНСТВЕННОЕ состояние спавнера, которое трогают два потока:
    команда плагина (`load`/`set_random`/`snapshot`) и воркер кадров (`next`/`pop`/`skip`). Всё состояние —
    под одним `self._lock`, каждый метод — ОДНА критическая секция.

    Воркер зовёт `next()` один раз за `tick()` и снимает голову `pop(generation)`/`skip(generation)` с
    поколением из СНИМКА: если команда за это время сменила список (`generation` изменилось), `pop`/`skip`
    ничего не меняют и возвращают `False` — диск чужого списка не засчитывается новому.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mode = "random"
        self._generation = 0
        self._items: list[tuple[str, float]] = []
        self._pos = 0
        self._fed = 0
        self._skipped = 0

    def _remaining_locked(self) -> int:
        """Сколько дисков осталось подать. Зовётся ТОЛЬКО под `self._lock`."""
        return len(self._items) - self._pos

    def next(self) -> SequenceHead:
        """Снимок головы одним захватом лока (воркер зовёт один раз за `tick()`)."""
        with self._lock:
            if self._mode != "list" or self._remaining_locked() == 0:
                return SequenceHead(self._mode, self._generation, None, None, None)
            letter, angle = self._items[self._pos]
            return SequenceHead(self._mode, self._generation, self._pos, letter, angle)

    def pop(self, generation: int) -> bool:
        """Голова подана: сдвинуть позицию, `fed += 1`. Чужое поколение, не режим списка или пустой
        остаток — `False`, ничего не меняется."""
        with self._lock:
            if generation != self._generation or self._mode != "list" or self._remaining_locked() == 0:
                return False
            self._pos += 1
            self._fed += 1
            return True

    def skip(self, generation: int) -> bool:
        """Голова пропущена (буквы нет в каталоге): как `pop`, но `skipped += 1`."""
        with self._lock:
            if generation != self._generation or self._mode != "list" or self._remaining_locked() == 0:
                return False
            self._pos += 1
            self._skipped += 1
            return True

    def load(self, discs: list[tuple[str, float]], *, replace: bool = False) -> int:
        """Загрузить список. Идёт список с остатком и `replace` ложно — `SequenceBusy(remaining)`, ничего
        не меняется. Иначе заменяет; возвращает число выброшенных дисков старого списка. Проверка и
        замена — внутри ОДНОГО `with self._lock` (две команды без `replace` не могут обе стать `ok`)."""
        with self._lock:
            remaining = self._remaining_locked()
            if self._mode == "list" and remaining > 0 and not replace:
                raise SequenceBusy(remaining)
            dropped = remaining if self._mode == "list" else 0
            self._items = [(item[0], item[1]) for item in discs]
            self._pos = self._fed = self._skipped = 0
            self._mode = "list"
            self._generation += 1
            return dropped

    def set_random(self) -> int:
        """Выйти из режима списка: остаток выброшен (его число — результат), спавн снова случайный."""
        with self._lock:
            dropped = self._remaining_locked()
            self._mode = "random"
            self._items = []
            self._pos = self._fed = self._skipped = 0
            self._generation += 1
            return dropped

    def snapshot(self) -> dict:
        """`{"mode", "total", "fed", "skipped", "remaining"}` — JSON-типы, для `scene.status`."""
        with self._lock:
            return {
                "mode": self._mode,
                "total": len(self._items),
                "fed": self._fed,
                "skipped": self._skipped,
                "remaining": self._remaining_locked(),
            }


def validate_flow(
    interval_s: tuple[float, float] | None,
    spacing_mm: tuple[float, float] | None,
) -> None:
    """Проверка режима отсчёта следующего спавна — ровно один из двух задан, каждый
    диапазон `(lo, hi)` с `0 < lo <= hi`. Вынесена из `__init__` (Task 6.1, контракт
    `plans/line-sim/phase-6-contract-6.1.md` шаг 1), чтобы `ObjectSpawner.set_flow()`
    (смена режима на живом спавнере) звала ТУ ЖЕ проверку, а не свою копию."""
    if (interval_s is None) == (spacing_mm is None):
        raise ValueError(
            "ровно один из interval_s/spacing_mm должен быть задан — "
            f"interval_s={interval_s!r}, spacing_mm={spacing_mm!r}"
        )
    if interval_s is not None:
        lo, hi = interval_s
        if lo > hi:
            raise ValueError(f"interval_s: lo={lo} > hi={hi} — нижняя граница интервала больше верхней")
        if lo <= 0:
            raise ValueError(f"interval_s: lo={lo} <= 0 — интервал спавна должен быть положительным")
    else:
        lo, hi = spacing_mm  # type: ignore[misc]  # spacing_mm гарантированно не None (проверка выше)
        if lo > hi:
            raise ValueError(f"spacing_mm: lo={lo} > hi={hi} — нижняя граница шага больше верхней")
        if lo <= 0:
            raise ValueError(f"spacing_mm: lo={lo} <= 0 — шаг спавна должен быть положительным")


def validate_lateral_offset_px(value: object) -> tuple[float, float]:
    """Проверка диапазона модуля поперечного смещения `lateral_offset_px = (lo, hi)` (пиксели
    кадра): пара конечных чисел (bool не число), `0 <= lo <= hi`. Возвращает `(float, float)`.
    Текст `ValueError` называет ключ и полученное значение. Общая для `ObjectSpawner.__init__`
    и плагина `scene_source` — одна проверка, не две копии."""
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)
    ):
        raise ValueError(f"lateral_offset_px: ожидалась пара конечных чисел [lo, hi], получено {value!r}")
    lo, hi = float(value[0]), float(value[1])
    if lo < 0:
        raise ValueError(
            f"lateral_offset_px: lo={lo} < 0 — модуль смещения не может быть отрицательным (получено {value!r})"
        )
    if lo > hi:
        raise ValueError(f"lateral_offset_px: lo={lo} > hi={hi} — нижняя граница больше верхней (получено {value!r})")
    return lo, hi


class ObjectSpawner:
    """Спавнит объекты на ленте по интервалу, снимает уехавшие за `scene_length_mm`.

    Пауза (`set_paused(True)`) останавливает только НОВЫЙ спавн — деспавн работает как
    обычно на каждом `tick()` (существующие объекты продолжают двигаться и уезжать со
    сцены, останов ленты — отдельный контрол, см. `VfdDriver`).

    Форс-хук «выпусти брак сейчас» (`force_defect_next()`, делегат `ObjectFactory.
    force_defect_next()`, LS-007) на паузе объект НЕ создаёт — только помечает СЛЕДУЮЩИЙ
    реальный спавн (после снятия паузы) как дефектный: оператор не получает объект на
    остановленном потоке, а нажатие не теряется, потому что фабрика гасит флаг лишь
    после того, как объект успешно собран (LS-006/LS-007).

    Потолок `max_active` (не энкодер!) ограничивает память при остановленной ленте:
    деспавн зависит ТОЛЬКО от энкодера (`encoder_to_offset_mm`), поэтому у застывшего
    энкодера нет своего выхода — без потолка поток спавнил бы объекты на одном месте
    неограниченно (ревью 2026-09-22: 600 объектов / 259 МБ кэша рендера за 5
    симулированных минут без потолка). Остановить сам ПОТОК при остановке ленты —
    ответственность вызывающего (Task 3.4 / Ф6), спавнер этого не делает сам.

    Pre: ровно один из `interval_s` / `spacing_mm` задан. `interval_s = (lo, hi)` с
    `0 < lo <= hi`; `spacing_mm = (lo, hi)` с `0 < lo <= hi`; `scene_length_mm > 0`;
    `max_active > 0`; `lateral_offset_px = (lo, hi)` с `0 <= lo <= hi`.

    Поперечное смещение (`lateral_offset_px`, пиксели кадра): каждому НОВОМУ объекту после
    `factory.make()` (поэтому розыгрыши фабрики не сдвигаются) проставляется
    `passport.lateral_px = ±rng.uniform(lo, hi)` (сначала модуль, затем знак ±1 равновероятно).
    Диапазон `(0, 0)` (дефолт) rng не трогает вовсе — поток случайных чисел и кадры байт в байт
    прежние, `lateral_px == 0.0` (не `-0.0`). Живёт в спавнере, а не в фабрике: переживает
    `set_factory()` (`preset.commit`).
    Post: `tick()` создаёт не больше одного объекта за вызов; в режиме `interval_s`
    пропущенные интервалы не догоняются — следующий срок считается от `now_wall_s`
    текущего тика, не от просроченного срока. В режиме `spacing_mm` первый объект
    создаётся на первом же `tick()` (ждать нечего — лента уже едет), следующий шаг
    выбирается заново при каждом спавне и хранится до следующего. `remove()` (Task
    3.5, job↔object matching) снимает объект из активных, но НЕ трогает счёт шага
    спавна (`_last_spawn_encoder`/`_next_spacing_mm`), срок таймера (`_deadline`) и
    нумерацию (`_next_id_n`) — снятие чужеродно расписанию будущего спавна.
    """

    def __init__(
        self,
        factory: ObjectFactory,
        *,
        interval_s: tuple[float, float] | None = None,
        spacing_mm: tuple[float, float] | None = None,
        scene_length_mm: float,
        max_active: int = 200,
        lateral_offset_px: tuple[float, float] = (0.0, 0.0),
        sequence: DiscSequence | None = None,
    ) -> None:
        validate_flow(interval_s, spacing_mm)
        self._lateral_offset_px = validate_lateral_offset_px(lateral_offset_px)
        if scene_length_mm <= 0:
            raise ValueError(f"scene_length_mm={scene_length_mm} <= 0 — длина сцены должна быть положительной")
        if max_active <= 0:
            raise ValueError(f"max_active={max_active} <= 0 — потолок активных объектов должен быть положительным")

        self._factory = factory
        self._interval_s = interval_s
        self._spacing_mm = spacing_mm
        self._scene_length_mm = scene_length_mm
        self._max_active = max_active
        self._active: list[LayeredObject] = []
        self._deadline: float | None = None
        self._last_spawn_encoder: float | None = None
        self._next_spacing_mm: float | None = None
        self._paused = False
        self._next_id_n = 1
        self._sequence = sequence
        # Настенное время последнего спавна (любого — и случайного): первый диск списка после случайного
        # тоже не раньше `SEQUENCE_MIN_INTERVAL_S`. Пишет только воркер.
        self._last_spawn_wall_s: float | None = None

    def tick(self, *, now_encoder: float, now_wall_s: float, rng: np.random.Generator) -> None:
        """Один шаг часов спавнера: сперва деспавн (на КАЖДОМ тике), затем — спавн по
        режиму, заданному в конструкторе (`interval_s` или `spacing_mm`, Task 3.3a).

        Спавн пропускается (порог — срок или пройденный путь — НЕ трогается, сработает,
        как только появится место), если `len(active_objects()) >= max_active` (fix F2,
        ревью 2026-09-22 — заменяет отвергнутую энкодерную версию: та ломала законный
        паттерн «энкодер держат константой, чтобы изолировать таймер», см. LS-008).
        Потолок ограничивает память, но НЕ трогает существующие объекты и не бросает
        исключение.

        Деспавн держит НИЖНЮЮ границу симметрично верхней (review Task 3.3a, находка 1,
        LS-010-ревью): объект снимается и когда `traveled_mm > scene_length_mm` (уехал
        вперёд — как раньше), И когда `traveled_mm < -scene_length_mm` (разрыв счётчика —
        энкодер обнулился/скакнул назад больше чем на длину сцены, например рестарт
        робота: 106016 -> 0 при `scene_length_mm=1200` даёт около -15319 мм). Обычный
        реверс/джог ленты (`-scene_length_mm <= traveled_mm < 0`) объект НЕ снимает — лента
        умеет идти назад (чекбокс на пульте), и это законное движение, не разрыв.
        """
        self._active = [
            obj
            for obj in self._active
            if -self._scene_length_mm
            <= encoder_to_offset_mm(now_encoder, obj.passport.spawn_encoder)
            <= self._scene_length_mm
        ]

        # Голова списка — ОДИН снимок за тик (`next()` под одним захватом лока): отдельных `peek()` и
        # чтения режима нет, иначе режим и голова могли бы относиться к разным спискам (TOCTOU).
        head = self._sequence.next() if self._sequence is not None else None
        if head is not None and head.mode == "list":
            self._tick_list(head, now_encoder=now_encoder, now_wall_s=now_wall_s, rng=rng)
        elif self._interval_s is not None:
            self._tick_interval(now_encoder=now_encoder, now_wall_s=now_wall_s, rng=rng)
        else:
            self._tick_spacing(now_encoder=now_encoder, now_wall_s=now_wall_s, rng=rng)

    def _tick_interval(self, *, now_encoder: float, now_wall_s: float, rng: np.random.Generator) -> None:
        """Режим `interval_s` (Task 3.3, без изменений в Task 3.3a).

        Первый `tick()` только взводит срок (`now_wall_s + rng.uniform(*interval_s)`) и
        не создаёт объект.

        Срок сдвигается НА ОКНЕ (`now_wall_s >= срок`), НЕЗАВИСИМО от того, успел ли
        `factory.make()` (ревью, fix F1) — так исключение из постоянно падающей фабрики
        прилетает раз в интервал, а не на каждом кадре продюсера (репродукция ревью: 286
        исключений за 300 тиков на 30 fps до фикса). Счётчик `object_id` — ТОЛЬКО после
        успеха: неудачная попытка не тратит id, но и не ретраится в том же окне —
        транзитный сбой теряет ровно один объект этого окна, не больше (форс-брак не
        теряется — фабрика гасит флаг только после успешной сборки, LS-007).
        """
        if self._deadline is None:
            self._deadline = now_wall_s + float(rng.uniform(*self._interval_s))
            return

        if self._paused:
            return

        if now_wall_s >= self._deadline:
            if len(self._active) >= self._max_active:
                return
            object_id = f"obj-{self._next_id_n}"
            self._deadline = now_wall_s + float(rng.uniform(*self._interval_s))
            obj = self._make(object_id, now_encoder, rng)
            self._active.append(obj)
            self._last_spawn_wall_s = now_wall_s
            self._next_id_n += 1

    def _make(
        self,
        object_id: str,
        now_encoder: float,
        rng: np.random.Generator,
        *,
        class_index: int | None = None,
        angle_deg: float | None = None,
    ) -> LayeredObject:
        """`factory.make()` + поперечное смещение паспорта (см. докстринг класса). Розыгрыш —
        ПОСЛЕ сборки объекта: исключение фабрики не тратит rng, а розыгрыши фабрики идут
        в прежнем порядке. `class_index`/`angle_deg` (диск списка, Task R1) уходят в фабрику только
        когда заданы — случайный путь зовёт `make` ровно как раньше (фабрики-заглушки тестов)."""
        make_kwargs: dict[str, object] = {}
        if class_index is not None:
            make_kwargs["class_index"] = class_index
        if angle_deg is not None:
            make_kwargs["angle_deg"] = angle_deg
        obj = self._factory.make(object_id, spawn_encoder=now_encoder, rng=rng, **make_kwargs)
        lo, hi = self._lateral_offset_px
        if hi > 0.0:
            magnitude = float(rng.uniform(lo, hi))
            sign = 1.0 if rng.random() < 0.5 else -1.0
            # `+ 0.0` гасит `-0.0` (магнитуда 0 со знаком минус): -0.0 + 0.0 == +0.0.
            obj.passport = replace(obj.passport, lateral_px=sign * magnitude + 0.0)
        return obj

    def _tick_spacing(self, *, now_encoder: float, now_wall_s: float, rng: np.random.Generator) -> None:
        """Режим `spacing_mm` (Task 3.3a): следующий объект появляется, когда лента
        проехала выбранный шаг — считает та же `encoder_to_offset_mm`, которой уже
        пользуется деспавн (первая строка `tick()`), не отдельная формула.

        Первый объект создаётся на первом же `tick()` без ожидания (`_last_spawn_encoder
        is None`) — лента уже едет, ждать нечего. На стоящей ленте (`now_encoder` не
        растёт) `encoder_to_offset_mm` даёт 0, порог не достигается — новые объекты не
        появляются сами собой; это и есть отличие от `interval_s`, ради которого задача
        существует (репродукция дефекта на живом стенде — куча объектов на одном
        `spawn_encoder`, план Task 3.3a).

        `_last_spawn_encoder`/`_next_spacing_mm` обновляются ДО вызова `factory.make()` —
        тот же приём, что fix F1 у `_tick_interval`: постоянно падающая фабрика роняет
        исключение раз в ШАГ (не на каждом тике, пока лента едет), а не на каждом тике.
        Потолок `max_active` проверяется раньше и порог не трогает (симметрично F2).

        Разрыв счётчика (review Task 3.3a, находка 1, LS-010-ревью):
        `traveled_mm < -scene_length_mm` относительно `_last_spawn_encoder` — счётчик
        потерял опору (обнуление/скачок больше длины сцены назад), а не обычный реверс.
        В этом случае точка отсчёта переустанавливается на `now_encoder` СРАЗУ, независимо
        от паузы (иначе следующий реальный спавн ждал бы весь пройденный до разрыва путь
        заново — замер ревью: сцена стояла пустой около 161 с). Обычный реверс/джог
        (`-scene_length_mm <= traveled_mm < 0`) НИЧЕГО не переустанавливает — просто не
        достигает порога `_next_spacing_mm` (тот всегда положителен), новый спавн наступает,
        когда лента снова пройдёт вперёд.
        """
        if self._last_spawn_encoder is not None:
            traveled_mm = encoder_to_offset_mm(now_encoder, self._last_spawn_encoder)
            if traveled_mm < -self._scene_length_mm:
                self._last_spawn_encoder = now_encoder
                return

        if self._paused:
            return

        if self._last_spawn_encoder is not None:
            # Порог сброшен `set_flow()` (Task 6.1) при уже пройденном пути — взвести его
            # ЗДЕСЬ, где есть `rng`, от НОВОГО диапазона. Без этой ветки сравнение ниже
            # ловило `None` и роняло тик `TypeError`, который `produce()` глушит своим
            # `except Exception` — лента ехала, объекты не появлялись, в логе только
            # предупреждение «сбой фабрики» (инъекция лида 2026-09-28, воспроизведение в
            # `Plugins/sim/scene_source/tests/test_lead_6_1.py`).
            if self._next_spacing_mm is None:
                self._next_spacing_mm = float(rng.uniform(*self._spacing_mm))
            traveled_mm = encoder_to_offset_mm(now_encoder, self._last_spawn_encoder)
            if traveled_mm < self._next_spacing_mm:
                return

        if len(self._active) >= self._max_active:
            return

        object_id = f"obj-{self._next_id_n}"
        self._last_spawn_encoder = now_encoder
        self._next_spacing_mm = float(rng.uniform(*self._spacing_mm))
        obj = self._make(object_id, now_encoder, rng)
        self._active.append(obj)
        self._last_spawn_wall_s = now_wall_s
        self._next_id_n += 1

    def _tick_list(
        self, head: SequenceHead, *, now_encoder: float, now_wall_s: float, rng: np.random.Generator
    ) -> None:
        """Режим списка (Task R1): подать диск `head` (буква = класс каталога фабрики, угол — из списка).

        Пороги потока (срок `interval_s` / шаг `spacing_mm`) те же, что у случайного режима, плюс
        `SEQUENCE_MIN_INTERVAL_S` между любыми двумя спавнами по настенному времени. Пока что-то из этого
        не выполнено — `return`, порог НЕ тратится: список, пришедший позже, подаёт первый диск сразу,
        как только прошла 1 с и порог потока достигнут. Исчерпанный список (`letter is None`) спавн
        останавливает до следующей команды (возврат к случайным сам по себе — нет).

        Порядок: порог сдвигается ДО `make` (как fix F1 у случайных режимов — падающая фабрика бросает
        раз в порог, не на каждом тике); голова снимается `pop(generation)` только ПОСЛЕ успешного
        `make`, поэтому транзитный сбой фабрики диск не теряет. Если `pop` вернул `False` (команда сменила
        список, пока шёл `make`), собранный объект ВЫБРАСЫВАЕТСЯ: не в `active`, `_last_spawn_wall_s` и
        `_next_id_n` не меняются, а сброшенный фабрикой форс брака взводится заново — нажатие оператора
        достаётся следующему диску.
        """
        if head.letter is None:
            return

        if self._interval_s is not None:
            if self._deadline is None:
                self._deadline = now_wall_s + float(rng.uniform(*self._interval_s))
                return
        elif self._last_spawn_encoder is not None:
            traveled_mm = encoder_to_offset_mm(now_encoder, self._last_spawn_encoder)
            if traveled_mm < -self._scene_length_mm:  # разрыв счётчика — как в `_tick_spacing`, до паузы
                self._last_spawn_encoder = now_encoder
                return

        if self._paused or len(self._active) >= self._max_active:
            return
        if self._last_spawn_wall_s is not None and now_wall_s - self._last_spawn_wall_s < SEQUENCE_MIN_INTERVAL_S:
            return

        if self._interval_s is not None:
            if now_wall_s < self._deadline:  # type: ignore[operator]  # срок взведён выше
                return
        elif self._last_spawn_encoder is not None:
            if self._next_spacing_mm is None:  # порог сброшен `set_flow()` — см. `_tick_spacing`
                self._next_spacing_mm = float(rng.uniform(*self._spacing_mm))  # type: ignore[misc]
            if encoder_to_offset_mm(now_encoder, self._last_spawn_encoder) < self._next_spacing_mm:
                return

        # Порог сдвигается ДО make (F1).
        if self._interval_s is not None:
            self._deadline = now_wall_s + float(rng.uniform(*self._interval_s))
        else:
            self._last_spawn_encoder = now_encoder
            self._next_spacing_mm = float(rng.uniform(*self._spacing_mm))  # type: ignore[misc]

        assert self._sequence is not None  # режим списка бывает только при заданной последовательности
        class_names = self._factory.class_names
        if head.letter not in class_names:
            if self._sequence.skip(head.generation):
                raise ValueError("список дисков: буквы нет в каталоге фабрики")
            return  # список уже чужой (команда пришла после next()): пропускать нечего, строки в логе не нужно

        object_id = f"obj-{self._next_id_n}"
        forced_before = self._factory.force_defect_pending
        obj = self._make(
            object_id, now_encoder, rng, class_index=class_names.index(head.letter), angle_deg=head.angle_deg
        )
        if not self._sequence.pop(head.generation):
            if forced_before:
                self._factory.force_defect_next()
            return
        self._active.append(obj)
        self._last_spawn_wall_s = now_wall_s
        self._next_id_n += 1

    def active_objects(self) -> list[LayeredObject]:
        """Копия списка активных объектов — мутация результата не трогает спавнер."""
        return list(self._active)

    def remove(self, object_id: str) -> ObjectPassport | None:
        """Снять объект из активных по `object_id` (Task 3.5, job↔object matching) —
        плагин сцены вызывает это, когда `match_job` находит совпадение с заданием
        робота. Неизвестный `object_id` -> `None`, без исключения (кривой/устаревший
        id — обычный случай гонки job/деспавна, не повод падать).

        Post: см. Post докстринга класса — расписание будущего спавна не меняется.
        """
        for i, obj in enumerate(self._active):
            if obj.passport.object_id == object_id:
                return self._active.pop(i).passport
        return None

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    @property
    def paused(self) -> bool:
        """Read-only — ручка «пауза» стенда (`scene.status`, Task 6.1) не лезет в приватное поле."""
        return self._paused

    @property
    def flow(self) -> dict:
        """Read-only снимок активного режима отсчёта спавна — `{"mode": "interval_s"|
        "spacing_mm", "lo": float, "hi": float}` (Task 6.1, `scene.status`)."""
        if self._interval_s is not None:
            lo, hi = self._interval_s
            mode = "interval_s"
        else:
            lo, hi = self._spacing_mm  # type: ignore[misc]  # ровно один режим задан всегда
            mode = "spacing_mm"
        return {"mode": mode, "lo": lo, "hi": hi}

    def set_flow(
        self,
        *,
        interval_s: tuple[float, float] | None = None,
        spacing_mm: tuple[float, float] | None = None,
    ) -> None:
        """Переключить режим отсчёта следующего спавна на ЖИВОМ спавнере (Task 6.1,
        ручка «поток» стенда) — та же проверка, что в `__init__` (`validate_flow`), кривые
        аргументы бросают `ValueError` ДО любой мутации состояния (отказ атомарен —
        текущий режим остаётся как был).

        Сбрасывает НЕЗАВЕРШЁННЫЙ отсчёт только СВОЕГО вида: новый `interval_s` взводит
        срок заново (`_deadline = None`, как на первом тике — вызывающий воркер передаёт
        актуальный `now_wall_s` на следующем `tick()`), новый `spacing_mm` сбрасывает
        только порог до следующего спавна (`_next_spacing_mm = None`). `_last_spawn_encoder`
        (путь ленты, уже пройденный с последнего реального спавна) НЕ трогается ни в одном
        из двух случаев — переключение режима не должно стирать то, что лента уже проехала.
        Активные объекты, нумерация (`_next_id_n`) и пауза не меняются вовсе."""
        validate_flow(interval_s, spacing_mm)
        if interval_s is not None:
            self._interval_s = interval_s
            self._spacing_mm = None
            self._deadline = None
        else:
            self._spacing_mm = spacing_mm
            self._interval_s = None
            self._next_spacing_mm = None

    def set_factory(self, factory: ObjectFactory) -> None:
        """Горячая подмена фабрики (Task 1.2a, `preset.commit`): СЛЕДУЮЩИЕ спавны строит
        `factory`, объекты, уже активные, не трогаются (у них свой закэшированный рендер).
        Расписание спавна (срок/шаг/нумерация) не меняется.

        Невыпущенный форс-брак старой фабрики переносится на новую (`force_defect_next()`),
        иначе нажатие оператора, пришедшееся между commit и следующим спавном, пропало бы.

        Pre: вызывается из того же потока, что и `tick()` (воркер кадров) — так делает
        плагин `scene_source`; лока нет (см. докстринг модуля: один producer).
        """
        if self._factory.force_defect_pending:
            factory.force_defect_next()
        self._factory = factory

    def force_defect_next(self) -> None:
        """Тонкий делегат `ObjectFactory.force_defect_next()` — см. докстринг класса."""
        self._factory.force_defect_next()
