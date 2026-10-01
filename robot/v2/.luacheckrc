-- Конфиг luacheck для собранного main_v2.lua; стабы API DRAS — T4.x (firmware-architecture.md:47).
-- Артефакт объявляет глобалы (FW_BUILD, REG, OP, ...) на верхнем уровне — без этого W111 даёт rc 1.
allow_defined_top = true
