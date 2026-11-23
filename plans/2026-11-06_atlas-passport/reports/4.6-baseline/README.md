# Эталон «до» для Task 4.6a (снят на 1e085652f)

`python scripts/atlas ref <id> --format passport --root <клон на 1e085652f>`; `ProcessModule.json` — `ref ProcessModule --format json`.

| файл | id |
|---|---|
| ProcessModule.passport.txt | ProcessModule (41 строка) |
| def1.passport.txt | Services/auth/models.py::SessionEntry.SQLMeta (30; с 4.6b — вывод ПОСЛЕ правки, +4 строки полей; остальные семь — «до») |
| def2.passport.txt | Plugins/sim/pult_web/plugin.py::_build_handler._PultHandler (31) |
| def3.passport.txt | …::_build_handler._PultHandler.log_message (26) |
| def4.passport.txt | multiprocess_framework/modules/base_manager/interfaces.py::IHandle.kind (26) |
| def5.passport.txt | Services/robot_comm/server/belt.py::BeltDrive.mm_s_at_max_freq (26) |
| def6.passport.txt | Services/vfd_comm/core/client.py::VfdClient.config (26) |

`oracle.py` — образец скрипта оракула привязок (независимый `ast`-обход блобов `1e085652f`), 17 171 привязка = 9 978 модуля + 7 193 тела класса.
Приёмка: после правки в том же клоне `git checkout <impl-sha> -- scripts/atlas` и `diff -r -x README.md -x 4.6a-fixtures.md -x oracle.py` с этим каталогом — пусто (для 4.6b дополнительно `-x def1.passport.txt`).
