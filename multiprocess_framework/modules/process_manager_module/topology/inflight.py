# -*- coding: utf-8 -*-
"""Бюджет «в полёте» процесса-получателя кадров (Task 4.7c).

**Зачем.** Кадр лежит в слоте SHM-кольца глубины D; по очереди идёт только ссылка на слот.
Писатель ходит по кольцу по кругу и через D кадров перезапишет тот же слот. Если у получателя
«в полёте» (data-очередь + потолок отставания исполнителя ``chain_max_lag_items``) может сидеть
больше D - 2 сообщений, то самое старое из них переживёт свой кадр: ссылка есть, пикселей уже
нет (разорванное чтение, пойманное seqlock'ом, — то есть потеря кадра вместо обработки).
Поэтому правило одно: **очередь + lag <= D - 2**; два слота запаса — на кадр, который читается
прямо сейчас, и на тот, который пишется прямо сейчас.

D — минимум глубин колец ВСЕХ писателей, чьи кадры получает процесс: самое мелкое кольцо
перезапишется первым. Камеры друг на друга не влияют: бюджет считается только по писателям
этого получателя (вызывающий передаёт именно их).

**Нижняя граница.** ``chain_max_lag_items == 0`` в DataReceiver означает «без границы» — для
процесса за кольцом это ловушка, поэтому lag всегда >= 1, очередь тоже >= 1. Минимум по
бюджету 2 (D = 4) → единственное разбиение (1, 1). Кольцо мельче 4 — ошибка построения.

Чистая функция без зависимостей: её зовёт ``SystemBlueprint.build_configs()``, ошибка поднимается
при сборке рецепта, а не на живой системе.
"""

from __future__ import annotations

from collections.abc import Iterable

# Стандартный потолок отставания исполнителя; на малом бюджете (D = 4) урезается до B - 1.
_DEFAULT_LAG = 2
# Запас слотов кольца сверх «в полёте»: кадр читается + кадр пишется.
_RING_RESERVE = 2
# Минимальное кольцо: бюджет B = D - 2 >= 2 (очередь >= 1 и lag >= 1).
_MIN_RING_DEPTH = _RING_RESERVE + 2


def inflight_budget(
    writer_depths: Iterable[int],
    *,
    queue: int | None = None,
    lag: int | None = None,
    process: str = "?",
) -> tuple[int, int]:
    """Вернуть ``(data_queue_maxsize, chain_max_lag_items)`` для получателя кадров.

    Args:
        writer_depths: глубины колец всех писателей, чьи кадры получает процесс.
        queue: явный размер data-очереди из рецепта (None = вывести).
        lag: явный потолок отставания из рецепта (None = вывести; 0 тут не «авто» —
            вызывающий переводит 0 в None).
        process: имя процесса — только для текста ошибки.

    Raises:
        ValueError: писателей нет; кольцо мельче 4; явные значения не влезают в D - 2.
    """
    depths = [int(d) for d in writer_depths]
    if not depths:
        raise ValueError(f"процесс '{process}': нет ни одного писателя кольца — бюджет считать не от чего")
    ring = min(depths)
    if ring < _MIN_RING_DEPTH:
        raise ValueError(
            f"процесс '{process}': кольцо {ring} слишком мелкое — на очередь >= 1 и lag >= 1 "
            f"(lag 0 = «без границы») нужно кольцо не меньше {_MIN_RING_DEPTH}"
        )
    budget = ring - _RING_RESERVE

    if lag is None:
        # lag по умолчанию 2, но не больше B - 1: иначе на границе (D = 4) очередь осталась бы 0.
        lag = min(_DEFAULT_LAG, budget - 1)
    elif lag < 1:
        raise ValueError(f"процесс '{process}': chain_max_lag_items {lag} < 1 (0 = «без границы» за кольцом)")
    if queue is None:
        queue = budget - lag
        if queue < 1:
            raise ValueError(
                f"процесс '{process}': lag {lag} не оставляет места очереди при кольце {ring} (бюджет {budget})"
            )
    elif queue < 1:
        raise ValueError(f"процесс '{process}': data_queue_maxsize {queue} < 1")

    if queue + lag > budget:
        raise ValueError(
            f"процесс '{process}': очередь {queue} больше кольца {ring} — очередь + lag = {queue + lag} "
            f"превышает бюджет в полёте {budget} (кольцо {ring} - {_RING_RESERVE}); "
            f"уменьшите data_queue_maxsize/chain_max_lag_items или увеличьте frame_ring_depth писателя"
        )
    return queue, lag
