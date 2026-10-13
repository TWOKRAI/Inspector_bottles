"""Слепая приёмка T3.2: сценарий -> провод -> робот кусками (``wire_v2``, ``upload``, ``run_chunks``, обёртки опкодов).

Purpose:
    Тесты написаны ДО реализации, по DESIGN брифа T3.2 и по контракту ``protocol_v2``; код ``wire_v2`` / ``run_chunks``
    не читался. Стенд — ``FakeRobotTransport`` над ``RobotSimCoreV2`` без сети; время внедрено (``clock`` /
    ``sleep`` — счётчик), ``rng`` с литералом. Модули и методы T3.2 импортируются внутри ``_api()`` в теле теста:
    каждый тест краснеет отдельно, сборка файла не падает.

Допущения (то, что DESIGN оставил открытым; чем тест НЕ является — в докстроке каждого теста):
    A1. Кусок = жадно до EXACT: проверяется лишь то, что DESIGN назвал (сумма, ``count`` <= 27, чередование смещений,
        последняя запись куска не LINE_PASS), плюс непрерывность ``start``; точные ``count`` не пинятся.
    A2. ``decode_record`` отдаёт ``kind`` / ``action`` именем (``"JOINT"``) или кодом — тест принимает оба вида.
    A3. ``on_progress`` вызывается и посреди куска, и в конце куска; тест стопа сработает при любом из двух режимов,
        если вызов с ``done`` > началом третьего куска приходит, пока в журнале ровно 3 SC_RUN.
    A4. Адрес буфера клиент читает из ``REG["SC_BUF"]`` / ``CONSTANTS["SC_BASE"]`` в момент вызова, не при импорте
        (иначе подмена в тесте YAML-порчи не доходит до записи).

Stability: lite
"""

import math
import os
import random
import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

__all__: list[str] = []

_REPO_ROOT = Path(__file__).resolve().parents[3]
_YAML_PATH = _REPO_ROOT / "Services" / "robot_comm" / "protocols" / "delta_v2.yaml"
_GOLDEN_PATH = Path(__file__).resolve().parent / "golden" / "t32_run_chunks.log"
_GOLDEN_SEED = 20261012
_DEADLINE_S = 120.0
_HALF = 27  # литерал половины буфера сценария (55 // 2): наибольший count куска и смещение второй половины
_TICKS_PER_READ = 1  # тик на чтение: прогресс виден посреди куска, а не только на его конце

#: Зона, мм и °: литералы, совпадают с умолчаниями sim.
_PARAMS = {
    "P_WS_R_MIN": 100,
    "P_WS_R_MAX": 600,
    "P_WS_Z_MIN": -150,
    "P_WS_Z_MAX": 0,
    "P_WS_RZ_MIN": -360,
    "P_WS_RZ_MAX": 360,
    "P_WS_ANG_MIN": -165,
    "P_WS_ANG_MAX": 165,
    "P_WS_BOX_EN": 0,
    "P_WS_X_MIN": -600,
    "P_WS_X_MAX": 600,
    "P_WS_Y_MIN": -600,
    "P_WS_Y_MAX": 600,
    "P_HAND": 1,
}


# --------------------------------------------------------------------------------------------
# стенд
# --------------------------------------------------------------------------------------------


def _api() -> SimpleNamespace:
    """Импорт публичного API T3.2 в теле теста: нет модуля или метода -> красный именно этот тест."""
    from Services.robot_comm import errors
    from Services.robot_comm.core import client_v2, protocol_v2, wire_v2
    from Services.robot_comm.programs import CompileError, Record, Scenario
    from Services.robot_comm.server.sim_core_v2 import RobotSimCoreV2
    from Services.robot_comm.testing.fake_transport import FakeRobotTransport

    return SimpleNamespace(
        errors=errors,
        RobotAborted=errors.RobotAborted,
        RobotClientV2=client_v2.RobotClientV2,
        ClientV2Config=client_v2.ClientV2Config,
        protocol=protocol_v2,
        REG=protocol_v2.REG,
        OP=protocol_v2.OP,
        KIND=protocol_v2.KIND,
        ACT=protocol_v2.ACT,
        ERR=protocol_v2.ERR,
        CONSTANTS=protocol_v2.CONSTANTS,
        STOP_LEVEL=protocol_v2.STOP_LEVEL,
        wire_v2=wire_v2,
        CompileError=CompileError,
        Record=Record,
        Scenario=Scenario,
        RobotSimCoreV2=RobotSimCoreV2,
        FakeRobotTransport=FakeRobotTransport,
    )


