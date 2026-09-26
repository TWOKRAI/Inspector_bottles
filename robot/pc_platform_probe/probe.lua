-- =====================================================================
--  Delta SCARA · DRAStudio (Lua/RL) — ПРОБА ПЛАТФОРМЫ (GATE-1 плана robot-protocol-v2)
--
--  Зачем. Протокол v2 опирается на факты о контроллере, которых нет в мануале под рукой:
--  какие адреса Modbus доступны, есть ли часы, как MultiTask делит время и состояние, можно
--  ли звать Override из function2, как быстро срабатывает MotionStop, как задать 4-ю ось
--  точки, можно ли на ходу переинициализировать CVT и порт RS-485. Эта программа отвечает
--  на них по командам с ПК (pc_probe.py) и ничего не делает сама.
--
--  Безопасность (проверено ревью 2026-09-27, каждое правило закрывает найденный сценарий):
--    • При старте движения нет, серво не трогаем, ПЧ получает СТОП (с повтором, итог в LIVE).
--    • Движение только после команды «якорь» (тест 29); каждая ЦЕЛЬ — в пределах ±50 мм по
--      X/Y/Z от якоря, скорость ≤ 30 %, Override из Mirror тоже ≤ 30 %.
--    • Нет позы (геттер вернул nil) — нет движения: относительная цель без позы стала бы
--      абсолютной.
--    • 4-ю ось на ходу не пишем вообще: точки объявлены при старте с текущей RZ, на ходу
--      меняются только X/Y/Z (WritePoint X/Y/Z доказан v1). Если RZ ушёл от стартового
--      больше чем на 1°, ход отклоняется. Ось RZ меняют только тесты 33/34 (±5°, с возвратом).
--    • Стоп с ПК прерывает и одиночный ход, и PASS-цепочку (проверка после каждого MovL).
--
--  Факты из мануала RL (DELTA_IA-ROBOT_DRAStudio_RL_EN_20240920, далее «RL»), которые проба
--  ПОДТВЕРЖДАЕТ на железе, а не принимает на веру: пользовательский Modbus 0x1000..0x1FFF
--  (0x3000..0x3FFF сохраняется при выключении, RL 12-2); 4-я ось в WritePoint/ReadPoint — «RZ»
--  (RL 5-9..5-10; v1 пишет «R»); Hand 0 правая / 1 левая (RL 5-3); таймер TimerOn/TimerRead в мс
--  (RL 3-4); MultiTask устарел, AuxTasks режет по 15 мс (RL 11-4..11-6); встроенный мастер RS-485
--  RSmasterRead/RSmasterWrite (RL 12-6); в ключевых словах есть goto — значит Lua ≥ 5.2.
--
--  Язык. Версия Lua контроллера неизвестна точно. Используется только то, что доказала рабочая
--  v1: #, %, pcall, tostring, type, string.char/byte/sub, math.floor, локальные функции,
--  таблицы. pairs, table.sort, error, _G — только после проверки type(...).
--  Общее состояние Motion и Mirror — в ГЛОБАЛАХ с префиксом PB_, как в v1. Работает ли
--  общий доступ через локальные переменные, проба как раз проверяет (тест 30, поле shared).
--
--  Канал ПК ↔ проба — в 0x1400..0x154B: единственный сплошной диапазон, который v1
--  гарантированно использовала (буфер точек рисования).
--
--    0x1400 CMD_FLAG   ПК пишет 1 ПОСЛЕДНИМ; проба сбрасывает в 0 при приёме
--    0x1401 CMD_SEQ    номер запроса (эхо в RES_SEQ); повтор номера не исполняется
--    0x1402 CMD_TEST   номер теста (таблица TESTS)
--    0x1404..0x140F    ARG0..ARG11
--    0x1410 RES_SEQ    проба пишет ПОСЛЕДНИМ — маркер готовности ответа
--    0x1411 RES_STATUS 1 ок · 2 ошибка теста (текст в буфере) · 3 нет такого теста
--                      4 функции нет на этом контроллере · 5 отказ по безопасности
--    0x1412 RES_N      число значений
--    0x1414..0x1433    RES_VAL0..31
--    0x1440..0x144F    LIVE: +0 HB_MOTION +1 HB_MIRROR +2 MOVING +3..6 X/Y/Z/RZ ×0.1
--                      +7 HAND +8/+9 ENC [lo,hi] +10 MIRROR_ERR +11 LAST_TEST
--                      +12 VFD_BOOT_STOP (1 ПЧ подтвердил / 2 нет ответа) +13 POSE_OK
--    0x1450..0x1457    CTRL: +0 STOP_REQ (изменение → MotionStop) +1 OVR_REQ (изменение → Override)
--                      +2 MIRROR_POSE (1 = Mirror публикует позу во время хода)
--                      +3 STOP_SEEN_TICK +4 OVR_RESULT (1 ок / 2 ошибка / 3 выше лимита)
--                      +5 SHARED_LOCAL +6 SHARED_GLOBAL (что видит Mirror)
--                      +7 FAST_STOP (1 = перед MotionStop DecL(25000) — максимум по RL 2-8; совет RL 1-51)
--    0x1460..0x151F    SCRATCH: область тестов атомарности и длины блоков
--
--  32-битные числа — двумя регистрами [lo, hi]. Все записи — знаковыми словами (как v1).
-- =====================================================================

local B = {
  CMD_FLAG = 0x1400, CMD_SEQ = 0x1401, CMD_TEST = 0x1402, ARG0 = 0x1404, ARG_N = 12,
  RES_SEQ = 0x1410, RES_STATUS = 0x1411, RES_N = 0x1412, VAL0 = 0x1414, VAL_N = 32,
  LIVE = 0x1440, CTRL = 0x1450, SCRATCH = 0x1460,
}

