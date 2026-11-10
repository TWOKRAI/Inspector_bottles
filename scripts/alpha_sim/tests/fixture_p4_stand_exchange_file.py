# ruff: noqa: E501  — литералы строк реального файла журнала
"""Строки реального файла журнала обмена стенда P4 (2026-11-10, data/logs/prototype/devices/robot_exchange.log).

Файл ДОПИСЫВАЕТСЯ между запусками прототипа: seq (после ``robot_main: #``) начинается с #1 заново.
BOUNDARY — граница двух инкарнаций (строки 636-650), TAIL_STOP — стоп последней инкарнации (строки 822-828).
"""

BOUNDARY = [
    "#722 2026-11-10 10:30:09,259 [INFO] S.d.d.e.robot_main: #621 in W* CMD_ARGC = 1",
    "#723 2026-11-10 10:30:09,259 [INFO] S.d.d.e.robot_main: #622 in W* CMD_ARGS[0] = 0",
    "#724 2026-11-10 10:30:09,259 [INFO] S.d.d.e.robot_main: #623 in W CMD_FLAG = 1",
    "#725 2026-11-10 10:30:09,280 [INFO] S.d.d.e.robot_main: #624 out R RES_SEQ..+12 RES_SEQ = 13908, RES_STATUS = 1, RES_ERRNO = 0 (ОК)",
    "#731 2026-11-10 10:30:09,383 [INFO] S.d.d.e.robot_main: #625 in W STOP_REQ = 5",
    "#737 2026-11-10 10:30:09,439 [INFO] S.d.d.e.robot_main: #626  disconnect",
    "#47 2026-11-10 10:37:08,581 [INFO] S.d.d.e.robot_main: #1  connect ok",
    "#48 2026-11-10 10:37:08,581 [INFO] S.d.d.e.robot_main: #2 out R RES_SEQ..+80 RES_SEQ = 13908, RES_STATUS = 1, RES_ERRNO = 0 (ОК)",
    "#49 2026-11-10 10:37:08,583 [INFO] S.d.d.e.robot_main: #3 in W* CMD_SEQ = 60466",
    "#50 2026-11-10 10:37:08,583 [INFO] S.d.d.e.robot_main: #4 in W* CMD_OPCODE = 65 (SERVO)",
    "#51 2026-11-10 10:37:08,583 [INFO] S.d.d.e.robot_main: #5 in W* CMD_ARGC = 1",
    "#52 2026-11-10 10:37:08,583 [INFO] S.d.d.e.robot_main: #6 in W* CMD_ARGS[0] = 1",
    "#53 2026-11-10 10:37:08,583 [INFO] S.d.d.e.robot_main: #7 in W CMD_FLAG = 1",
    "#54 2026-11-10 10:37:08,608 [INFO] S.d.d.e.robot_main: #8 out R RES_SEQ..+12 RES_SEQ = 60466, RES_STATUS = 1, RES_ERRNO = 0 (ОК)",
    "#57 2026-11-10 10:37:08,621 [INFO] S.d.d.e.robot_main: #9 in W 0x1204 = 1",
]

TAIL_STOP = [
    "#257 2026-11-10 10:44:42,384 [INFO] S.d.d.e.robot_main: #169 in W* CMD_OPCODE = 65 (SERVO)",
    "#258 2026-11-10 10:44:42,384 [INFO] S.d.d.e.robot_main: #170 in W* CMD_ARGC = 1",
    "#259 2026-11-10 10:44:42,384 [INFO] S.d.d.e.robot_main: #171 in W* CMD_ARGS[0] = 0",
    "#260 2026-11-10 10:44:42,384 [INFO] S.d.d.e.robot_main: #172 in W CMD_FLAG = 1",
    "#261 2026-11-10 10:44:42,406 [INFO] S.d.d.e.robot_main: #173 out R RES_SEQ..+12 RES_SEQ = 60477, RES_STATUS = 1, RES_ERRNO = 0 (ОК)",
    "#267 2026-11-10 10:44:42,434 [INFO] S.d.d.e.robot_main: #174 in W STOP_REQ = 9",
    "#273 2026-11-10 10:44:42,531 [INFO] S.d.d.e.robot_main: #175  disconnect",
]