@dataclass
class _Stand:
    api: SimpleNamespace
    core: object
    transport: object
    client: object


def _stand(api: SimpleNamespace, *, round_step: float | None = None, servo: bool = True, seed: int = 1) -> _Stand:
    """Фейк-робот + клиент с внедрённым временем. Пульс не взводится (сторож sim не трогаем)."""
    clock = {"t": 0.0}

    def read_clock() -> float:
        return clock["t"]

    def sleep(seconds: float) -> None:
        clock["t"] += seconds

    fields: dict[str, object] = {"done_timeout_s": 100000.0}
    if round_step is not None:
        fields["round_step"] = round_step
    config = api.ClientV2Config.from_dict(fields)
    core = api.RobotSimCoreV2()
    transport = api.FakeRobotTransport(core=core, ticks_per_read=_TICKS_PER_READ)
    client = api.RobotClientV2(transport, config, rng=random.Random(seed), clock=read_clock, sleep=sleep)
    transport.connect()
    client.probe()
    if servo:
        client.servo(True)
    return _Stand(api=api, core=core, transport=transport, client=client)


def _bounded(call):
    """Вызов в daemon-потоке с дедлайном 120 с: живой поток после дедлайна — провал. Исключение пробрасывается."""
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["value"] = call()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток теста
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=_DEADLINE_S)
    if thread.is_alive():
        pytest.fail(f"вызов не завершился за {_DEADLINE_S:.0f} с (поток жив)")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box.get("value")


# --------------------------------------------------------------------------------------------
# программы и оракулы (свои, не из проверяемого кода)
# --------------------------------------------------------------------------------------------


def _circle_scenario(api: SimpleNamespace, n: int, ang_from: float, ang_to: float):
    """n точек на окружности r = 300 мм, угол равным шагом, z = -50, rz = 0.

    Запись 0 — JOINT, дальше LINE_PASS, каждая 4-я (индекс % 4 == 3) и последняя — LINE; действий нет.
    """
    records = []
    for i in range(n):
        angle = math.radians(ang_from + (ang_to - ang_from) * i / (n - 1))
        if i == 0:
            kind = "JOINT"
        elif i % 4 == 3 or i == n - 1:
            kind = "LINE"
        else:
            kind = "LINE_PASS"
        records.append(
            api.Record(
                x=300.0 * math.cos(angle),
                y=300.0 * math.sin(angle),
                z=-50.0,
                rz=0.0,
                kind=kind,
                action="NONE",
                aparam=0,
            )
        )
    return api.Scenario(records=tuple(records), step_of=tuple(range(n)))


def _half_away(value: float) -> int:
    """Округление половина от нуля (оракул теста)."""
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def _oracle_words(api: SimpleNamespace, record) -> tuple[int, ...]:
    """Слова u16 записи при round_step = 0.1: ×10, половина от нуля, дополнительный код; OP = KIND + 256 * ACT."""
    coords = tuple(_half_away(v * 10.0) & 0xFFFF for v in (record.x, record.y, record.z, record.rz))
    return (*coords, api.KIND[record.kind] + 256 * api.ACT[record.action], record.aparam)


def _s16(word: int) -> int:
    return word - 0x10000 if word >= 0x8000 else word


def _pose(stand: _Stand) -> tuple[float, float, float, float]:
    """Поза sim из TLM_X..TLM_RZ, ×0.1."""
    raw = stand.core.read(stand.api.REG["TLM_X"], 4)
    return tuple(_s16(w) / 10.0 for w in raw)  # type: ignore[return-value]


def _code(value, table: dict[str, int]) -> int:
    """Имя или код -> код (допущение A2: ``decode_record`` вправе отдавать и то, и другое)."""
    return table[value] if isinstance(value, str) else int(value)


# --------------------------------------------------------------------------------------------
# разбор журнала записей
# --------------------------------------------------------------------------------------------


def _ops(stand: _Stand) -> list[tuple]:
    """Плоский список операций записи в порядке журнала."""
    return [op for txn in stand.transport.transactions for op in txn]