local ST_OK, ST_ERR, ST_NOTEST, ST_NOFUNC, ST_REFUSED = 1, 2, 3, 4, 5

-- ── геометрия и железо ──
local CV         = 1
local POSTURE    = {0, 0, 0, 0, 0, 0, 0, 4}
local ENVELOPE   = 500          -- ×0.1 мм: цель не дальше 50 мм от якоря по каждой оси
local RZ_TOL     = 10           -- ×0.1°: допуск RZ относительно стартового
local ROT_STEP   = 50           -- ×0.1°: поворот тестов 33/34
local MAX_SPD    = 30           -- %
local PT_ID, PT_NAME = 81, "GL_PROBE"
local POOL_BASE, POOL_N = 100, 40      -- точки PASS-цепочки: 101..140

local PORT, SLAVE    = 1, 1
local VFD_REG_CMD    = 0x2000
local VFD_REG_STATUS = 0x2100
local CMD_STOP       = 0x0005
local RS485_RATE, RS485_PROTOCOL, RS485_MODE = 0x2, 0xD, 0x11
local RX_TRIES       = 8

-- ── общее состояние Motion ↔ Mirror: глобалы, как в v1 ──
PB_hb_mirror, PB_mirror_err = 0, 0
PB_moving, PB_stop_seen = false, false
PB_last_stop, PB_last_ovr = 0, 0
PB_text = ""
PB_shared_global = 0
PB_fast_ok = nil                -- результат DecL(max) из Mirror перед быстрым стопом
local shared_local = 0          -- то же значение в local: проверка, видит ли его Mirror

-- ── состояние Motion ──
local hb_motion, last_seq = 0, -1
local boot_pose = nil           -- {x, y, z, r, hand} ×0.1 на момент старта
local anchor = nil              -- {x, y, z} ×0.1 — центр разрешённой оболочки

-- =====================  УТИЛИТЫ  ===================================
local function s16(v)                         -- целое → знаковое слово
  v = math.floor((v or 0) + 0.5) % 65536
  if v >= 32768 then return v - 65536 end
  return v
end

local function u16(v) return math.floor(v or 0) % 65536 end
local function abs(v) if v < 0 then return -v end; return v end

local function join(list, sep)                -- вместо table.concat
  local s = ""
  for i = 1, #list do
    if i > 1 then s = s .. sep end
    s = s .. list[i]
  end
  return s
end

local function rd(addr)                        -- nil-safe чтение слова, результат 0..65535
  local ok, v = pcall(ReadModbus, addr, "W")
  if not ok or v == nil then return nil end
  return u16(v)
end

local function wr(addr, v) pcall(WriteModbus, addr, "W", s16(v)) end

local function arg(i) return rd(B.ARG0 + i) or 0 end
local function sarg(i) local v = arg(i); if v >= 32768 then v = v - 65536 end; return v end

