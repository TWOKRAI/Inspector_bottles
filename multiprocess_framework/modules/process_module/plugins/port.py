"""Port — типизированный вход/выход плагина.

Порт описывает что плагин принимает (input) или отдаёт (output).
Используется для валидации цепочки до запуска и auto-wiring.

dtype — MIME-подобная строка с иерархией:
    image/*          — любое изображение
      image/bgr      — BGR 3-канальное
      image/gray     — grayscale 1-канальное
      image/rgba     — RGBA 4-канальное
    tensor/*         — тензор
      tensor/float32
      tensor/uint8
    dict             — словарь (произвольные данные)
    bytes            — сырые байты
    any              — совместим с чем угодно (wildcard)

shape — шаблон размерности:
    "(H, W, 3)"     — изображение с 3 каналами
    "(H, W, 1)"     — маска
    "(H, W)"         — 2D без каналов
    "(N, 4)"         — N детекций по 4 координаты
    ""               — произвольная форма

Совместимость:
    image/bgr  →  image/bgr    ✓  точное совпадение
    image/bgr  →  image/*      ✓  wildcard match
    image/bgr  →  any          ✓  any принимает всё
    image/gray →  image/bgr    ✗  несовместимо
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

from ...data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("PortV1")
class Port(SchemaBase):
    """Типизированный порт плагина (вход или выход)."""

    name: Annotated[
        str,
        FieldMeta("Имя порта", info="Уникальное имя в пределах плагина: frame, mask, stats"),
    ] = ""

    dtype: Annotated[
        str,
        FieldMeta("Тип данных", info="MIME-подобный: image/bgr, image/gray, dict, tensor/float32, any"),
    ] = "any"

    shape: Annotated[
        str,
        FieldMeta("Форма", info="Шаблон размерности: (H, W, 3), (N, 4), пусто = произвольная"),
    ] = ""

    optional: Annotated[
        bool,
        FieldMeta("Опциональный", info="Если True — порт может быть не подключен"),
    ] = False

    description: Annotated[
        str,
        FieldMeta("Описание", info="Человекочитаемое описание порта"),
    ] = ""


def are_ports_compatible(output: Port, input_port: Port) -> bool:
    """Проверить совместимость выходного порта с входным.

    Правила (от GStreamer caps + UE pin inheritance):
    1. "any" совместим с чем угодно (wildcard)
    2. Точное совпадение dtype — совместимо
    3. Wildcard в dtype: "image/*" совместим с "image/bgr", "image/gray" и т.д.
    4. Shape: пустой шаблон совместим с любым
    5. Shape: шаблон с одинаковым числом элементов — совместим
       (переменные H, W, N — согласуются при линковке)
    """
    # any принимает всё
    if output.dtype == "any" or input_port.dtype == "any":
        return True

    # Точное совпадение
    if output.dtype == input_port.dtype:
        return _shapes_compatible(output.shape, input_port.shape)

    # Wildcard: image/* принимает image/bgr, image/gray и т.д.
    if _dtype_wildcard_match(output.dtype, input_port.dtype):
        return _shapes_compatible(output.shape, input_port.shape)

    return False


def _dtype_wildcard_match(out_dtype: str, in_dtype: str) -> bool:
    """Проверить wildcard совместимость dtype.

    "image/bgr" совместим с "image/*"
    "image/*" совместим с "image/*"
    "image/bgr" НЕ совместим с "tensor/*"
    """
    # Вход принимает wildcard?
    if in_dtype.endswith("/*"):
        prefix = in_dtype[:-2]  # "image"
        return out_dtype.startswith(prefix + "/") or out_dtype == prefix

    # Выход — wildcard? (выход image/* → вход image/bgr — совместимо)
    if out_dtype.endswith("/*"):
        prefix = out_dtype[:-2]
        return in_dtype.startswith(prefix + "/") or in_dtype == prefix

    return False


def _shapes_compatible(out_shape: str, in_shape: str) -> bool:
    """Проверить совместимость shape-шаблонов.

    "" (пустой) совместим с любым.
    "(H, W, 3)" совместим с "(H, W, 3)".
    "(H, W, 3)" НЕ совместим с "(H, W, 1)" — разное число каналов.
    "(H, W, *)" совместим с "(H, W, 3)" — wildcard по каналам.
    """
    if not out_shape or not in_shape:
        return True

    out_parts = _parse_shape(out_shape)
    in_parts = _parse_shape(in_shape)

    if len(out_parts) != len(in_parts):
        return False

    for o, i in zip(out_parts, in_parts):
        # Переменные (H, W, N) и wildcard (*) — совместимы
        if o == "*" or i == "*":
            continue
        if o.isalpha() or i.isalpha():
            continue  # переменная — согласуется при линковке
        # Числовые значения — должны совпадать
        if o != i:
            return False

    return True


def _parse_shape(shape: str) -> list[str]:
    """Разобрать shape-шаблон: "(H, W, 3)" → ["H", "W", "3"]."""
    s = shape.strip().strip("()")
    if not s:
        return []
    return [part.strip() for part in s.split(",")]


class PortValidationError(ValueError):
    """items на границе плагина не соответствуют Port-декларации (FW_PORT_VALIDATE=1).

    Dev-only sanity-check (Ф4.3): плагин объявил обязательный порт (inputs/
    outputs), а фактические items не несут его поле. Не проверяет dtype/shape
    во время выполнения — это статическая декларация контракта, а не
    runtime-типизация данных (углублять — вне объёма 4.3).
    """


def validate_items_against_ports(
    plugin_name: str,
    direction: str,
    ports: list[Port],
    items: list[dict],
) -> None:
    """Проверить, что items содержат поля всех обязательных портов плагина.

    Вызывается ТОЛЬКО за флагом ``FW_PORT_VALIDATE`` (см. ``PluginRunner``) —
    это dev-mode граница data-плоскости, не хочет оверхеда на hot path в prod.
    Optional-порты (``Port.optional=True``) пропускаются. Пустой ``items`` не
    считается ошибкой — плагин мог легитимно ничего не выдать (например,
    детектор без находок).

    Args:
        plugin_name: имя плагина (для текста ошибки).
        direction: "input" | "output" — какая граница проверяется.
        ports: декларация портов плагина (``plugin.inputs`` / ``plugin.outputs``).
        items: items на границе (входные — для "input", выходные — для "output").

    Raises:
        PortValidationError: обязательный порт '{name}' отсутствует хотя бы в
            одном item.
    """
    for port in ports:
        if port.optional:
            continue
        for idx, item in enumerate(items):
            if port.name not in item:
                raise PortValidationError(
                    f"{plugin_name}: {direction}-порт '{port.name}' ({port.dtype}) "
                    f"отсутствует в item[{idx}] (ключи: {sorted(item)})"
                )


def available_keys(
    chain: list[tuple[str, list[Port], list[Port]]],
    *,
    wired_inputs: Iterable[str] = (),
) -> dict[str, Port]:
    """Ключи, которые рантайм несёт в dict items к моменту после узлов ``chain``.

    Модель: вход узла покрыт, если ИМЯ его порта есть среди имён проводов процесса
    ∪ выходов узлов выше. Имя из провода даёт ``Port(dtype="any")`` (dtype провода
    уже сверен циклом Wire в ``SystemBlueprint.check``). Выход узла перезаписывает
    одноимённый ключ: побеждает последний производитель.

    Граница модели: плагин, возвращающий свежий dict, сбрасывает ключи; валидатор
    этого не видит (OPEN_QUESTIONS 2026-10-03, решение CTO; ADR-PM-052 в
    ``process_module/DECISIONS.md``).

    Args:
        chain: [(plugin_name, inputs, outputs), ...] в порядке выполнения.
        wired_inputs: имена портов, приходящих проводом процесса (один проход
            по итератору — генератор допустим).
    """
    keys: dict[str, Port] = {name: Port(name=name, dtype="any") for name in wired_inputs}
    for _, _, outputs in chain:
        for out in outputs:
            keys[out.name] = out
    return keys


def _last_producer(chain: list[tuple[str, list[Port], list[Port]]], key: str) -> tuple[str, list[Port]]:
    """(имя, выходы) последнего узла chain, чей выход называется ``key`` — для текста ошибки."""
    for name, _, outputs in reversed(chain):
        if any(out.name == key for out in outputs):
            return name, outputs
    return "провод процесса", []


def validate_chain_detailed(
    plugins_with_ports: list[tuple[str, list[Port], list[Port]]],
    *,
    wired_inputs: Iterable[str] = (),
) -> list[tuple[str, str, str]]:
    """Как :func:`validate_chain`, но каждая ошибка несёт ``(plugin_name, port_name, text)``.

    Нужна ``SystemBlueprint.check``: по паре (плагин, порт) он знает, какие адреса
    уже названы, и не дублирует их ошибкой «не подключен».
    """
    wired = tuple(wired_inputs)  # итератор читается ровно один раз
    findings: list[tuple[str, str, str]] = []

    for i, (curr_name, curr_inputs, _) in enumerate(plugins_with_ports):
        upstream = plugins_with_ports[:i]
        keys = available_keys(upstream, wired_inputs=wired)

        for inp in curr_inputs:
            if inp.optional:
                continue

            producer_port = keys.get(inp.name)
            if producer_port is None:
                findings.append(
                    (
                        curr_name,
                        inp.name,
                        f"Вход '{curr_name}.{inp.name}' ({inp.dtype}) не подключен: "
                        f"ключ '{inp.name}' не производит ни провод процесса, ни узел выше по цепочке",
                    )
                )
            elif not are_ports_compatible(producer_port, inp):
                prev_name, prev_outputs = _last_producer(upstream, inp.name)
                out_types = ", ".join(f"{o.name}:{o.dtype}" for o in prev_outputs)
                findings.append(
                    (
                        curr_name,
                        inp.name,
                        f"{prev_name} → {curr_name}: "
                        f"вход '{inp.name}' ({inp.dtype} {inp.shape}) "
                        f"несовместим с выходами [{out_types}]",
                    )
                )

    return findings


def validate_chain(
    plugins_with_ports: list[tuple[str, list[Port], list[Port]]],
    *,
    wired_inputs: Iterable[str] = (),
) -> list[str]:
    """Валидировать цепочку плагинов внутри процесса.

    Вход узла i проверяется по :func:`available_keys` узлов 0…i-1 плюс провода
    процесса. Два текста ошибки: ключа нет вовсе / ключ есть, но последний
    производитель несовместим. Optional-входы ошибок не дают.

    Args:
        plugins_with_ports: [(plugin_name, inputs, outputs), ...]
            в порядке выполнения
        wired_inputs: имена портов, приходящих проводом процесса.

    Returns:
        Список ошибок. Пустой = всё ОК.
    """
    return [text for _, _, text in validate_chain_detailed(plugins_with_ports, wired_inputs=wired_inputs)]