def _op_span(op: tuple) -> tuple[int, int]:
    """Полуинтервал адресов [lo, hi), который пишет операция журнала."""
    if op[0] == "w":
        return op[1], op[1] + 1
    if op[0] == "wm":
        return op[1], op[1] + len(op[2])
    raise AssertionError(f"неизвестная операция журнала: {op[0]!r}")


def _touches(op: tuple, lo: int, hi: int) -> bool:
    start, end = _op_span(op)
    return start < hi and lo < end


def _cmd_block(api: SimpleNamespace, op: tuple) -> tuple[int, list[int]] | None:
    """Если операция пишет блок CMD с опкодом: (опкод, аргументы), иначе None."""
    if op[0] != "wm":
        return None
    address, values = op[1], list(op[2])
    index = api.REG["CMD_OPCODE"] - address
    if not 0 <= index < len(values):
        return None
    argc = values[api.REG["CMD_ARGC"] - address]
    first = api.REG["CMD_ARGS"] - address
    return values[index], values[first : first + argc]


def _sc_runs(stand: _Stand) -> list[tuple[int, int, int]]:
    """(count, sc_id, offset) каждой транзакции SC_RUN, по журналу."""
    runs = []
    for op in _ops(stand):
        block = _cmd_block(stand.api, op)
        if block is not None and block[0] == stand.api.OP["SC_RUN"]:
            count, sc_id, offset = block[1][:3]
            runs.append((count, sc_id, offset))
    return runs


def _log_lines(stand: _Stand) -> list[str]:
    """Лог golden: по строке на операцию записи, ``W <адрес hex> <слова u16 через пробел>``."""
    lines = []
    for op in _ops(stand):
        values = [op[2]] if op[0] == "w" else list(op[2])
        _op_span(op)
        assert all(0 <= int(v) <= 0xFFFF for v in values), "в журнале слово вне u16"
        lines.append(f"W {op[1]:04X} " + " ".join(str(int(v)) for v in values))
    return lines


def _run_program60() -> tuple[list[str], tuple[float, float, float, float]]:
    """Фиксированная программа из 60 записей на фейке; (лог записей, итоговая поза sim)."""
    api = _api()
    scenario = _circle_scenario(api, 60, -60.0, 60.0)
    stand = _stand(api, seed=_GOLDEN_SEED)
    _bounded(lambda: stand.client.run_chunks(scenario, params=_PARAMS))
    return _log_lines(stand), _pose(stand)


def _golden_lines() -> list[str]:
    """Строки golden без ``#``; нет файла — провал."""
    if not _GOLDEN_PATH.exists():
        pytest.fail(f"нет файла эталона {_GOLDEN_PATH.name}: сгенерировать ROBOT_GOLDEN_UPDATE=1")
    text = _GOLDEN_PATH.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if not line.startswith("#")]


# --------------------------------------------------------------------------------------------
# a. 200 точек кусками
# --------------------------------------------------------------------------------------------