local function arg_text(first)                 -- ASCII из ARG[first..], 2 символа на регистр
  local out = {}
  for i = first, B.ARG_N - 1 do
    local w = arg(i)
    local hi, lo = math.floor(w / 256), w % 256
    if hi == 0 then break end
    out[#out + 1] = string.char(hi)
    if lo == 0 then break end
    out[#out + 1] = string.char(lo)
  end
  return join(out, "")
end

local function push_i32(vals, v)               -- 32 бита → [lo, hi]
  v = math.floor(v or 0) % 4294967296
  vals[#vals + 1] = s16(v % 65536)
  vals[#vals + 1] = s16(math.floor(v / 65536))
end

local function resolve(path)                   -- "os.clock" → значение или nil (без string.gmatch)
  if type(_G) ~= "table" then return nil end
  local cur, part = _G, ""
  for i = 1, #path + 1 do
    local ch = string.sub(path, i, i)
    if ch == "." or ch == "" then
      if type(cur) ~= "table" then return nil end
      cur = cur[part]
      part = ""
    else
      part = part .. ch
    end
  end
  return cur
end

-- Поза ×0.1 и рука. nil, если хоть один геттер не ответил числом: без позы не двигаемся.
local function pose()
  local function g(f)
    local ok, v = pcall(f)
    if ok and type(v) == "number" then return v end
    return nil
  end
  local x, y, z, r = g(RobotX), g(RobotY), g(RobotZ), g(RobotRZ)
  if not (x and y and z and r) then return nil end
  return {x = x * 10, y = y * 10, z = z * 10, r = r * 10, hand = g(RobotHand)}
end

-- =====================  RS-485 к ПЧ (мост v1, ответ FC6 — строгое эхо)  ============
local function xor16(a, b)
  local res, bit = 0, 1
  for _ = 0, 15 do
    if (a % 2) ~= (b % 2) then res = res + bit end
    a = math.floor(a / 2); b = math.floor(b / 2); bit = bit * 2
  end
  return res
end

local function crc16(s)
  local crc = 0xFFFF
  for i = 1, #s do
    crc = xor16(crc, string.byte(s, i))
    for _ = 1, 8 do
      if (crc % 2) == 1 then crc = xor16(math.floor(crc / 2), 0xA001)
      else crc = math.floor(crc / 2) end
    end
  end
  return crc
end

local function with_crc(body)
  local c = crc16(body)
  return body .. string.char(c % 256, math.floor(c / 256))
end

local function txn(req, expected)
  for _ = 1, 5 do SCM_Rx(PORT) end
  SCM_Tx(PORT, req)
  local buf = ""
  for _ = 1, RX_TRIES do
    local valid, data = SCM_Rx(PORT)
    if valid == 0 and type(data) == "string" and #data > 0 then buf = buf .. data end
    if #buf >= expected then break end
    DELAY(0.005)
  end
  return buf
end

local function vfd_read(addr, qty)             -- FC3 к ПЧ; таблица значений или nil
  local req = with_crc(string.char(SLAVE, 0x03, math.floor(addr / 256), addr % 256,
                                   math.floor(qty / 256), qty % 256))
  local buf = txn(req, 5 + 2 * qty)
  for i = 1, #buf - 1 do
    if string.byte(buf, i) == SLAVE and string.byte(buf, i + 1) == 0x03 then
      local bc = string.byte(buf, i + 2)
      if bc == 2 * qty and #buf >= i + 4 + bc then
        local c = crc16(string.sub(buf, i, i + 2 + bc))
        if string.byte(buf, i + 3 + bc) == c % 256 and string.byte(buf, i + 4 + bc) == math.floor(c / 256) then
          local out = {}
          for k = 0, qty - 1 do
            out[#out + 1] = string.byte(buf, i + 3 + 2 * k) * 256 + string.byte(buf, i + 4 + 2 * k)
          end
          return out
        end
      end
    end
  end
  return nil
end

local function vfd_write(addr, value)          -- успех = ответ побайтно совпал с запросом (эхо FC6)
  local req = with_crc(string.char(SLAVE, 0x06, math.floor(addr / 256), addr % 256,
                                   math.floor(value / 256), value % 256))
  local buf = txn(req, 8)
  for i = 1, #buf - 7 do
    if string.sub(buf, i, i + 7) == req then return true end
  end
  return false
end

local function open_port()
  return SCM_FreePort(PORT, RS485_RATE, RS485_PROTOCOL, RS485_MODE, 0x1, 0x0, 0x0, 0x00, 0x00)
end

-- =====================  CVT (initCVT дословно из main_actual.lua v1)  ==
local function initCVT()
  CVT_ChangeMotion()
  CVT_SelectMode(CV, 2)
  CVT_SetTriggerMode(CV, 2)
  local cvtFactor_num, cvtFactor_den, interval = 144473, 1000, 10
  local trans_ccd_x, trans_ccd_y, rotat_ccd_c = 0, 0, 0
  local vuPix2UmNum, vuPix2UmDen = 10, 1
  local vuAgRatioNum, vuAgRatioDen = 10, 1
  local vuXYExchgFlag = 0
  local cmpstVectorX, cmpstVectorY, cmpstVectorZ = 0, 1000, 0
  local srcType, srcIdx = 1, 1
  local cvtUFIdx = 1
  local NGZoneRadius = 20000
  local robotTrigLine = CVT_CalRobotTrigLine(334631, -381077, cmpstVectorX, cmpstVectorY)
  local zoneEndLine   = CVT_CalZoneEndLine(334631, -200000, cmpstVectorX, cmpstVectorY)
  local cvtuIdx, CV_instSlotIdx = 1, 1
  local instType, instIdx = 2, 1
  cvtFactor_den = cvtFactor_den * interval
  local vuIdx, CRotatSwFlag = 1, 0
  CVT_SetUserDefineDI(1, 2)
  CVT_Initialization(cvtuIdx, instType, instIdx, srcType, srcIdx,
    cvtFactor_num, cvtFactor_den, interval, cmpstVectorX, cmpstVectorY, cmpstVectorZ, cvtUFIdx,
    trans_ccd_x, trans_ccd_y, rotat_ccd_c, vuIdx, vuPix2UmNum, vuPix2UmDen, vuAgRatioNum, vuAgRatioDen,
    vuXYExchgFlag, CRotatSwFlag, NGZoneRadius, zoneEndLine, robotTrigLine, CV_instSlotIdx)
end

-- =====================  ДВИЖЕНИЕ (только тесты 30..34)  ============
-- Проверка цели. Возвращает текст отказа или nil.
local function guard(p, tx, ty, tz, spd)
  if not p then return "поза не читается (геттер вернул nil) — движение запрещено" end
  if not boot_pose then return "поза при старте не прочиталась — движение запрещено" end
  if not anchor then return "нет якоря — сначала тест 29 (anchor)" end
  if abs(p.r - boot_pose.r) > RZ_TOL then return "RZ ушёл от стартового больше чем на 1°" end
  if abs(tx - anchor.x) > ENVELOPE or abs(ty - anchor.y) > ENVELOPE or abs(tz - anchor.z) > ENVELOPE then
    return "цель дальше 50 мм от якоря"
  end
  if spd < 1 or spd > MAX_SPD then return "скорость вне 1..30 %" end
  return nil
end

local function set_xyz(pt, x, y, z)            -- ×0.1 → мм; 4-ю ось не трогаем
  WritePoint(pt, "X", x / 10); WritePoint(pt, "Y", y / 10); WritePoint(pt, "Z", z / 10)
end

-- Сверка точки перед ходом через ReadPoint (есть по RL 5-9). Нет ReadPoint — nil (сверка
-- невозможна, остаётся правило «RZ как при старте»). Расхождение — текст отказа.
local function verify_point(pt, x, y, z, r)
  if type(ReadPoint) ~= "function" then return nil end
  local want = {X = x / 10, Y = y / 10, Z = z / 10, RZ = r / 10}
  local keys = {"X", "Y", "Z", "RZ"}
  for i = 1, #keys do
    local ok, v = pcall(ReadPoint, pt, keys[i])
    if not ok or type(v) ~= "number" then return "ReadPoint(" .. keys[i] .. ") не читается" end
    if abs(v - want[keys[i]]) > 0.05 then
      return "точка " .. tostring(pt) .. " " .. keys[i] .. "=" .. tostring(v) .. ", ожидалось " .. tostring(want[keys[i]])
    end
  end
  return nil
end

local function begin_move(token)
  PB_stop_seen = false
  PB_last_stop = rd(B.CTRL + 0) or 0            -- стоп, выставленный ДО хода, не считается
  PB_last_ovr  = rd(B.CTRL + 1) or 0
  wr(B.CTRL + 3, 0); wr(B.CTRL + 4, 0); wr(B.CTRL + 5, 0); wr(B.CTRL + 6, 0)
  shared_local, PB_shared_global = token, token
  PB_moving = true
  wr(B.LIVE + 2, 1)
end

local function end_move()
  PB_moving = false
  wr(B.LIVE + 2, 0)
  pcall(Override, 100)
  pcall(DecL, 5000)                             -- вернуть замедление после быстрого стопа
end

-- =====================  ТЕСТЫ  =====================================
-- Каждый тест: function(seq) → status, vals[, text]. Текст уходит в PB_text (тест 3 листает).
local TESTS = {}

TESTS[1] = function()                          -- INFO: версия Lua, библиотеки, базовые функции
  local s = tostring(_VERSION)
  local names = {"os", "io", "bit", "bit32", "string", "table", "math", "coroutine", "debug",
                 "pairs", "ipairs", "next", "error", "select", "unpack", "load", "loadstring",
                 "setfenv", "collectgarbage", "_G"}
  for i = 1, #names do
    local v = resolve(names[i])
    if names[i] == "_G" then v = _G end
    s = s .. "\n" .. names[i] .. "=" .. type(v)
  end
  return ST_OK, {}, s
end

TESTS[2] = function()                          -- GLOBALS: все глобалы + поля таблиц 1 уровня
  if type(pairs) ~= "function" or type(_G) ~= "table" then
    return ST_NOFUNC, {}, "pairs " .. type(pairs) .. ", _G " .. type(_G)
  end
  local lines = {}
  for k, v in pairs(_G) do
    local name = tostring(k)
    lines[#lines + 1] = name .. " " .. type(v)
    if type(v) == "table" and name ~= "_G" and name ~= "package" then
      for k2, v2 in pairs(v) do lines[#lines + 1] = name .. "." .. tostring(k2) .. " " .. type(v2) end
    end
  end
  if type(table) == "table" and type(table.sort) == "function" then table.sort(lines) end
  return ST_OK, {#lines}, join(lines, "\n")
end

TESTS[3] = function()                          -- TEXT_PAGE(page): [длина lo, hi] + 60 байт (30 рег)
  local page = arg(0)
  local chunk = string.sub(PB_text, page * 60 + 1, page * 60 + 60)
  local vals = {}
  push_i32(vals, #PB_text)
  for i = 1, #chunk, 2 do
    local hi = string.byte(chunk, i)
    local lo = string.byte(chunk, i + 1) or 0
    vals[#vals + 1] = s16(hi * 256 + lo)
  end
  return ST_OK, vals, nil
end

TESTS[4] = function()                          -- CALL0(name): вызвать функцию без аргументов
  local name = arg_text(0)
  local f = resolve(name)
  if type(f) ~= "function" then return ST_NOFUNC, {}, name .. ": " .. type(f) end
  local ok, a, b = pcall(f)
  if not ok then return ST_ERR, {}, tostring(a) end
  return ST_OK, {}, tostring(a) .. "|" .. tostring(b)
end

TESTS[5] = function()                          -- CLOCK(n, name): n × DELAY(0.005) между чтениями часов
  local n = arg(0)
  local name = arg_text(1)
  local f = nil
  if name ~= "" then
    f = resolve(name)
    if type(f) ~= "function" then return ST_NOFUNC, {}, name end
  end
  local t0 = f and f() or nil
  for _ = 1, n do DELAY(0.005) end
  local t1 = f and f() or nil
  return ST_OK, {}, tostring(t0) .. "|" .. tostring(t1) .. "|" .. n
end

TESTS[7] = function()                          -- MB_READ(addr): что видит Lua по адресу
  local ok, v = pcall(ReadModbus, arg(0), "W")
  if not ok then return ST_ERR, {}, tostring(v) end
  if v == nil then return ST_NOFUNC, {}, "nil" end
  return ST_OK, {s16(v)}, nil
end

TESTS[8] = function()                          -- MB_WRITE(addr, value): запись из Lua
  local ok, e = pcall(WriteModbus, arg(0), "W", s16(arg(1)))
  if not ok then return ST_ERR, {}, tostring(e) end
  return ST_OK, {}, nil
end

TESTS[9] = function()                          -- MB_MULTI(addr, n, base): блоки из Lua
  local addr, n, base = arg(0), arg(1), arg(2)
  local vals = {}
  for i = 1, n do vals[i] = s16(base + i - 1) end
  local okw, ew = pcall(MultiWriteModbus, addr, n, "W", vals)
  local okr, rr = pcall(MultiReadModbus, addr, n, "W")
  local got = (okr and type(rr) == "table") and #rr or -1
  local match = 0
  if got == n then
    match = 1
    for i = 1, n do if u16(rr[i]) ~= u16(vals[i]) then match = 0 end end
  end
  return ST_OK, {okw and 1 or 0, s16(got), match}, (okw and "" or tostring(ew)) .. "|" .. (okr and "" or tostring(rr))
end

TESTS[10] = function()                         -- DW_ORDER(addr): Lua пишет DW 0x12345678
  local ok, e = pcall(WriteModbus, arg(0), "DW", 305419896)
  if not ok then return ST_ERR, {}, tostring(e) end
  return ST_OK, {}, nil
end

TESTS[11] = function()                         -- ATOMIC_LUA_WRITE(n, cycles): Lua пишет k,k,…,k
  local n, cycles = arg(0), arg(1)
  local vals = {}
  for k = 1, cycles do
    for i = 1, n do vals[i] = s16(k) end
    MultiWriteModbus(B.SCRATCH, n, "W", vals)
  end
  return ST_OK, {}, nil
end

TESTS[12] = function()                         -- ATOMIC_LUA_READ(n, cycles): Lua считает рваные блоки
  local n, cycles = arg(0), arg(1)
  local torn, reads = 0, 0
  for _ = 1, cycles do
    local r = MultiReadModbus(B.SCRATCH, n, "W")
    if type(r) == "table" and #r == n then
      reads = reads + 1
      for i = 2, n do if r[i] ~= r[1] then torn = torn + 1; break end end
    end
  end
  return ST_OK, {s16(reads), s16(torn)}, nil
end

TESTS[13] = function()                         -- AXES: имена пунктов WritePoint, сверка через ReadPoint
  -- Всё на точке 82, которой ничто не движется. «Принято без ошибки» НЕ значит «записано»:
  -- без ReadPoint вывод делать нельзя, поэтому каждое имя сверяется чтением RZ обратно.
  local rp = type(ReadPoint) == "function"
  local out = {"ReadPoint=" .. type(ReadPoint)}
  local tries = {{"X", 301.5, "X"}, {"Y", -211.5, "Y"}, {"Z", -41.5, "Z"},
                 {"RZ", 12.5, "RZ"}, {"R", 23.5, "RZ"}, {"C", 34.5, "RZ"}}
  for i = 1, #tries do
    local name, val, check = tries[i][1], tries[i][2], tries[i][3]
    local ok, e = pcall(WritePoint, "GL_AXTEST", name, val)
    local line = name .. ": " .. (ok and "принято" or ("ошибка " .. tostring(e)))
    if ok and rp then
      local okr, v = pcall(ReadPoint, "GL_AXTEST", check)
      line = line .. ", ReadPoint " .. check .. "=" .. (okr and tostring(v) or "err") ..
             ((okr and type(v) == "number" and abs(v - val) < 0.01) and " → ЗАПИСАНО" or " → не записано")
    end
    out[#out + 1] = line
  end
  return ST_OK, {}, join(out, "\n")
end

TESTS[23] = function()                         -- SETGLOBAL_RUNTIME: SetGlobalPoint на ходу + ReadPoint
  if type(ReadPoint) ~= "function" then return ST_NOFUNC, {}, "ReadPoint " .. type(ReadPoint) end
  local okh, h = pcall(RobotHand)
  local ok, e = pcall(SetGlobalPoint, 82, "GL_AXTEST", 305.5, -215.5, -45.5, 45.5, (okh and h) or 1, 0, 0, POSTURE)
  if not ok then return ST_ERR, {}, tostring(e) end
  local s = ""
  local want = {X = 305.5, Y = -215.5, Z = -45.5, RZ = 45.5}
  local keys = {"X", "Y", "Z", "RZ", "H"}
  local all = true
  for i = 1, #keys do
    local okr, v = pcall(ReadPoint, "GL_AXTEST", keys[i])
    s = s .. keys[i] .. "=" .. (okr and tostring(v) or "err") .. " "
    if want[keys[i]] and not (okr and type(v) == "number" and abs(v - want[keys[i]]) < 0.01) then all = false end
  end
  return ST_OK, {all and 1 or 0}, s
end

TESTS[24] = function()                         -- LOCAL_POINT: есть ли локальная точка 1001 (RL 5-5)
  if type(SetLocalPoint) ~= "function" then return ST_NOFUNC, {}, "SetLocalPoint " .. type(SetLocalPoint) end
  local p = pose() or {x = 3000, y = -2100, z = -400, r = -1000, hand = 1}
  local ok, e = pcall(SetLocalPoint, 1001, p.x / 10, p.y / 10, p.z / 10, p.r / 10, p.hand or 1, 0, 0, POSTURE)
  local back = "ReadPoint нет"
  if ok and type(ReadPoint) == "function" then
    local okr, v = pcall(ReadPoint, 1001, "X")
    back = "ReadPoint X=" .. (okr and tostring(v) or "err")
  end
  return ST_OK, {ok and 1 or 0}, (ok and "SetLocalPoint 1001 принята" or ("ошибка " .. tostring(e))) .. "; " .. back
end

TESTS[22] = function()                         -- RSMASTER: встроенный мастер RS-485 (RL 12-6) к ПЧ
  if type(RSmasterRead) ~= "function" then return ST_NOFUNC, {}, "RSmasterRead " .. type(RSmasterRead) end
  local ok, a, b, c, d = pcall(RSmasterRead, SLAVE, VFD_REG_STATUS, 4)
  if not ok then return ST_ERR, {}, tostring(a) end
  return ST_OK, {s16(a or 0), s16(b or 0), s16(c or 0), s16(d or 0)},
         "RSmasterRead → " .. tostring(a) .. ", " .. tostring(b) .. ", " .. tostring(c) .. ", " .. tostring(d)
end

TESTS[6] = function()                          -- TIMER(n): TimerOn, n × DELAY(0.005), TimerRead (RL 3-4)
  if type(TimerOn) ~= "function" or type(TimerRead) ~= "function" then
    return ST_NOFUNC, {}, "TimerOn " .. type(TimerOn) .. ", TimerRead " .. type(TimerRead)
  end
  local n = arg(0)
  TimerOn()
  local t0 = TimerRead()
  for _ = 1, n do DELAY(0.005) end
  local t1 = TimerRead()
  return ST_OK, {}, tostring(t0) .. "|" .. tostring(t1) .. "|" .. n
end

TESTS[14] = function()                         -- HAND: RobotHand(), поза, скорость ленты
  local p = pose()
  local okb, belt = pcall(CVT_GetCVSpeed, CV)
  local okh, h = pcall(RobotHand)
  local vals = {}
  if p then vals = {s16(p.x), s16(p.y), s16(p.z), s16(p.r)} end
  return ST_OK, vals, "RobotHand=" .. (okh and tostring(h) or ("err " .. tostring(h))) ..
         "\nCVT_GetCVSpeed=" .. (okb and tostring(belt) or ("err " .. tostring(belt))) ..
         "\npose=" .. (p and "ok" or "nil")
end

TESTS[15] = function()                         -- CVT_REINIT: повторная initCVT на ходу программы
  local e0 = CVT_GetEncoderPulseCount(CV)
  local ok, err = pcall(initCVT)
  DELAY(0.2)
  local e1 = CVT_GetEncoderPulseCount(CV)
  local vals = {ok and 1 or 0}
  push_i32(vals, e0 or 0); push_i32(vals, e1 or 0)
  return ST_OK, vals, ok and "" or tostring(err)
end

TESTS[16] = function()                         -- PORT_REOPEN: повторный SCM_FreePort + статус ПЧ
  local ok, rtn = pcall(open_port)
  DELAY(0.1)
  local s = vfd_read(VFD_REG_STATUS, 4)
  local vals = {ok and 1 or 0, s16(ok and rtn or -1), s and 1 or 0}
  if s then for i = 1, 4 do vals[#vals + 1] = s16(s[i]) end end
  return ST_OK, vals, ok and "" or tostring(rtn)
end

TESTS[17] = function()                         -- VFD_READ(addr, qty ≤ 16): регистры ПЧ через мост
  local qty = arg(1)
  if qty < 1 or qty > 16 then return ST_REFUSED, {}, "qty 1..16" end
  local r = vfd_read(arg(0), qty)
  if not r then return ST_ERR, {}, "ПЧ не ответил" end
  local vals = {}
  for i = 1, #r do vals[i] = s16(r[i]) end
  return ST_OK, vals, nil
end

TESTS[18] = function()                         -- VFD_TIMING(n): n чтений статуса подряд
  local okn, failn = 0, 0
  for _ = 1, arg(0) do
    if vfd_read(VFD_REG_STATUS, 4) then okn = okn + 1 else failn = failn + 1 end
  end
  return ST_OK, {s16(okn), s16(failn)}, nil
end

TESTS[19] = function()                         -- DI(1..16): как читаются входы
  if type(DI) ~= "function" then return ST_NOFUNC, {}, "DI " .. type(DI) end
  local parts = {}
  for ch = 1, 16 do
    local ok, v = pcall(DI, ch)
    parts[#parts + 1] = ch .. "=" .. (ok and tostring(v) or "err")
  end
  return ST_OK, {}, join(parts, " ")
end

TESTS[20] = function()                         -- SERVO(on)
  if arg(0) == 1 then RobotServoOn() else RobotServoOff() end
  return ST_OK, {}, nil
end

TESTS[21] = function()                         -- SETTERS: режимы движения, которые нужны v2
  local checks = {
    {"Accur HIGH", Accur, "HIGH"}, {"Accur ROUGH", Accur, "ROUGH"},
    {"PassMode", PassMode, "DISTANT", "PLON"}, {"SetOverlapDistance", SetOverlapDistance, 0.5},
    {"SpdL", SpdL, 500}, {"AccL", AccL, 5000}, {"DecL", DecL, 5000},
    {"SpdJ", SpdJ, 30}, {"AccJ", AccJ, 50}, {"DecJ", DecJ, 50}, {"Override", Override, 100},
  }
  local parts = {}
  for i = 1, #checks do
    local c = checks[i]
    local ok, e = false, "нет функции"
    if type(c[2]) == "function" then ok, e = pcall(c[2], c[3], c[4]) end
    parts[#parts + 1] = c[1] .. "=" .. (ok and "ok" or ("err " .. tostring(e)))
  end
  return ST_OK, {}, join(parts, "\n")
end

TESTS[29] = function()                         -- ANCHOR: текущая поза = центр оболочки ±50 мм
  local p = pose()
  if not p then return ST_REFUSED, {}, "поза не читается — якорь не поставлен" end
  if not boot_pose then return ST_REFUSED, {}, "поза при старте не прочиталась" end
  if abs(p.r - boot_pose.r) > RZ_TOL then return ST_REFUSED, {}, "RZ ушёл от стартового — вернись в стартовую ориентацию" end
  anchor = {x = p.x, y = p.y, z = p.z}
  return ST_OK, {s16(p.x), s16(p.y), s16(p.z), s16(p.r)}, nil
end

TESTS[30] = function(seq)                      -- MOVE_REL(dx, dy, dz, spd): MovL на смещение
  local dx, dy, dz, spd = sarg(0), sarg(1), sarg(2), arg(3)
  local p = pose()
  local why = guard(p, (p and p.x or 0) + dx, (p and p.y or 0) + dy, (p and p.z or 0) + dz, spd)
  if why then return ST_REFUSED, {}, why end
  set_xyz(PT_NAME, p.x + dx, p.y + dy, p.z + dz)
  local bad = verify_point(PT_NAME, p.x + dx, p.y + dy, p.z + dz, p.r)
  if bad then return ST_REFUSED, {}, bad end
  Override(spd)
  begin_move(seq % 30000 + 1)
  local ok, err = pcall(function() MovL(PT_NAME) end)
  end_move()
  local f = pose() or {x = 0, y = 0, z = 0, r = 0}
  local fast = (PB_fast_ok == nil) and 0 or (PB_fast_ok and 1 or 2)
  PB_fast_ok = nil
  return ST_OK, {ok and 1 or 0, PB_stop_seen and 1 or 0, s16(f.x), s16(f.y), s16(f.z), s16(f.r), fast},
         ok and "" or tostring(err)
end

TESTS[31] = function(seq)                      -- PASS_CHAIN(n, step, spd, mode): зигзаг по X туда-обратно
  -- mode 0: без записей Modbus · 1: Mirror публикует позу · 2: Motion пишет между точками
  local n, step, spd, mode = arg(0), sarg(1), arg(2), arg(3)
  if n < 4 or n > POOL_N or n % 2 == 1 then return ST_REFUSED, {}, "n чётное 4..40" end
  local p = pose()
  local why = guard(p, (p and p.x or 0) + step * n / 2, p and p.y or 0, p and p.z or 0, spd)
  if why then return ST_REFUSED, {}, why end
  local half = n / 2
  for i = 1, n do
    local k = (i <= half) and i or (n - i)
    set_xyz(POOL_BASE + i, p.x + step * k, p.y, p.z)
    local bad = verify_point(POOL_BASE + i, p.x + step * k, p.y, p.z, p.r)
    if bad then return ST_REFUSED, {}, bad end
  end
  wr(B.CTRL + 2, (mode == 1) and 1 or 0)
  PassMode("DISTANT", "PLON")
  SetOverlapDistance(0.5)
  Override(spd)
  begin_move(seq % 30000 + 1)
  local done = 0
  local ok, err = pcall(function()
    for i = 1, n do
      if PB_stop_seen then return end          -- стоп прерывает цепочку (MovL+PASS возвращается сразу)
      if mode == 2 then wr(B.SCRATCH, i) end
      if i < n then MovL(POOL_BASE + i, PASS()) else MovL(POOL_BASE + i) end
      done = i
    end
  end)
  end_move()
  wr(B.CTRL + 2, 0)
  -- Цепочка «туда-обратно» кончается в старте: остановка вдали от старта = стоп прервал очередь
  -- PASS-ходов. Счётчик done этого не показывает: MovL+PASS возвращается до конца хода.
  local f = pose() or p
  return ST_OK, {ok and 1 or 0, PB_stop_seen and 1 or 0, done, s16(f.x - p.x)}, ok and "" or tostring(err)
end

TESTS[32] = function(seq)                      -- UNWIND: error(таблица) после хода внутри pcall
  if type(error) ~= "function" then return ST_NOFUNC, {}, "error " .. type(error) end
  local p = pose()
  local why = guard(p, (p and p.x or 0) + 20, p and p.y or 0, p and p.z or 0, 10)
  if why then return ST_REFUSED, {}, why end
  local MARK = {}
  Override(10)
  begin_move(seq % 30000 + 1)
  set_xyz(PT_NAME, p.x + 20, p.y, p.z)
  local bad = verify_point(PT_NAME, p.x + 20, p.y, p.z, p.r)
  if bad then end_move(); return ST_REFUSED, {}, bad end
  local ok, err = pcall(function() MovL(PT_NAME); error(MARK) end)
  local caught = (not ok) and (err == MARK)
  set_xyz(PT_NAME, p.x, p.y, p.z)
  local bad2 = verify_point(PT_NAME, p.x, p.y, p.z, p.r)
  local ok2, err2 = false, bad2
  if not bad2 then ok2, err2 = pcall(function() MovL(PT_NAME) end) end
  end_move()
  return ST_OK, {caught and 1 or 0, ok2 and 1 or 0}, ok2 and "" or tostring(err2)
end

-- Поворот RZ на +5° и обратно; способ задания 4-й оси — параметр. Возвращает dRZ ×0.1.
-- Поворот RZ на +5° и обратно; способ задания 4-й оси — параметр apply(p, rz_град).
-- Точка сверяется через ReadPoint и перед ходом вперёд, и перед возвратом: «принятая, но не
-- записанная» координата иначе увела бы робота из оболочки (ревью 2026-09-27, итерация 2).
local function rotate_test(seq, apply)
  local p = pose()
  local why = guard(p, p and p.x or 0, p and p.y or 0, p and p.z or 0, 5)
  if why then return ST_REFUSED, {}, why end
  set_xyz(PT_NAME, p.x, p.y, p.z)
  local ok, err = pcall(apply, p, (p.r + ROT_STEP) / 10)
  if not ok then return ST_ERR, {}, "задание оси: " .. tostring(err) end
  local bad = verify_point(PT_NAME, p.x, p.y, p.z, p.r + ROT_STEP)
  if bad then
    pcall(apply, p, p.r / 10)                    -- вернуть точку, робот не двигался
    return ST_REFUSED, {}, "до хода: " .. bad
  end
  Override(5)
  begin_move(seq % 30000 + 1)
  local okm, errm = pcall(function() MovL(PT_NAME) end)
  local mid = pose() or {x = 0, y = 0, z = 0, r = 0}
  local okb = pcall(apply, p, p.r / 10)
  local bad2 = "точка возврата не задана"      -- не «a and f() or b»: f() == nil значит «сверка прошла»
  if okb then bad2 = verify_point(PT_NAME, p.x, p.y, p.z, p.r) end
  local okm2 = false
  if not bad2 then okm2 = pcall(function() MovL(PT_NAME) end) end
  end_move()
  local f = pose() or {x = 0, y = 0, z = 0, r = 0}
  local text = okm and "" or tostring(errm)
  if bad2 then text = text .. " возврат НЕ выполнен: " .. bad2 end
  return ST_OK, {okm and 1 or 0, s16(mid.r - p.r), s16(mid.x - p.x), s16(mid.y - p.y), s16(mid.z - p.z),
                 okm2 and 1 or 0, s16(f.r - p.r)}, text
end

TESTS[33] = function(seq)                      -- ROT_SETGLOBAL: RZ через SetGlobalPoint на ходу программы
  return rotate_test(seq, function(p, r)
    SetGlobalPoint(PT_ID, PT_NAME, p.x / 10, p.y / 10, p.z / 10, r, boot_pose.hand or 1, 0, 0, POSTURE)
  end)
end

TESTS[34] = function(seq)                      -- ROT_WRITEPOINT(name): RZ через WritePoint(имя оси)
  local name = arg_text(0)
  if name ~= "RZ" and name ~= "R" then return ST_REFUSED, {}, "только RZ или R" end
  return rotate_test(seq, function(_, r) WritePoint(PT_NAME, name, r) end)
end

-- =====================  ЦИКЛ ПРОБЫ  ================================
local function publish_live()
  hb_motion = (hb_motion + 1) % 32768
  local p = pose()
  local enc = CVT_GetEncoderPulseCount(CV) or 0
  local vals = {hb_motion, s16(PB_hb_mirror), PB_moving and 1 or 0}
  if p then
    vals[4], vals[5], vals[6], vals[7] = s16(p.x), s16(p.y), s16(p.z), s16(p.r)
    vals[8] = s16(p.hand or -1)
  else
    vals[4], vals[5], vals[6], vals[7], vals[8] = 0, 0, 0, 0, -1
  end
  push_i32(vals, enc)
  MultiWriteModbus(B.LIVE, #vals, "W", vals)
  wr(B.LIVE + 13, p and 1 or 0)
end

local function answer(seq, status, vals)
  vals = vals or {}
  local n = #vals
  if n > B.VAL_N then n = B.VAL_N end
  if n > 0 then MultiWriteModbus(B.VAL0, n, "W", vals) end
  wr(B.RES_N, n)
  wr(B.RES_STATUS, status)
  wr(B.RES_SEQ, seq)                             -- маркер ответа — последним
end

function probe_step()                          -- одна итерация Motion (зовётся и из сухого прогона)
  publish_live()
  if rd(B.CMD_FLAG) ~= 1 then return end
  local seq, test = rd(B.CMD_SEQ) or 0, rd(B.CMD_TEST) or 0
  wr(B.CMD_FLAG, 0)
  if seq == last_seq then return end            -- повтор запроса без повторного исполнения
  last_seq = seq
  wr(B.LIVE + 11, test)
  local fn = TESTS[test]
  if not fn then answer(seq, ST_NOTEST); return end
  local ok, status, vals, text = pcall(fn, seq)
  if not ok then
    PB_text = tostring(status)
    answer(seq, ST_ERR)
    return
  end
  if text ~= nil then PB_text = text end
  answer(seq, status, vals)
end

function Motion()
  while true do
    local ok, err = pcall(probe_step)
    if not ok then print("probe: " .. tostring(err)) end
    DELAY(0.005)
  end
end

-- Mirror (function2): ⚠️ без while/WAIT/DELAY. Считает свои тики всегда — так видно,
-- крутится ли она в простое; во время хода отрабатывает стоп и Override с ПК.
function Mirror()
  local ok, err = pcall(function()
    PB_hb_mirror = (PB_hb_mirror + 1) % 32768
    wr(B.LIVE + 1, PB_hb_mirror)
    if not PB_moving then return end
    wr(B.CTRL + 5, shared_local)
    wr(B.CTRL + 6, PB_shared_global)
    if rd(B.CTRL + 2) == 1 then
      local p = pose()
      if p then MultiWriteModbus(B.LIVE + 3, 4, "W", {s16(p.x), s16(p.y), s16(p.z), s16(p.r)}) end
    end
    local sv = rd(B.CTRL + 0) or 0
    if sv ~= PB_last_stop and not PB_stop_seen then
      if rd(B.CTRL + 7) == 1 then PB_fast_ok = pcall(DecL, 25000) end   -- максимум по RL 2-8
      MotionStop()
      PB_stop_seen = true
      wr(B.CTRL + 3, PB_hb_mirror)
    end
    local ov = rd(B.CTRL + 1) or 0
    if ov ~= PB_last_ovr and ov >= 1 then
      PB_last_ovr = ov
      if ov > MAX_SPD then
        wr(B.CTRL + 4, 3)
      else
        local okv = pcall(Override, ov)
        wr(B.CTRL + 4, okv and 1 or 2)
      end
    end
  end)
  if not ok then
    PB_mirror_err = (PB_mirror_err + 1) % 32768
    wr(B.LIVE + 10, PB_mirror_err)
    PB_text = "Mirror: " .. tostring(err)
  end
end

-- =====================  СТАРТ  =====================================
local rtn = open_port()
print("probe: SCM_FreePort rtn = " .. tostring(rtn))
DELAY(0.1)
local vfd_stopped = false
for _ = 1, 3 do                                   -- лента стоит, пока идёт проба
  if vfd_write(VFD_REG_CMD, CMD_STOP) then vfd_stopped = true; break end
  DELAY(0.05)
end
print("probe: СТОП ПЧ " .. (vfd_stopped and "подтверждён" or "НЕ подтверждён — проверь ленту"))
initCVT()
-- консервативные скорости: процент Override считается от них
pcall(SpdL, 500); pcall(AccL, 5000); pcall(DecL, 5000)
pcall(SpdJ, 30); pcall(AccJ, 50); pcall(DecJ, 50)

boot_pose = pose()
local bp = boot_pose or {x = 3000, y = -2100, z = -400, r = -1000, hand = 1}
local hand = bp.hand or 1
SetGlobalPoint(PT_ID, PT_NAME, bp.x / 10, bp.y / 10, bp.z / 10, bp.r / 10, hand, 0, 0, POSTURE)
SetGlobalPoint(82, "GL_AXTEST", bp.x / 10, bp.y / 10, bp.z / 10, bp.r / 10, hand, 0, 0, POSTURE)
for i = 1, POOL_N do
  SetGlobalPoint(POOL_BASE + i, "GL_PB" .. i, bp.x / 10, bp.y / 10, bp.z / 10, bp.r / 10, hand, 0, 0, POSTURE)
end
for a = B.CMD_FLAG, B.CTRL + 7 do wr(a, 0) end
wr(B.LIVE + 12, vfd_stopped and 1 or 2)
print("probe: готова, поза при старте " .. (boot_pose and "прочитана" or "НЕ прочитана (движение запрещено)") ..
      ", ждёт команд pc_probe.py (канал 0x1400)")
MultiTask(Motion, Mirror)
