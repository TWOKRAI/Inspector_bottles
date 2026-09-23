"""ObjectSpawner — непрерывный поток объектов на ленте: спавн по интервалу ИЛИ по шагу
ленты в мм, деспавн за границей сцены, пауза, форс-хук брака.

Часы и очередь спавна принадлежат спавнеру целиком (LS-008): `tick()` — единственная
точка входа, вызывающий передаёт только "что сейчас" (`now_encoder`, `now_wall_s`, `rng`).
Единственный producer — поток-продюсер кадров (Task 3.4); лок не нужен, это НЕ
многопоточный доступ к одному инстансу (если появится второй вызывающий — тогда лок).

Два режима отсчёта следующего спавна (Task 3.3a, LS-010) — ровно один задан в конструкторе:
`interval_s` (по настенному времени, исходный режим Task 3.3) или `spacing_mm` (по пути
ленты — тот же `encoder_to_offset_mm`, которым уже пользуется деспавн). Режим `interval_s`
на стоящей ленте продолжает спавнить объекты в одну точку (известный дефект, воспроизведён
на живом стенде 2026-09-23 — три объекта с одинаковым `spawn_encoder`); `spacing_mm`
привязан к пути ленты, поэтому на стоящей ленте новые объекты не появляются сами собой.
"""

from __future__ import annotations

import numpy as np

from Services.line_sim.core.belt import encoder_to_offset_mm
from Services.line_sim.core.factory import ObjectFactory
from Services.line_sim.core.layered_object import LayeredObject
from Services.line_sim.interfaces import ObjectPassport


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
    `max_active > 0`.
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
    ) -> None:
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

        if self._interval_s is not None:
            self._tick_interval(now_encoder=now_encoder, now_wall_s=now_wall_s, rng=rng)
        else:
            self._tick_spacing(now_encoder=now_encoder, rng=rng)

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
            obj = self._factory.make(object_id, spawn_encoder=now_encoder, rng=rng)
            self._active.append(obj)
            self._next_id_n += 1

    def _tick_spacing(self, *, now_encoder: float, rng: np.random.Generator) -> None:
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
            traveled_mm = encoder_to_offset_mm(now_encoder, self._last_spawn_encoder)
            if traveled_mm < self._next_spacing_mm:
                return

        if len(self._active) >= self._max_active:
            return

        object_id = f"obj-{self._next_id_n}"
        self._last_spawn_encoder = now_encoder
        self._next_spacing_mm = float(rng.uniform(*self._spacing_mm))
        obj = self._factory.make(object_id, spawn_encoder=now_encoder, rng=rng)
        self._active.append(obj)
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

    def force_defect_next(self) -> None:
        """Тонкий делегат `ObjectFactory.force_defect_next()` — см. докстринг класса."""
        self._factory.force_defect_next()