def test_200_points_run_in_chunks_with_exact_borders():
    """200 точек уходят кусками <= 27, граница каждого куска — на EXACT-записи, половины буфера чередуются.

    Из журнала записей: SC_RUN (count, sc_id, offset), содержимое буфера в момент каждого SC_RUN (свой оракул слов),
    окно, в котором идёт кусок. Из ответа: ``report.chunks``, ``on_progress``, итоговая поза sim.

    НЕ доказывает: точные ``count`` кусков (допущение A1), что ``wait_done`` ждёт именно приход в точку на
    железе (sim завершает кусок на своём тике), порядок опроса между кусками по времени.
    """
    api = _api()
    scenario = _circle_scenario(api, 200, -150.0, 150.0)
    stand = _stand(api)
    progress: list[tuple[int, int]] = []

    report = _bounded(
        lambda: stand.client.run_chunks(
            scenario, params=_PARAMS, on_progress=lambda done, total: progress.append((done, total))
        )
    )

    runs = _sc_runs(stand)
    assert sum(count for count, _, _ in runs) == 200
    assert all(1 <= count <= _HALF for count, _, _ in runs)
    assert [offset for _, _, offset in runs] == [0 if k % 2 == 0 else _HALF for k in range(len(runs))]

    chunks = []
    start = 0
    for count, _, offset in runs:
        last = start + count - 1
        assert scenario.records[last].kind != "LINE_PASS", f"кусок с {start} кончается на LINE_PASS (запись {last})"
        chunks.append((start, count, offset))
        start += count
    assert tuple(tuple(c) for c in report.chunks) == tuple(chunks)
    assert report.total == 200

    assert progress, "on_progress ни разу не вызван"
    assert all(total == 200 for _, total in progress)
    assert all(later[0] >= earlier[0] for earlier, later in zip(progress, progress[1:], strict=False))
    assert progress[-1] == (200, 200)

    x, y, z, rz = _pose(stand)
    assert abs(x - (-259.8)) <= 0.1 + 1e-9  # 300 * cos(150 deg) = -259.81
    assert abs(y - 150.0) <= 0.1 + 1e-9
    assert abs(z - (-50.0)) <= 0.1 + 1e-9
    assert abs(rz - 0.0) <= 0.1 + 1e-9

    # буфер в момент каждого SC_RUN держит записи именно этого куска (пересборка буфера по журналу)
    buf: dict[int, int] = {}
    run_index = 0
    running: tuple[int, int] | None = None  # [lo, hi) адресов куска, который сейчас идёт
    sc_buf = api.REG["SC_BUF"]
    stride = api.CONSTANTS["SC_STRIDE"]
    for op in _ops(stand):
        block = _cmd_block(api, op)
        if block is not None and block[0] == api.OP["SC_RUN"]:
            chunk_start, count, offset = chunks[run_index]
            for j in range(count):
                expected = _oracle_words(api, scenario.records[chunk_start + j])
                got = tuple(buf.get(sc_buf + (offset + j) * stride + w) for w in range(stride))
                assert got == expected, f"SC_RUN #{run_index}: запись {chunk_start + j} в буфере не та"
            running = (sc_buf + offset * stride, sc_buf + (offset + count) * stride)
            run_index += 1
        elif op[0] == "wm" and _touches(op, sc_buf, sc_buf + api.CONSTANTS["SC_CAP"] * stride):
            if running is not None:
                assert not _touches(op, *running), "запись в половину буфера, пока кусок из неё идёт"
            for k, word in enumerate(op[2]):
                buf[op[1] + k] = int(word)
    assert run_index == len(chunks)


# --------------------------------------------------------------------------------------------
# b. стоп посреди третьего куска
# --------------------------------------------------------------------------------------------


def test_stop_in_third_chunk_aborts_and_loads_nothing_more():
    """HARD-стоп из ``on_progress`` в третьем куске: ``RobotAborted(E_ABORTED)``, после стопа ни загрузки, ни команды.

    Условие стопа — как в брифе: в журнале ровно 3 SC_RUN и ``done`` больше начала третьего куска. После
    запомненной точки журнала: нет записей в буфер сценария и нет записей флага CMD; всего SC_RUN — 3.

    НЕ доказывает: стоп SOFT/HALT, стоп из другого потока (здесь он из потока ``run_chunks``), поведение
    настоящей прошивки после HARD.
    """
    api = _api()
    scenario = _circle_scenario(api, 200, -150.0, 150.0)
    stand = _stand(api)
    state: dict[str, int | None] = {"mark": None}

    def on_progress(done: int, total: int) -> None:
        if state["mark"] is not None:
            return
        runs = _sc_runs(stand)
        if len(runs) == 3 and done > runs[0][0] + runs[1][0]:
            stand.client.stop(api.STOP_LEVEL["HARD"])
            state["mark"] = len(stand.transport.transactions)

    with pytest.raises(api.RobotAborted) as info:
        _bounded(lambda: stand.client.run_chunks(scenario, params=_PARAMS, on_progress=on_progress))

    assert state["mark"] is not None, "условие стопа не наступило: стоп не выдан"
    assert info.value.errno == api.ERR["E_ABORTED"]
    after = [op for txn in stand.transport.transactions[state["mark"] :] for op in txn]
    sc_lo = api.CONSTANTS["SC_BASE"]
    sc_hi = sc_lo + 330
    assert not [op for op in after if _touches(op, sc_lo, sc_hi)], "после стопа записан буфер сценария"
    flag = api.REG["CMD_FLAG"]
    assert not [op for op in after if _touches(op, flag, flag + 1)], "после стопа взведён флаг CMD"
    assert len(_sc_runs(stand)) == 3


# --------------------------------------------------------------------------------------------
# c, d. golden-лог и его порча через YAML
# --------------------------------------------------------------------------------------------


def test_golden_log_matches():
    """Лог записей программы из 60 точек (rng = Random(20261012)) равен эталону построчно.

    ``ROBOT_GOLDEN_UPDATE=1`` пишет эталон и проходит (если прогон дошёл до последней точки).

    НЕ доказывает: что последовательность записей верна для железа. Эталон самоссылочный: он снят с того же
    клиента, поэтому ловит только непреднамеренный дрейф, а не неверную с самого начала раскладку.
    """
    log, pose = _run_program60()
    assert abs(pose[0] - 150.0) <= 0.1 + 1e-9  # 300 * cos(60 deg)
    assert abs(pose[1] - 259.8) <= 0.1 + 1e-9  # 300 * sin(60 deg) = 259.81
    assert abs(pose[2] - (-50.0)) <= 0.1 + 1e-9
    assert abs(pose[3] - 0.0) <= 0.1 + 1e-9

    if os.environ.get("ROBOT_GOLDEN_UPDATE") == "1":
        header = [
            "# самоссылочный эталон, не железо",
            "# программа: 60 точек на окружности r=300 мм, угол от -60 до +60 градусов равным шагом, z=-50, rz=0;",
            "#   запись 0 JOINT, дальше LINE_PASS, каждая 4-я запись и последняя LINE, действий нет",
            f"# стенд: RobotSimCoreV2 через FakeRobotTransport, rng=random.Random({_GOLDEN_SEED}); в логе все записи",
            "#   в регистры по порядку журнала: servo, загрузка кусков, SC_RUN",
            "# формат строки: W <адрес hex> <слова u16 через пробел>",
            "# перегенерировать: ROBOT_GOLDEN_UPDATE=1 python -m pytest "
            "Services/robot_comm/tests/test_client_v2_chunks_acceptance.py -k golden_log_matches",
        ]
        _GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN_PATH.write_text("\n".join([*header, *log]) + "\n", encoding="utf-8")
        return

    assert log == _golden_lines()


def test_yaml_address_corruption_breaks_golden(tmp_path, monkeypatch):
    """Правка адреса буфера в YAML (0x1400 -> 0x1406) -> кодоген -> подмена словарей -> лог расходится с эталоном.

    Первая отличающаяся строка — запись загрузки по адресу 0x1406 (эталон — по 0x1400), прогон при этом доходит
    до последней точки. Подмена ``CONSTANTS`` / ``REG`` — через ``monkeypatch.setitem``: sim делит эти словари с
    клиентом и читает буфер по ``REG["SC_BUF"]``.

    НЕ доказывает: что правка YAML доходит до клиента без monkeypatch (в бою словари меняет перегенерация
    ``protocol_v2.py`` и перезапуск процесса); не проверяет согласие адресов с прошивкой.
    """
    from Services.robot_comm import codegen
    from Services.robot_comm.core import protocol_v2

    proto_dir = tmp_path / "Services" / "robot_comm" / "protocols"
    proto_dir.mkdir(parents=True)
    text = _YAML_PATH.read_bytes().decode("utf-8").replace("\r\n", "\n")
    buf_block = "  sc_buf:\n    type: block\n    address: 0x1400\n"
    base_line = "  SC_BASE: 0x1400\n"
    assert text.count(buf_block) == 1
    assert text.count(base_line) == 1
    text = text.replace(buf_block, buf_block.replace("0x1400", "0x1406")).replace(
        base_line, base_line.replace("0x1400", "0x1406")
    )
    (proto_dir / "delta_v2.yaml").write_bytes(text.encode("utf-8"))

    outputs = codegen.generate(tmp_path)
    generated = next(body for path, body in outputs.items() if path.name == "protocol_v2.py")
    namespace: dict[str, object] = {}
    exec(compile(generated, "protocol_v2_corrupted.py", "exec"), namespace)  # noqa: S102 — свой генерат из tmp
    assert namespace["CONSTANTS"]["SC_BASE"] == 0x1406
    assert namespace["REG"]["SC_BUF"] == 0x1406

    golden = _golden_lines()  # читаем эталон до подмены
    monkeypatch.setitem(protocol_v2.CONSTANTS, "SC_BASE", namespace["CONSTANTS"]["SC_BASE"])
    monkeypatch.setitem(protocol_v2.REG, "SC_BUF", namespace["REG"]["SC_BUF"])
    log, pose = _run_program60()

    assert abs(pose[0] - 150.0) <= 0.1 + 1e-9  # прогон дошёл до последней точки
    assert abs(pose[1] - 259.8) <= 0.1 + 1e-9
    assert log != golden
    first = next(i for i, (a, b) in enumerate(zip(log, golden, strict=False)) if a != b)
    assert int(log[first].split()[1], 16) == 0x1406
    assert int(golden[first].split()[1], 16) == 0x1400


# --------------------------------------------------------------------------------------------
# e. круг: ошибка округления не больше половины шага
# --------------------------------------------------------------------------------------------

_ACTIONS = st.one_of(
    st.just(("NONE", 0)),
    st.tuples(st.sampled_from(["DO_ON", "DO_OFF"]), st.integers(1, 16)),
    st.tuples(st.just("DELAY_MS"), st.integers(0, 65535)),
    st.tuples(st.just("SPEED_PCT"), st.integers(1, 100)),
    st.tuples(st.just("ACCUR"), st.integers(0, 1)),
)
_POINT = st.tuples(
    st.floats(110.0, 590.0, allow_nan=False),  # r, мм
    st.floats(-160.0, 160.0, allow_nan=False),  # угол, °
    st.floats(-140.0, -10.0, allow_nan=False),  # z, мм
    st.floats(-350.0, 350.0, allow_nan=False),  # rz, °
    _ACTIONS,
)


@settings(max_examples=100, deadline=None, derandomize=True)
@given(round_step=st.sampled_from([0.1, 0.2, 0.5]), points=st.lists(_POINT, min_size=1, max_size=9))
def test_roundtrip_within_half_round_step(round_step, points):
    """encode -> upload -> чтение буфера -> decode: координата уходит от исходной не дальше ``round_step / 2``.

    Записи внутри зоны с запасом >= 1 мм, все JOINT (без отрезков); значение после круга кратно ``round_step``;
    kind / action / aparam сохраняются (действия разные — проверяется и упаковка слова OP).

    НЕ доказывает: границу зоны после округления (это тест f), отрезки LINE, поведение sim на этих записях
    (SC_RUN здесь не выдаётся), порядок слов на проводе Modbus (читается массив sim, не байты).
    """
    api = _api()
    records = []
    for r, angle_deg, z, rz, (action, aparam) in points:
        angle = math.radians(angle_deg)
        records.append(
            api.Record(
                x=r * math.cos(angle),
                y=r * math.sin(angle),
                z=z,
                rz=rz,
                kind="JOINT",
                action=action,
                aparam=aparam,
            )
        )
    scenario = api.Scenario(records=tuple(records), step_of=tuple(range(len(records))))
    stand = _stand(api, round_step=round_step, servo=False)

    words = api.wire_v2.encode_scenario(scenario, params=_PARAMS, round_step=round_step)
    assert len(words) == len(records)
    assert all(len(w) == 6 and all(0 <= int(v) <= 0xFFFF for v in w) for w in words)
    stand.client.upload(words, 0)
    stride = api.CONSTANTS["SC_STRIDE"]
    stored = stand.core.read(api.CONSTANTS["SC_BASE"], stride * len(records))

    for i, record in enumerate(records):
        decoded = api.wire_v2.decode_record(tuple(stored[i * stride : (i + 1) * stride]))
        for original, got in zip((record.x, record.y, record.z, record.rz), decoded[:4], strict=True):
            assert abs(got - original) <= round_step / 2 + 1e-9
            assert abs(got - round(got / round_step) * round_step) <= 1e-6
        assert _code(decoded[4], api.KIND) == api.KIND[record.kind]
        assert _code(decoded[5], api.ACT) == api.ACT[record.action]
        assert decoded[6] == record.aparam


# --------------------------------------------------------------------------------------------
# f. точка у границы зоны: округление выводит её за зону -> отказ на ПК
# --------------------------------------------------------------------------------------------


def test_point_leaving_zone_after_rounding_rejected_on_pc():
    """Точка r = 599.994 в зоне, после округления до 0.1 (424.3, 424.3) r = 600.051 вне зоны -> ``CompileError``.

    ``encode_scenario`` и ``run_chunks`` отдают ``step == 7``, ``reason == 4``; ``run_chunks`` не пишет в
    регистры ни слова (журнал до и после одинаков). Пара достижимости: (424.2, 424.2), r = 599.9, кодируется.

    НЕ доказывает: отказ для LINE-отрезка и мёртвой зоны (причины 5), другие шаги округления, что робот сам
    отверг бы эту точку (проверка именно на ПК, sim не запускается).
    """
    api = _api()
    first = api.Record(x=300.0, y=0.0, z=-50.0, rz=0.0, kind="JOINT", action="NONE", aparam=0)
    edge = api.Record(x=424.26, y=424.26, z=-50.0, rz=0.0, kind="JOINT", action="NONE", aparam=0)
    inner = api.Record(x=424.2, y=424.2, z=-50.0, rz=0.0, kind="JOINT", action="NONE", aparam=0)
    bad = api.Scenario(records=(first, edge), step_of=(0, 7))
    good = api.Scenario(records=(first, inner), step_of=(0, 7))
    assert math.hypot(424.26, 424.26) < 600.0 < math.hypot(424.3, 424.3)  # оракул самого теста

    with pytest.raises(api.CompileError) as encode_info:
        api.wire_v2.encode_scenario(bad, params=_PARAMS, round_step=0.1)
    assert encode_info.value.step == 7
    assert encode_info.value.reason == 4

    stand = _stand(api)
    before = len(stand.transport.transactions)
    with pytest.raises(api.CompileError) as run_info:
        _bounded(lambda: stand.client.run_chunks(bad, params=_PARAMS))
    assert run_info.value.step == 7
    assert run_info.value.reason == 4
    assert len(stand.transport.transactions) == before

    words = api.wire_v2.encode_scenario(good, params=_PARAMS, round_step=0.1)
    assert tuple(words[1][:4]) == (4242, 4242, 65036, 0)  # 424.2*10, 424.2*10, -50*10 (u16), 0


# --------------------------------------------------------------------------------------------
# g. шаг округления в конфиге
# --------------------------------------------------------------------------------------------


def test_round_step_config_errors():
    """Шаг округления 0.05 и 0.15 отвергается ``ValueError`` с именем поля и без входного значения; 0.1/0.2/0.5 — нет.

    Без ключа — 0.1. Принятие проверяется отдельно: «отказ на неизвестное поле» тоже ``ValueError`` с этим именем,
    и без проверки принятия тест краснел бы только на втором шаге.

    НЕ доказывает: другие недопустимые шаги (0, отрицательный, строка), влияние шага на ``run_chunks`` (тесты e, f).
    """
    api = _api()
    for ok in (0.1, 0.2, 0.5):
        assert api.ClientV2Config.from_dict({"round_step": ok}).round_step == ok
    assert api.ClientV2Config.from_dict({}).round_step == 0.1

    for bad in (0.05, 0.15):
        with pytest.raises(ValueError) as info:
            api.ClientV2Config.from_dict({"round_step": bad})
        message = str(info.value)
        assert "round_step" in message
        assert str(bad) not in message


# --------------------------------------------------------------------------------------------
# h. обёртка на каждый опкод
# --------------------------------------------------------------------------------------------


def test_every_opcode_has_wrapper():
    """У каждого опкода ``OP`` есть обёртка (``WRAPPERS``: опкод -> имя метода); ``ptp_move`` пишет округлённые слова.

    ``ptp_move(300.04, -10.06, -50.0, 1.25, kind="JOINT", spd_pct=50)`` при шаге 0.1: аргументы блока CMD
    3000, -101, -500, 13 (слова u16 в журнале: 3000, 65435, 65036, 13), ``KIND["JOINT"]``, 50.

    НЕ доказывает: аргументы остальных обёрток (кроме ``ptp_move``), ожидание завершения внутри обёрток (тест
    смотрит только запись в блок CMD), ошибки при неверных аргументах, округление шагом 0.2 / 0.5 в ``ptp_move``.
    """
    api = _api()
    assert set(api.RobotClientV2.WRAPPERS) == set(api.OP)
    for name in api.RobotClientV2.WRAPPERS.values():
        assert callable(getattr(api.RobotClientV2, name)), name

    stand = _stand(api)
    _bounded(lambda: stand.client.ptp_move(300.04, -10.06, -50.0, 1.25, kind="JOINT", spd_pct=50))
    moves = [
        block
        for block in (_cmd_block(api, op) for op in _ops(stand))
        if block is not None and block[0] == api.OP["PTP_MOVE"]
    ]
    assert len(moves) == 1
    assert moves[0][1] == [3000, 65435, 65036, 13, api.KIND["JOINT"], 50]
