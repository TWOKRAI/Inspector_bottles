-- =====================================================================
--  Delta SCARA · DRAStudio (Lua/RL) — ПОЛНАЯ: CVT pick-place + РИСОВАНИЕ
--
--  Одна программа, ПЯТЬ режимов (переключатель REG_MODE 0x1109):
--    MODE=0 (CVT)    — конвейерный pick-place + ПЧ + телеметрия + параметры + стоп + зона
--                      (= cvt_universal_mt.lua дословно).
--    MODE=1 (DRAW)   — плоттер: пачка точек → плавный проход MovL(PASS) по ПУЛУ distinct-точек,
--                      перо по Z (= draw.lua).
--    MODE=2 (MANUAL) — ручной jog по Modbus: ПК задаёт смещение dX/dY (0.1 мм) и скорость (%),
--                      флаг REG_MAN_FLAG 0x1340 запускает один линейный ход MovL на месте.
--                      Относительный (jog) или абсолютный (ехать в координату) — REG_MAN_ABS.
--                      Стоп — REG_MAN_ABORT/REG_STOP. Z/RZ не меняются (движение в плоскости).
--                      Удобно для наведения робота по точкам калибровки.
--    MODE=3 (RETURN) — возврат буквы на ленту: ПК шлёт координату СЛОТА (REG_RET_X/Y/Z) +
--                      флаг REG_RET_FLAG 0x1350. Робот линейными MovL берёт диск из слота
--                      (DO-захват), поднимает +RET_LIFT по Z, сдвигает +RET_PUSH по X к ленте,
--                      опускает −RET_LIFT, отпускает (диск на ленту), едет домой.
--                      Handshake как у DRAW: flag→0 (приём), REG_RET_BUSY 1→0 (готово).
--    MODE=4 (TOOLCHANGE) — смена инструмента: ПК пишет целевой инструмент REG_TOOL_TARGET
--                      (0 = снять / 1 / 2) + флаг REG_TOOL_FLAG 0x1360. Робот линейными MovL
--                      возвращает текущий инструмент в гнездо и надевает целевой. Маршрут по
--                      обученным точкам over/sock/exit; инструмент 2 ВСЕГДА проходится через
--                      "над 1". Handshake: flag→0 (приём), REG_TOOL_BUSY 1→0 (готово).
--
--  Планировщик MultiTask(Motion, Mirror): Motion (function1) — главный цикл, ветвится по
--  режиму; Mirror (function2) — параллельно во время хода (свежий энкодер/живая поза + стоп).
--  ⚠️ Mirror без while/WAIT/DELAY (требование MultiTask).
--
--  Обычный MovL работает и в CVT-режиме (CVT_ChangeMotion) — подтверждено стартовым
--  MovP("GL_HOME") во всех рабочих CVT-файлах. Поэтому рисование плоскими MovL корректно.
--
--  Переключай режим ТОЛЬКО когда робот свободен. ПК: pc_full.py.
-- =====================================================================

-- =====================  КАРТА РЕГИСТРОВ  ============================
-- ── общее ──
REG_MODE = 0x1109        -- W  : РЕЖИМ. 0 = CVT pick-place, 1 = рисование
-- ── CVT: задание ──
REG_FLAG = 0x1100        -- W  : 1 = задание готово (ПК), 0 = принято (робот)
REG_X    = 0x1101        -- W  : X в 0.1 мм
REG_Y    = 0x1102        -- W  : Y в 0.1 мм
REG_Z    = 0x1103        -- W  : Z захвата (глубина опускания на picke), 0.1 мм; 0 = Z_PICK по умолч.
REG_ECAP = 0x1104        -- DW : E_capture — энкодер в момент кадра (чётный!)
-- ── CVT: поза УКЛАДКИ x/y/z/r (доворот). Забор остаётся по REG_X/REG_Y (трекинг). ──
REG_PLACE_X    = 0x1140  -- W  : X укладки, 0.1 мм
REG_PLACE_Y    = 0x1141  -- W  : Y укладки, 0.1 мм
REG_PLACE_Z    = 0x1142  -- W  : Z укладки, 0.1 мм
REG_PLACE_RZ   = 0x1143  -- W  : доворот, 0.1° (R = R_BASE + place_rz)
REG_PLACE_FLAG = 0x1144  -- W  : 1 = класть в place_x/y/z с доворотом; 0 = фикс. GL_PLACE
REG_STOP = 0x1106        -- W  : СТОП. 0=нет | 1=домой+продолжить | 2=домой+выход+серво OFF | 3=на месте+выход+серво ON
REG_SERVO = 0x1108       -- W  : серво (одноразовая). 0=нет | 1=включить | 2=выключить
REG_FREE = 0x1110        -- W  : 1 = робот свободен, 0 = занят
REG_ENC  = 0x1112        -- DW : живой энкодер (зеркалим — ПК читает как E_capture)
REG_ECHO_X = 0x1120
REG_ECHO_Y = 0x1121
REG_PX     = 0x1122
REG_PY     = 0x1123
REG_TRAV   = 0x1124
-- ── VFD ──
REG_CMD_RUN   = 0x1200
REG_CMD_DIR   = 0x1201
REG_CMD_FREQ  = 0x1202
REG_CMD_RESET = 0x1203
REG_VFD_FLAG  = 0x1204
REG_ST_BASE   = 0x1210
local ST_BLOCK_CNT  = 8
-- ── телеметрия (X/Y живые — общие для обоих режимов) ──
REG_TLM_BASE = 0x1130
local TLM_CNT      = 11
local TLM_EVERY    = 5
-- ── параметры (CFG) ──
REG_CFG_FLAG = 0x1300
REG_CFG_BASE = 0x1301
local CFG_CNT      = 11
-- ── РИСОВАНИЕ: управление ──
REG_DRAW_FLAG  = 0x1400  -- W  : 1 = старт
REG_DRAW_TYPE  = 0x1401  -- W  : 0 = полилиния (буфер точек), 1 = круг (MCircle)
REG_DRAW_COUNT = 0x1402  -- W  : число точек (полилиния)
REG_DRAW_BUSY  = 0x1403  -- W  : робот 1=рисует/0=свободен
REG_DRAW_PROG  = 0x1404  -- W  : текущий индекс точки
REG_DRAW_ABORT = 0x1405  -- W  : 1 = стоп рисования
REG_CIRC_CX    = 0x1406  -- W  : круг — центр X ×10
REG_CIRC_CY    = 0x1407  -- W  : круг — центр Y ×10
REG_CIRC_R     = 0x1408  -- W  : круг — радиус ×10
REG_DRAW_DONE_N = 0x1409 -- W  : эхо — сколько точек проход РЕАЛЬНО выполнил (read-back ACK для ПК).
                         --       Пишется ПОСТ-усечённый count (см. execute_path: при коротком
                         --       чтении буфера count молча уменьшается). НЕ обнуляется в конце
                         --       прохода (в отличие от PROG) — ПК сверяет с размером пачки.
-- ── РИСОВАНИЕ: конфиг (ПК пишет напрямую) ──
REG_PEN_DOWN = 0x1410    -- W  : Z рисования, 0.1 мм
REG_PEN_UP   = 0x1411    -- W  : Z переезда, 0.1 мм
REG_DRAW_SPD = 0x1412    -- W  : скорость %, 1..100
REG_OVERLAP  = 0x1413    -- W  : SetOverlapDistance, 0.1 мм
REG_DRAW_HOME = 0x1414   -- W  : 1 = после прохода ехать домой (последний проход рисунка); 0 = ждать на месте
REG_DRAW_TRAVEL = 0x1415 -- W  : скорость ПЕРЕЕЗДА с поднятым пером, % 1..100 (live из пульта)
-- ── РИСОВАНИЕ: буфер точек (PTS_MAX слотов × 3 рег: X, Y, pen) ──
REG_PTS_BASE = 0x1420
local PTS_MAX      = 100
local POOL_BASE    = 100        -- id точек пула = POOL_BASE+1..POOL_BASE+PTS_MAX (101..200)
-- ⚠️ АДРЕСА КОМАНДНЫХ БЛОКОВ — в свободной дыре 0x1340..0x13FF (между CONFIG 0x130B и DRAW
--    0x1400), НИЖЕ буфера точек рисования 0x1420..0x154B. Раньше MAN/RET/TOOL стояли на
--    0x1500/0x1510/0x1520 — ВНУТРИ буфера: рисунок ≥76 точек затирал эти регистры (режимы
--    конфликтовали по адресам). Теперь каждый режим — свой непересекающийся блок.
-- ── MANUAL: ручной jog по Modbus (0x1340..0x1346) ──
REG_MAN_FLAG  = 0x1340    -- W  : 1 = команда хода готова (ПК), 0 = принято/выполнено (робот)
REG_MAN_DX    = 0x1341    -- W  : смещение X, 0.1 мм (знаковое; абс. — целевой X при REG_MAN_ABS=1)
REG_MAN_DY    = 0x1342    -- W  : смещение Y, 0.1 мм (знаковое; абс. — целевой Y при REG_MAN_ABS=1)
REG_MAN_SPD   = 0x1343    -- W  : скорость %, 1..100
REG_MAN_BUSY  = 0x1344    -- W  : 1 = движется, 0 = свободен
REG_MAN_ABORT = 0x1345    -- W  : 1 = стоп ручного хода
REG_MAN_ABS   = 0x1346    -- W  : 0 = относительно (jog на dX/dY), 1 = абсолют (ехать в X=dX, Y=dY)
-- ── RETURN: возврат буквы на ленту (mode=3) (0x1350..0x1354) ──
REG_RET_FLAG = 0x1350     -- W  : 1 = задание возврата готово (ПК), 0 = принято/выполнено (робот)
REG_RET_X    = 0x1351     -- W  : X слота (откуда забрать), 0.1 мм
REG_RET_Y    = 0x1352     -- W  : Y слота (откуда забрать), 0.1 мм
REG_RET_Z    = 0x1353     -- W  : Z слота (высота захвата), 0.1 мм
REG_RET_BUSY = 0x1354     -- W  : 1 = выполняет возврат, 0 = свободен (handshake как у рисования)
-- ── TOOLCHANGE: смена инструмента (mode=4) (0x1360..0x1363) ──
REG_TOOL_FLAG   = 0x1360  -- W  : 1 = команда смены готова (ПК), 0 = принято/выполнено (робот)
REG_TOOL_TARGET = 0x1361  -- W  : целевой инструмент: 0 = снять, 1 = инструмент 1, 2 = инструмент 2
REG_TOOL_BUSY   = 0x1362  -- W  : 1 = выполняет смену, 0 = свободен (handshake как у RETURN)
REG_TOOL_CUR    = 0x1363  -- W  : текущий установленный инструмент (зеркало для ПК)

-- =====================  ГЕОМЕТРИЯ / ТОЧКИ  ========================
CV        = 1
FACTOR_MM = 0.144473
UX, UY    = 0, 1
XY_SCALE  = 10.0

local Z_PICK   = -100
local R_BASE   = -100   -- фикс. R (4-я ось) при заборе/доме (= 4-я координата GL_*); укладка = R_BASE + доворот
local SPD_MOVE = 80     -- скорость перемещений % (было 60 — подними/опусти под «через секунду»)
local GRIP_S   = 0.4    -- дожим присоски/отпускания, сек (было 2 — главная «долго»; присоска быстрая)
local DO_GRIP  = 1
local POSTURE  = {0,0,0,0,0,0,0,4}
-- CVT-точки (id 80/90/91 — вне пула рисования 101..200):
SetGlobalPoint(90, "GL_HOME",  300, -210, -40,    -100, 1, 0, 0, POSTURE)
SetGlobalPoint(91, "GL_PLACE", 450, -300, -90,    -100, 1, 0, 0, POSTURE)
SetGlobalPoint(80, "GL_PICK",  300, -210, Z_PICK, -100, 1, 0, 0, POSTURE)
SetGlobalPoint(81, "GL_MAN",   300, -210, -40,    -100, 1, 0, 0, POSTURE)  -- скретч-точка ручного хода (MANUAL)
SetGlobalPoint(82, "GL_RET",   300, -210, -40,    -100, 1, 0, 0, POSTURE)  -- скретч-точка возврата (RETURN)

-- дефолты рисования:
local PEN_DOWN0 = -100
local PEN_UP0   = -90
local DRAW_SPD0 = 30
local TRAVEL_SPD0 = 100  -- скорость переезда с ПОДНЯТЫМ пером (%), макс → минимум пауз между штрихами
local OVERLAP0  = 0.5
local DRAW_LIFT_MM = 10.0   -- подъём вертикально перед заездом домой в конце рисунка, мм (1 см)
-- возврат на ленту (RETURN, mode=3): смещения траектории — КОНСТАНТЫ (ТЗ владельца).
local RET_LIFT_MM = 20.0    -- подъём/опускание по Z (вверх над слотом, вниз к ленте), мм
local RET_PUSH_MM = 100.0   -- сдвиг по X к ленте, мм (знак подобрать на железе — куда лента)

-- =====================  RS-485 / ПРИВОД  ==========================
local PORT, SLAVE    = 1, 1
local VFD_REG_CMD    = 0x2000
local VFD_REG_FREQ   = 0x2001
local CMD_FWD_RUN    = 0x0001
local CMD_REV_RUN    = 0x0002
local CMD_STOP       = 0x0005
local CMD_FAULT_RST  = 0x0007
local VFD_REG_STATUS = 0x2100
local VFD_STAT_CNT   = 4
local VFD_REG_MON    = 0x3000
local VFD_MON_CNT    = 5
local STAT_FWD, STAT_REV = 1, 2
local RS485_RATE     = 0x2
local RS485_PROTOCOL = 0xD
local RS485_MODE     = 0x11
local RX_TRIES       = 8

-- =====================  СОСТОЯНИЕ (глобалы)  ======================
mode            = 0            -- 0 CVT / 1 DRAW (читается из REG_MODE)
have_job        = false
job_x, job_y, job_enc = 0, 0, 0
job_z           = 0            -- глубина захвата на picke (0 = Z_PICK по умолчанию)
job_place_x, job_place_y, job_place_z, job_place_rz, job_place_fl = 0, 0, 0, 0, 0
heartbeat       = 0
comm_errors     = 0
robot_hb        = 0
tlm_tick        = 0
stop_mode       = 0
tracking_active = false
motion_stopped  = false
running         = true
exit_servo_off  = false
servo_on        = true
zone_max        = 500
zone_min        = 120
miss_count      = 0
zone_tripped    = false
draw_abort      = false        -- запрос стопа рисования
manual_abort    = false        -- запрос стопа ручного хода (MANUAL)
instrument      = 0            -- текущий установленный инструмент: 0 нет / 1 / 2 (смена, mode=4)

-- =====================  МЕЛКИЕ ХЕЛПЕРЫ  ===========================
-- (v or 0): nil-guard. iround/clampW зовутся отовсюду (телеметрия, зона, job);
-- nil-операнд давал "attempt to compare nil with number" → краш задачи MultiTask.
local function iround(v) return math.floor((v or 0) + 0.5) end

local function clampW(v)
  v = iround(v)
  if v >  32767 then return  32767 end
  if v < -32767 then return -32767 end
  return v
end

local function mirror_encoder()
  local enc = CVT_GetEncoderPulseCount(CV)
  if enc then WriteModbus(REG_ENC, "DW", enc) end
end

local function poll_stop()
  local sm = ReadModbus(REG_STOP, "W")
  if sm == 1 or sm == 2 or sm == 3 then return sm end
  return 0
end

local function obj_out_of_zone(x, y)
  if not x or not y then return false end          -- nil-guard (только CVT-зона; DRAW не зовёт)
  local r2 = x * x + y * y
  return (zone_max > 0 and r2 > zone_max * zone_max)
      or (zone_min > 0 and r2 < zone_min * zone_min)
end

-- живая поза X/Y → телеметрия (оба режима, в т.ч. в движении)
local function publish_pose()
  WriteModbus(REG_TLM_BASE + 0, "W", clampW((RobotX() or 0) * XY_SCALE))
  WriteModbus(REG_TLM_BASE + 1, "W", clampW((RobotY() or 0) * XY_SCALE))
end

-- =====================  ИНИЦИАЛИЗАЦИЯ CVT  ========================
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

-- =====================  RS-485 RTU (Free Port)  ===================
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

local function frame_crc_ok(buf, i, n)
  local sub = string.sub(buf, i, i + n - 1)
  local c = crc16(sub)
  return string.byte(buf, i + n) == (c % 256)
     and string.byte(buf, i + n + 1) == math.floor(c / 256)
end

local function mb_read(addr, qty)
  local req = with_crc(string.char(
    SLAVE, 0x03, math.floor(addr / 256), addr % 256,
    math.floor(qty / 256), qty % 256))
  local buf = txn(req, 5 + 2 * qty)
  for i = 1, #buf - 1 do
    local a, f = string.byte(buf, i), string.byte(buf, i + 1)
    if a == SLAVE and f == 0x03 then
      local bc = string.byte(buf, i + 2)
      if bc == 2 * qty and #buf >= i + 4 + bc and frame_crc_ok(buf, i, 3 + bc) then
        local out = {}
        for k = 0, qty - 1 do
          out[#out + 1] = string.byte(buf, i + 3 + 2 * k) * 256
                        + string.byte(buf, i + 4 + 2 * k)
        end
        return out
      end
    elseif a == SLAVE and f == 0x83 then
      return nil
    end
  end
  return nil
end

local function mb_write(addr, value)
  local req = with_crc(string.char(
    SLAVE, 0x06, math.floor(addr / 256), addr % 256,
    math.floor(value / 256), value % 256))
  local buf = txn(req, 8)
  for i = 1, #buf - 1 do
    if string.byte(buf, i) == SLAVE and string.byte(buf, i + 1) == 0x06 then return true end
  end
  return false
end

-- =====================  VFD  ======================================
local last_cmd, last_freq = nil, nil

local function desired_cmd(run, dir)
  if not run then return CMD_STOP end
  if dir == 1 then return CMD_REV_RUN end
  return CMD_FWD_RUN
end

local function vfd_poll_publish()
  local s = mb_read(VFD_REG_STATUS, VFD_STAT_CNT)
  local m = s and mb_read(VFD_REG_MON, VFD_MON_CNT) or nil
  if not s or not m then
    comm_errors = (comm_errors + 1) % 32767
    WriteModbus(REG_ST_BASE + 7, "W", comm_errors)
    return
  end
  local state = s[1]
  heartbeat = (heartbeat + 1) % 32767
  MultiWriteModbus(REG_ST_BASE, ST_BLOCK_CNT, "W", {
    (state == STAT_FWD or state == STAT_REV) and 1 or 0,
    m[1], m[5], m[3], s[4], state, heartbeat, comm_errors,
  })
end

local function handle_vfd()
  local run   = ReadModbus(REG_CMD_RUN,   "W") == 1
  local dir   = ReadModbus(REG_CMD_DIR,   "W")
  local freq  = ReadModbus(REG_CMD_FREQ,  "W")
  local reset = ReadModbus(REG_CMD_RESET, "W")
  if reset == 1 then
    mb_write(VFD_REG_CMD, CMD_FAULT_RST); DELAY(0.05)
    WriteModbus(REG_CMD_RESET, "W", 0)
    last_cmd, last_freq = nil, nil
  end
  if freq ~= nil and freq ~= last_freq then        -- nil-guard: транзиентный nil на шине не льём в mb_write
    if mb_write(VFD_REG_FREQ, freq) then last_freq = freq end
  end
  local want = desired_cmd(run, dir)
  if want ~= last_cmd then
    if mb_write(VFD_REG_CMD, want) then last_cmd = want end
  end
  vfd_poll_publish()
end

-- =====================  ТЕЛЕМЕТРИЯ  ===============================
local function publish_telemetry()
  tlm_tick = tlm_tick + 1
  if tlm_tick < TLM_EVERY then return end
  tlm_tick = 0
  local x  = RobotX()  or 0
  local y  = RobotY()  or 0
  local z  = RobotZ()  or 0
  local rz = RobotRZ() or 0
  local belt = CVT_GetCVSpeed(CV) or 0
  if belt < 0 then belt = 0 end
  local hand = RobotHand() or 0
  robot_hb = (robot_hb + 1) % 32767
  MultiWriteModbus(REG_TLM_BASE, TLM_CNT, "W", {
    clampW(x * XY_SCALE), clampW(y * XY_SCALE), clampW(z * XY_SCALE), clampW(rz * XY_SCALE),
    have_job and 1 or 0, SPD_MOVE, clampW(belt), hand, robot_hb,
    servo_on and 1 or 0, miss_count,
  })
end

-- =====================  ПАРАМЕТРЫ ОТ ПК  ==========================
local function handle_config()
  local c = MultiReadModbus(REG_CFG_BASE, CFG_CNT, "W")
  if not c or #c < CFG_CNT then return end
  local spd = c[1]
  local hx, hy, hz = c[2] / XY_SCALE, c[3] / XY_SCALE, c[4] / XY_SCALE
  local pz = c[5] / XY_SCALE
  local qx, qy, qz = c[6] / XY_SCALE, c[7] / XY_SCALE, c[8] / XY_SCALE
  local grip_ms = c[9]
  local zmax = c[10] / XY_SCALE
  local zmin = c[11] / XY_SCALE
  if spd >= 1 and spd <= 100 then SPD_MOVE = spd; Override(spd) end
  WritePoint("GL_HOME",  "X", hx); WritePoint("GL_HOME",  "Y", hy); WritePoint("GL_HOME",  "Z", hz)
  Z_PICK = pz; WritePoint("GL_PICK", "Z", pz)
  WritePoint("GL_PLACE", "X", qx); WritePoint("GL_PLACE", "Y", qy); WritePoint("GL_PLACE", "Z", qz)
  if grip_ms >= 0 then GRIP_S = grip_ms / 1000.0 end
  if zmax >= 0 then zone_max = zmax end
  if zmin >= 0 then zone_min = zmin end
  print("CFG: SPD=" .. SPD_MOVE .. " HOME=" .. hx .. "," .. hy .. "," .. hz ..
        " PICKZ=" .. Z_PICK .. " PLACE=" .. qx .. "," .. qy .. "," .. qz ..
        " GRIP=" .. GRIP_S .. " ZONE=" .. zone_min .. ".." .. zone_max)
end

-- =====================  СТОП / MISS (CVT)  ========================
local function handle_stop()
  if tracking_active then CVT_VelOut(CV); tracking_active = false end
  local m = stop_mode
  have_job = false
  if m == 3 then
    running = false
  else
    MovP("GL_HOME")
    WriteModbus(REG_FREE, "W", 1)
    if m == 2 then running = false; exit_servo_off = true end
  end
  motion_stopped = false
  WriteModbus(REG_STOP, "W", 0)
  stop_mode = 0
  print("STOP mode " .. m .. " выполнен")
end

local function handle_miss()
  if tracking_active then CVT_VelOut(CV); tracking_active = false end
  miss_count = (miss_count + 1) % 32767
  have_job = false
  zone_tripped = false
  motion_stopped = false
  MovP("GL_HOME")
  WriteModbus(REG_FREE, "W", 1)
  print("MISS #" .. miss_count .. " — объект вне кольца (" .. zone_min .. ".." .. zone_max .. ")")
end

-- =====================  ОДНО ЗАДАНИЕ CVT (pick-place)  ============
local function run_job()
  if not servo_on then return end
  local enc_now = CVT_GetEncoderPulseCount(CV) or -1
  if enc_now < 0 then return end
  local trav = (enc_now - job_enc) * FACTOR_MM
  local px = job_x + UX * trav
  local py = job_y + UY * trav
  WriteModbus(REG_ECHO_X, "W", clampW(job_x * XY_SCALE))
  WriteModbus(REG_ECHO_Y, "W", clampW(job_y * XY_SCALE))
  WriteModbus(REG_PX,     "W", clampW(px * XY_SCALE))
  WriteModbus(REG_PY,     "W", clampW(py * XY_SCALE))
  WriteModbus(REG_TRAV,   "W", clampW(trav * XY_SCALE))
  WritePoint("GL_PICK", "X", px)
  WritePoint("GL_PICK", "Y", py)
  -- глубина захвата: job_z с ПК (если задан), иначе дефолт Z_PICK
  WritePoint("GL_PICK", "Z", (job_z ~= 0) and job_z or Z_PICK)
  if obj_out_of_zone(px, py) then
    miss_count = (miss_count + 1) % 32767
    have_job = false
    WriteModbus(REG_FREE, "W", 1)
    print("MISS #" .. miss_count .. " — цель вне кольца (не начинаем)")
    return
  end
  tracking_active = true
  CVT_VelIn(CV)
  MovL("GL_PICK")
  if stop_mode ~= 0 then handle_stop(); return end
  if zone_tripped then handle_miss(); return end
  DO(DO_GRIP, "ON")                                    -- ЗАХВАТ диска (вакуум, DO1) — строковый формат
  DELAY(GRIP_S)
  if stop_mode ~= 0 then handle_stop(); return end
  if zone_tripped then handle_miss(); return end
  CVT_VelOut(CV); tracking_active = false
  -- УКЛАДКА: при place_fl=1 — в позу job (x/y/z) с доворотом R=R_BASE+rz; иначе фикс. GL_PLACE.
  if job_place_fl == 1 then
    -- R укладки — АБСОЛЮТНЫЙ: ПК опросил реальный R инструмента (телеметрия) и прислал уже
    -- R = реальный_R + доворот. Lua ставит готовое значение, без вычислений и хардкода R_BASE.
    WritePoint("GL_PLACE", "X", job_place_x)
    WritePoint("GL_PLACE", "Y", job_place_y)
    WritePoint("GL_PLACE", "Z", job_place_z)
    WritePoint("GL_PLACE", "R", job_place_rz)            -- абсолютный R инструмента при укладке
  end
  MovP("GL_PLACE")
  if stop_mode ~= 0 then handle_stop(); return end
  DO(DO_GRIP, "OFF")                                   -- ОТПУСТИТЬ диск в слот (вакуум, DO1)
  DELAY(GRIP_S)
  if stop_mode ~= 0 then handle_stop(); return end
  if job_place_fl == 1 then
    -- вернуть R точки укладки к базе (чтобы place_flag=0 jobs клали в нейтральной ориентации;
    -- физически R довернёт MovP("GL_HOME")). ВАЖНО на роботе: имя 4-й оси WritePoint (R/C/A).
    WritePoint("GL_PLACE", "R", R_BASE)
  end
  MovP("GL_HOME")                                        -- R → R_BASE (дом. ориентация) + подъём + домой
  have_job = false
  WriteModbus(REG_FREE, "W", 1)
end

-- =====================  ПРОХОД БУФЕРА (рисование)  ================
-- Пред-чтение всей пачки → запись в ПУЛ distinct-точек → MovL(PASS) по разным точкам
-- (контроллер делает look-ahead → плавная линия). Зовётся из Motion (function1).
local function execute_path(count)
  local pen_down = ReadModbus(REG_PEN_DOWN, "W") / XY_SCALE
  local pen_up   = ReadModbus(REG_PEN_UP,   "W") / XY_SCALE
  local spd      = ReadModbus(REG_DRAW_SPD, "W")
  local overlap  = ReadModbus(REG_OVERLAP,  "W") / XY_SCALE
  -- Скорость РИСОВАНИЯ (перо по бумаге) и ПЕРЕЕЗДА (перо вверх) — обе с пульта (регистры).
  local trav     = ReadModbus(REG_DRAW_TRAVEL, "W")
  local draw_spd = (spd and spd >= 1 and spd <= 100) and spd or DRAW_SPD0
  local travel_spd = (trav and trav >= 1 and trav <= 100) and trav or TRAVEL_SPD0
  Override(draw_spd)
  if overlap < 0.1 then overlap = 0.1 end
  if count > PTS_MAX then count = PTS_MAX end

  -- 1) пред-чтение пачки в таблицы (в цикле движения НЕТ Modbus-чтений)
  local px, py, pen = {}, {}, {}
  local got = 0
  while got < count do
    local n = count - got
    if n > 10 then n = 10 end                        -- ≤30 регистров за чтение (как и запись с ПК)
    local blk = MultiReadModbus(REG_PTS_BASE + got * 3, n * 3, "W")
    if not blk or #blk < n * 3 then break end
    for k = 0, n - 1 do
      px[got + k + 1]  = blk[k * 3 + 1] / XY_SCALE
      py[got + k + 1]  = blk[k * 3 + 2] / XY_SCALE
      pen[got + k + 1] = blk[k * 3 + 3]
    end
    got = got + n
  end
  if got < count then count = got end
  if count < 1 then WriteModbus(REG_DRAW_BUSY, "W", 0); return end

  -- 2) координаты → ПУЛ distinct-точек POOL_BASE+1..POOL_BASE+count (Z по перу)
  for i = 1, count do
    WritePoint(POOL_BASE + i, "X", px[i])
    WritePoint(POOL_BASE + i, "Y", py[i])
    WritePoint(POOL_BASE + i, "Z", (pen[i] == 1) and pen_down or pen_up)
  end

  -- 3) проход
  -- Между штрихами (точка pen=0 — подвод к началу следующего штриха) НЕ едем по
  -- диагонали (раньше один MovL из (конец штриха, перо ВНИЗ) в (подвод, перо ВВЕРХ)
  -- тянул призрачную линию). Теперь явный П-образный переезд через скретч GL_MAN (в
  -- DRAW простаивает): (1) вертикальный подъём в ТЕКУЩЕМ XY до pen_up → (2) переезд на
  -- высоте до подвода → (3) вертикальное опускание в подводе до pen_down перед штрихом.
  -- Высота переезда = pen_up (live-tunable из пульта «Перо: подъём»; оператор задаёт зазор,
  -- рекомендуется ≥10 мм — текущий дефолт рецепта 6 мм для медленного боевого теста).
  PassMode("DISTANT", "PLON")
  SetOverlapDistance(overlap)
  WriteModbus(REG_DRAW_BUSY, "W", 1)
  local LIFT = "GL_MAN"   -- скретч-точка для вертикальных подъёма/опускания (в DRAW свободна)
  for i = 1, count do
    if draw_abort then break end
    WriteModbus(REG_DRAW_PROG, "W", i)
    if pen[i] == 0 then
      -- подвод к началу штриха — П-образно, БЫСТРО (перо вверх → паузы между штрихами минимальны)
      Override(travel_spd)
      if i > 1 then
        WritePoint(LIFT, "X", px[i - 1]); WritePoint(LIFT, "Y", py[i - 1]); WritePoint(LIFT, "Z", pen_up)
        MovL(LIFT)                                  -- (1) подъём вертикально в текущем XY — быстро
      end
      MovL(POOL_BASE + i)                           -- (2) переезд на высоте к подводу (Z=pen_up) — быстро
      Override(draw_spd)                            -- вернуть скорость пера для опускания+штриха
      WritePoint(LIFT, "X", px[i]); WritePoint(LIFT, "Y", py[i]); WritePoint(LIFT, "Z", pen_down)
      MovL(LIFT)                                    -- (3) опускание вертикально в подводе — скорость пера
    elseif pen[i] == 1 and i < count then
      MovL(POOL_BASE + i, PASS())                   -- внутри штриха — скорость пера (по слайдеру)
    else
      MovL(POOL_BASE + i)                           -- последняя точка штриха/прохода — чётко
    end
  end

  -- финал/после стопа: перо вверх НА МЕСТЕ. Между проходами робот ждёт здесь (не домой).
  -- Подъём +1 см и заезд домой — только если ПК пометил этот проход последним (REG_DRAW_HOME=1).
  WriteModbus(REG_DRAW_ABORT, "W", 0)
  draw_abort     = false
  motion_stopped = false
  Override(travel_spd)                              -- финал — перо вверх/домой, быстро (без рисования)
  WritePoint(POOL_BASE + 1, "X", RobotX() or px[count] or 0)
  WritePoint(POOL_BASE + 1, "Y", RobotY() or py[count] or 0)
  WritePoint(POOL_BASE + 1, "Z", pen_up)
  MovL(POOL_BASE + 1)
  if ReadModbus(REG_DRAW_HOME, "W") == 1 then
    WriteModbus(REG_DRAW_HOME, "W", 0)
    WritePoint(POOL_BASE + 1, "Z", pen_up + DRAW_LIFT_MM)  -- ещё +1 см вертикально (увести перо от листа)
    MovL(POOL_BASE + 1)
    MovP("GL_HOME")
    print("DRAW: рисунок завершён → подъём + домой")
  end
  -- Read-back ACK: эхо РЕАЛЬНО выполненного count (пост-усечённого) — до обнуления PROG.
  -- ПК сверяет с размером пачки и при расхождении повторяет проход (точки не теряются молча).
  WriteModbus(REG_DRAW_DONE_N, "W", count)
  WriteModbus(REG_DRAW_PROG, "W", 0)
  WriteModbus(REG_DRAW_BUSY, "W", 0)
  print("DRAW: проход завершён (" .. count .. " точек)")
end

-- Круг родной командой MCircle (круговая интерполяция). 3 точки задают круг: старт (cx+r,cy),
-- ref-верх (cx,cy+r), tgt-лево (cx-r,cy) → start→ref→tgt→назад = полный круг. Гладко, без точек.
local function draw_circle()
  local pen_down = ReadModbus(REG_PEN_DOWN, "W") / XY_SCALE
  local pen_up   = ReadModbus(REG_PEN_UP,   "W") / XY_SCALE
  local spd      = ReadModbus(REG_DRAW_SPD, "W")
  local trav     = ReadModbus(REG_DRAW_TRAVEL, "W")
  local draw_spd = (spd and spd >= 1 and spd <= 100) and spd or DRAW_SPD0  -- скорость пера по бумаге
  local travel_spd = (trav and trav >= 1 and trav <= 100) and trav or TRAVEL_SPD0  -- скорость переезда
  local cx = ReadModbus(REG_CIRC_CX, "W") / XY_SCALE
  local cy = ReadModbus(REG_CIRC_CY, "W") / XY_SCALE
  local r  = ReadModbus(REG_CIRC_R,  "W") / XY_SCALE

  WriteModbus(REG_DRAW_BUSY, "W", 1)
  local PS, PR, PT = POOL_BASE + 1, POOL_BASE + 2, POOL_BASE + 3  -- старт, ref-верх, tgt-лево
  Override(travel_spd)                               -- подвод над стартом — быстро (перо вверх)
  WritePoint(PS, "X", cx + r); WritePoint(PS, "Y", cy);     WritePoint(PS, "Z", pen_up)
  MovL(PS)                                            -- подвод над стартом, перо вверх
  Override(draw_spd)                                  -- скорость пера для рисования круга
  WritePoint(PS, "Z", pen_down); MovL(PS)             -- перо вниз на старте
  WritePoint(PR, "X", cx);     WritePoint(PR, "Y", cy + r); WritePoint(PR, "Z", pen_down)
  WritePoint(PT, "X", cx - r); WritePoint(PT, "Y", cy);     WritePoint(PT, "Z", pen_down)
  MCircle(PR, PT, "BORDER")                           -- полный круг (start→PR→PT→start)

  WriteModbus(REG_DRAW_ABORT, "W", 0)
  draw_abort     = false
  motion_stopped = false
  Override(travel_spd)                               -- финал — перо вверх/домой, быстро
  WritePoint(PS, "X", RobotX() or (cx + r)); WritePoint(PS, "Y", RobotY() or cy)
  WritePoint(PS, "Z", pen_up); MovL(PS)               -- перо вверх на месте
  if ReadModbus(REG_DRAW_HOME, "W") == 1 then
    WriteModbus(REG_DRAW_HOME, "W", 0)
    WritePoint(PS, "Z", pen_up + DRAW_LIFT_MM); MovL(PS)  -- ещё +1 см вертикально (увести перо от листа)
    MovP("GL_HOME")
    print("DRAW: круг завершён → подъём + домой")
  end
  WriteModbus(REG_DRAW_DONE_N, "W", 1)  -- круг = один логический проход (read-back ACK)
  WriteModbus(REG_DRAW_BUSY, "W", 0)
  print("DRAW: круг (" .. cx .. "," .. cy .. ") R=" .. r)
end

-- =====================  ОДИН РУЧНОЙ ХОД (MANUAL jog)  =============
-- ПК пишет dX/dY (0.1 мм) + скорость (Override %), флаг REG_MAN_FLAG запускает один MovL.
-- REG_MAN_ABS=0 — относительно текущей позы (jog на dX/dY); =1 — абсолют (ехать в X=dX, Y=dY).
-- Z/RZ сохраняются (движение в плоскости). Линейный ход одной команды ограничен 0..MAX_MAN_MM мм.
local MAX_MAN_MM = 200          -- макс. ход за одну команду, мм (защитный диапазон 0..200)

local function run_manual()
  if not servo_on then
    print("MANUAL: серво OFF — ход отклонён")
    WriteModbus(REG_MAN_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
    return
  end
  -- nil-guard: ReadModbus вне выделенного Modbus-пространства вернёт nil; без guard
  -- nil протекает в арифметику/WritePoint → "compare nil with number" → краш Motion-задачи.
  local dx  = (ReadModbus(REG_MAN_DX,  "W") or 0) / XY_SCALE
  local dy  = (ReadModbus(REG_MAN_DY,  "W") or 0) / XY_SCALE
  local spd = ReadModbus(REG_MAN_SPD, "W") or SPD_MOVE
  local absmode = ReadModbus(REG_MAN_ABS, "W") or 0
  if spd >= 1 and spd <= 100 then Override(spd) end   -- скорость через Override (%)

  local cx, cy, cz = RobotX() or 0, RobotY() or 0, RobotZ() or 0
  local tx, ty
  if absmode == 1 then tx, ty = dx, dy else tx, ty = cx + dx, cy + dy end

  -- защита: линейный ход одной команды — в диапазоне 0..MAX_MAN_MM мм
  local mvx, mvy = tx - cx, ty - cy
  local dist = math.sqrt(mvx * mvx + mvy * mvy)
  if dist > MAX_MAN_MM then
    local k = MAX_MAN_MM / dist
    tx, ty = cx + mvx * k, cy + mvy * k
    print("MANUAL: ход " .. iround(dist) .. " мм > " .. MAX_MAN_MM .. " — обрезан до " .. MAX_MAN_MM)
  end

  WritePoint("GL_MAN", "X", tx)
  WritePoint("GL_MAN", "Y", ty)
  WritePoint("GL_MAN", "Z", cz)                        -- Z сохраняем (движение в плоскости)
  WriteModbus(REG_MAN_BUSY, "W", 1); WriteModbus(REG_FREE, "W", 0)
  MovL("GL_MAN")                                       -- стоп ловит Mirror → MotionStop
  WriteModbus(REG_MAN_ABORT, "W", 0)
  manual_abort   = false
  motion_stopped = false
  WriteModbus(REG_MAN_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
  print("MANUAL: → (" .. iround(tx) .. "," .. iround(ty) .. ") spd=" .. spd .. " abs=" .. absmode)
end

-- =====================  ОДИН ВОЗВРАТ (RETURN на ленту)  ==========
-- ПК пишет координату СЛОТА (x,y,z — откуда забрать) + REG_RET_FLAG=1 (handshake).
-- Робот: подвод над слотом → опуститься → ЗАХВАТ → +RET_LIFT по Z → +RET_PUSH по X →
-- −RET_LIFT по Z → ОТПУСТИТЬ (диск падает на ленту) → домой. Только линейные MovL.
-- Стоп ловит Mirror (MotionStop) → проверяем stop_mode между ходами (как run_job).
local function ret_abort()
  WriteModbus(REG_STOP, "W", 0); stop_mode = 0
  motion_stopped = false
  DO(DO_GRIP, "OFF")                                   -- на стопе отпустить (диск мог быть в схвате)
  MovP("GL_HOME")
  WriteModbus(REG_RET_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
  print("RETURN: стоп → домой")
end

local function run_return()
  if not servo_on then
    print("RETURN: серво OFF — отклонено")
    WriteModbus(REG_RET_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
    return
  end
  local sx = (ReadModbus(REG_RET_X, "W") or 0) / XY_SCALE   -- nil-guard (см. run_manual)
  local sy = (ReadModbus(REG_RET_Y, "W") or 0) / XY_SCALE
  local sz = (ReadModbus(REG_RET_Z, "W") or 0) / XY_SCALE
  WriteModbus(REG_RET_BUSY, "W", 1); WriteModbus(REG_FREE, "W", 0)

  -- подвод над слотом (схват вверх)
  WritePoint("GL_RET", "X", sx); WritePoint("GL_RET", "Y", sy); WritePoint("GL_RET", "Z", sz + RET_LIFT_MM)
  MovL("GL_RET")
  if stop_mode ~= 0 then return ret_abort() end
  -- опуститься к диску и захватить
  WritePoint("GL_RET", "Z", sz); MovL("GL_RET")
  DO(DO_GRIP, "ON"); DELAY(GRIP_S)
  if stop_mode ~= 0 then return ret_abort() end
  -- подъём +RET_LIFT по Z
  WritePoint("GL_RET", "Z", sz + RET_LIFT_MM); MovL("GL_RET")
  -- сдвиг +RET_PUSH по X (над лентой)
  WritePoint("GL_RET", "X", sx + RET_PUSH_MM); MovL("GL_RET")
  if stop_mode ~= 0 then return ret_abort() end
  -- опускание −RET_LIFT по Z к ленте и отпустить
  WritePoint("GL_RET", "Z", sz); MovL("GL_RET")
  DO(DO_GRIP, "OFF"); DELAY(GRIP_S)
  MovP("GL_HOME")
  WriteModbus(REG_RET_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
  print("RETURN: (" .. iround(sx) .. "," .. iround(sy) .. ") → лента")
end

-- =====================  СМЕНА ИНСТРУМЕНТА (TOOLCHANGE, mode=4)  ===
-- ⚠️ ТОЧКИ. Для каждого инструмента — 3 ОБУЧЕННЫЕ точки робота:
--   over — "над инструментом" (высоко),  sock — "сам инструмент" (гнездо),  exit — "выход".
-- Обучи их на роботе под этими именами (или подставь сюда имена своих точек).
-- Инструмент 2 ВСЕГДА проходится через "над 1" (TOOL_TRANSIT) — и туда, и обратно.
local TOOL = {
  [1] = { over = "t1_over", sock = "t1_pick", exit = "t1_exit" },
  [2] = { over = "t2_over", sock = "t2_pick", exit = "t2_exit" },
}
local TOOL_TRANSIT = "t1_over"   -- "над 1 инструментом" — транзит к инструменту 2

-- стоп во время смены: гасим без homing — робот остаётся на месте
local function tool_abort()
  WriteModbus(REG_STOP, "W", 0); stop_mode = 0
  motion_stopped = false
  WriteModbus(REG_TOOL_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
  print("TOOL: стоп — робот на месте")
end

-- НАДЕТЬ инструмент n:  [над1 →] over → sock → exit
local function tool_mount(n)
  if n == 0 then return true end                  -- надевать нечего
  local p = TOOL[n]
  if n == 2 then MovL(TOOL_TRANSIT) end            -- к инстр.2 — через "над 1"
  MovL(p.over)                                      -- над инструментом
  if stop_mode ~= 0 then return false end
  Accur("HIGH")
  MovL(p.sock)                                      -- в гнездо (надевание)
  DELAY(1)
  if stop_mode ~= 0 then return false end
  Accur("ROUGH")
  MovL(p.exit)                                      -- выход инструмента
  return stop_mode == 0
end

-- СНЯТЬ инструмент n:  exit → sock → over [→ над1]
local function tool_remove(n)
  if n == 0 then return true end                  -- снимать нечего
  local p = TOOL[n]
  MovL(p.exit)                                      -- выход инструмента
  if stop_mode ~= 0 then return false end
  Accur("HIGH")
  MovL(p.sock)                                      -- в гнездо (снятие)
  DELAY(1)
  if stop_mode ~= 0 then return false end
  Accur("ROUGH")
  MovL(p.over)                                      -- над инструментом
  if n == 2 then MovL(TOOL_TRANSIT) end            -- от инстр.2 — обратно через "над 1"
  return stop_mode == 0
end

-- одна смена: сначала вернуть текущий инструмент в гнездо, потом надеть целевой
local function run_toolchange()
  if not servo_on then
    print("TOOL: серво OFF — отклонено")
    WriteModbus(REG_TOOL_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
    return
  end
  local target = ReadModbus(REG_TOOL_TARGET, "W") or 0   -- nil-guard (см. run_manual)
  if target ~= 0 and target ~= 1 and target ~= 2 then
    print("TOOL: неверный target = " .. tostring(target))
    WriteModbus(REG_TOOL_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
    return
  end
  if target == instrument then
    print("TOOL: инструмент " .. target .. " уже стоит")
    WriteModbus(REG_TOOL_CUR, "W", instrument)
    WriteModbus(REG_TOOL_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
    return
  end
  WriteModbus(REG_TOOL_BUSY, "W", 1); WriteModbus(REG_FREE, "W", 0)
  if not tool_remove(instrument) then return tool_abort() end   -- вернуть текущий в гнездо
  if not tool_mount(target)      then return tool_abort() end   -- надеть новый
  instrument = target
  WriteModbus(REG_TOOL_CUR, "W", instrument)
  MovP("GL_HOME")                                                -- домой — готов к работе/выходу
  WriteModbus(REG_TOOL_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
  print("TOOL: установлен инструмент " .. instrument)
end

-- =====================  FUNCTION2: MIRROR (параллельная)  =========
-- Крутится ВО ВРЕМЯ хода Motion. Ветвится по режиму. ⚠️ НЕТ while/WAIT/DELAY.
function Mirror()
  if mode == 1 then
    -- DRAW: живая поза + стоп рисования
    publish_pose()
    if ReadModbus(REG_DRAW_ABORT, "W") == 1 then
      draw_abort = true
      if not motion_stopped then MotionStop(); motion_stopped = true end
    end
    return
  end

  if mode == 2 then
    -- MANUAL: живая поза + свежий энкодер + стоп ручного хода
    publish_pose()
    local enc = CVT_GetEncoderPulseCount(CV)
    if enc then WriteModbus(REG_ENC, "DW", enc) end
    if ReadModbus(REG_MAN_ABORT, "W") == 1 then
      manual_abort = true
      if not motion_stopped then MotionStop(); motion_stopped = true end
    end
    local sm = poll_stop()
    if sm ~= 0 then
      stop_mode = sm
      if not motion_stopped then MotionStop(); motion_stopped = true end
    end
    return
  end

  if mode == 3 then
    -- RETURN: живая поза + стоп возврата
    publish_pose()
    local sm = poll_stop()
    if sm ~= 0 then
      stop_mode = sm
      if not motion_stopped then MotionStop(); motion_stopped = true end
    end
    return
  end

  if mode == 4 then
    -- TOOLCHANGE: живая поза + стоп смены инструмента
    publish_pose()
    local sm = poll_stop()
    if sm ~= 0 then
      stop_mode = sm
      if not motion_stopped then MotionStop(); motion_stopped = true end
    end
    return
  end

  -- CVT: во время движения опрашиваем ТОЛЬКО энкодер (+ стоп + зона). Живую позу
  -- робота (RobotX/RobotY) тут НЕ читаем: в fault-состоянии геттеры возвращают nil и
  -- роняют скрипт, а трекинг и так идёт по энкодеру (поза не нужна). Позу X/Y публикует
  -- publish_telemetry() в IDLE-ветке Motion, когда робот НЕ в движении.
  local enc = CVT_GetEncoderPulseCount(CV)
  if enc then WriteModbus(REG_ENC, "DW", enc) end
  local sm = poll_stop()
  if sm ~= 0 then
    stop_mode = sm
    if not motion_stopped then MotionStop(); motion_stopped = true end
  end
  -- job_enc в guard: если приём задания прочитал ECAP как nil — не считаем зону (без краша).
  if tracking_active and not zone_tripped and enc and job_enc and (zone_max > 0 or zone_min > 0) then
    local t  = (enc - job_enc) * FACTOR_MM
    local ox = job_x + UX * t
    local oy = job_y + UY * t
    if obj_out_of_zone(ox, oy) then
      zone_tripped = true
      if not motion_stopped then MotionStop(); motion_stopped = true end
    end
  end
end

-- =====================  FUNCTION1: MOTION (главный цикл)  =========
-- Тело одной итерации вынесено в motion_body; Motion() гоняет его в pcall, чтобы
-- ЛЮБОЙ транзиентный сбой (nil-чтение шины, fault-геттер RobotX/Y/Z) НЕ ронял задачу
-- MultiTask — ошибка печатается, цикл продолжается. DRAW happy-path не затронут.
local function motion_body()
    mode = ReadModbus(REG_MODE, "W")                -- 0 CVT / 1 DRAW / 2 MANUAL / 3 RETURN / 4 TOOLCHANGE
    if mode ~= 1 and mode ~= 2 and mode ~= 3 and mode ~= 4 then mode = 0 end

    if mode == 1 then
      -- ================ РЕЖИМ РИСОВАНИЯ ================
      publish_pose()
      if ReadModbus(REG_DRAW_FLAG, "W") == 1 then
        WriteModbus(REG_DRAW_FLAG, "W", 0)
        draw_abort = false
        WriteModbus(REG_DRAW_ABORT, "W", 0)
        if ReadModbus(REG_DRAW_TYPE, "W") == 1 then
          draw_circle()                               -- круг через MCircle
        else
          local count = ReadModbus(REG_DRAW_COUNT, "W") or 0
          if count > 0 then execute_path(count) end   -- полилиния через буфер
        end
      else
        -- Стоп МЕЖДУ проходами (робот стоит, busy=0 — Mirror не ловит abort в движении).
        -- Если ПК взвёл REG_DRAW_HOME=1 (так делает _op_draw_abort), честно уводим домой:
        -- поднимаем перо +1 см вертикально и едем в GL_HOME (как финал прохода). Иначе
        -- робот «забывал» приехать домой, если стоп пришёлся на паузу между проходами.
        if ReadModbus(REG_DRAW_ABORT, "W") == 1 then
          WriteModbus(REG_DRAW_ABORT, "W", 0)
          if ReadModbus(REG_DRAW_HOME, "W") == 1 then
            WriteModbus(REG_DRAW_HOME, "W", 0)
            local pen_up = ReadModbus(REG_PEN_UP, "W") / XY_SCALE
            WritePoint(POOL_BASE + 1, "X", RobotX() or 0)
            WritePoint(POOL_BASE + 1, "Y", RobotY() or 0)
            WritePoint(POOL_BASE + 1, "Z", pen_up + DRAW_LIFT_MM)  -- перо вверх вертикально
            MovL(POOL_BASE + 1)
            MovP("GL_HOME")
            print("DRAW: стоп между проходами → подъём + домой")
          end
        end
        DELAY(0.02)
      end

    elseif mode == 2 then
      -- ================ РЕЖИМ MANUAL (ручной jog по Modbus) ================
      publish_pose()
      mirror_encoder()
      if stop_mode == 0 then stop_mode = poll_stop() end
      if stop_mode ~= 0 then
        -- стоп ручного хода: гасим без homing — робот остаётся на месте
        WriteModbus(REG_STOP, "W", 0); stop_mode = 0
        motion_stopped = false
        WriteModbus(REG_MAN_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
        print("MANUAL: стоп — робот на месте")
      elseif ReadModbus(REG_VFD_FLAG, "W") == 1 then
        -- ПЧ на той же RS-485 — обслуживаем и в MANUAL (иначе heartbeat ПЧ замёрзнет → stale)
        WriteModbus(REG_VFD_FLAG, "W", 0)
        handle_vfd()
      elseif ReadModbus(REG_SERVO, "W") == 1 then
        WriteModbus(REG_SERVO, "W", 0); RobotServoOn();  servo_on = true;  print("SERVO ON")
      elseif ReadModbus(REG_SERVO, "W") == 2 then
        WriteModbus(REG_SERVO, "W", 0); RobotServoOff(); servo_on = false; print("SERVO OFF")
      elseif ReadModbus(REG_MAN_FLAG, "W") == 1 then
        WriteModbus(REG_MAN_FLAG, "W", 0)
        manual_abort = false
        WriteModbus(REG_MAN_ABORT, "W", 0)
        run_manual()
      else
        publish_telemetry()
        WriteModbus(REG_FREE, "W", 1)
        DELAY(0.005)
      end

    elseif mode == 3 then
      -- ================ РЕЖИМ RETURN (возврат буквы на ленту) ================
      publish_pose()
      if stop_mode == 0 then stop_mode = poll_stop() end
      if stop_mode ~= 0 then
        -- стоп возврата: гасим без homing — робот на месте
        WriteModbus(REG_STOP, "W", 0); stop_mode = 0
        motion_stopped = false
        WriteModbus(REG_RET_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
        print("RETURN: стоп — робот на месте")
      elseif ReadModbus(REG_VFD_FLAG, "W") == 1 then
        -- ПЧ на той же RS-485 — обслуживаем и в RETURN (иначе heartbeat ПЧ замёрзнет)
        WriteModbus(REG_VFD_FLAG, "W", 0)
        handle_vfd()
      elseif ReadModbus(REG_SERVO, "W") == 1 then
        WriteModbus(REG_SERVO, "W", 0); RobotServoOn();  servo_on = true;  print("SERVO ON")
      elseif ReadModbus(REG_SERVO, "W") == 2 then
        WriteModbus(REG_SERVO, "W", 0); RobotServoOff(); servo_on = false; print("SERVO OFF")
      elseif ReadModbus(REG_RET_FLAG, "W") == 1 then
        WriteModbus(REG_RET_FLAG, "W", 0)             -- приём (handshake: flag→0), дальше busy 1→0
        run_return()
      else
        publish_telemetry()
        WriteModbus(REG_FREE, "W", 1)
        DELAY(0.005)
      end

    elseif mode == 4 then
      -- ================ РЕЖИМ TOOLCHANGE (смена инструмента) ================
      publish_pose()
      if stop_mode == 0 then stop_mode = poll_stop() end
      if stop_mode ~= 0 then
        -- стоп смены: гасим без homing — робот на месте
        WriteModbus(REG_STOP, "W", 0); stop_mode = 0
        motion_stopped = false
        WriteModbus(REG_TOOL_BUSY, "W", 0); WriteModbus(REG_FREE, "W", 1)
        print("TOOL: стоп — робот на месте")
      elseif ReadModbus(REG_VFD_FLAG, "W") == 1 then
        -- ПЧ на той же RS-485 — обслуживаем и в TOOLCHANGE (иначе heartbeat ПЧ замёрзнет)
        WriteModbus(REG_VFD_FLAG, "W", 0)
        handle_vfd()
      elseif ReadModbus(REG_SERVO, "W") == 1 then
        WriteModbus(REG_SERVO, "W", 0); RobotServoOn();  servo_on = true;  print("SERVO ON")
      elseif ReadModbus(REG_SERVO, "W") == 2 then
        WriteModbus(REG_SERVO, "W", 0); RobotServoOff(); servo_on = false; print("SERVO OFF")
      elseif ReadModbus(REG_TOOL_FLAG, "W") == 1 then
        WriteModbus(REG_TOOL_FLAG, "W", 0)            -- приём (handshake: flag→0), дальше busy 1→0
        run_toolchange()
      else
        publish_telemetry()
        WriteModbus(REG_FREE, "W", 1)
        DELAY(0.005)
      end

    else
      -- ================ РЕЖИМ CVT pick-place ================
      mirror_encoder()
      if stop_mode == 0 then stop_mode = poll_stop() end
      if stop_mode ~= 0 then
        handle_stop()
      elseif ReadModbus(REG_VFD_FLAG, "W") == 1 then
        WriteModbus(REG_VFD_FLAG, "W", 0)
        handle_vfd()
      elseif ReadModbus(REG_CFG_FLAG, "W") == 1 then
        WriteModbus(REG_CFG_FLAG, "W", 0)
        handle_config()
      elseif ReadModbus(REG_SERVO, "W") == 1 then
        WriteModbus(REG_SERVO, "W", 0); RobotServoOn();  servo_on = true;  print("SERVO ON")
      elseif ReadModbus(REG_SERVO, "W") == 2 then
        WriteModbus(REG_SERVO, "W", 0); RobotServoOff(); servo_on = false; print("SERVO OFF")
      elseif have_job then
        run_job()
      elseif ReadModbus(REG_FLAG, "W") == 1 then
        job_x   = (ReadModbus(REG_X, "W") or 0) / XY_SCALE
        job_y   = (ReadModbus(REG_Y, "W") or 0) / XY_SCALE
        job_enc = ReadModbus(REG_ECAP, "DW") or 0
        -- глубина захвата (Z); 0 = дефолт Z_PICK. Сбрасываем регистр после чтения, чтобы
        -- следующий job без job_z не унаследовал прошлую глубину (стейл).
        job_z   = (ReadModbus(REG_Z, "W") or 0) / XY_SCALE
        WriteModbus(REG_Z, "W", 0)
        -- поза укладки (доворот); place_fl=0 → старое поведение (фикс. GL_PLACE)
        -- nil-guard: читаются на КАЖДОМ job; nil из ReadModbus → краш Motion → задержка job.
        job_place_fl = ReadModbus(REG_PLACE_FLAG, "W") or 0
        job_place_x  = (ReadModbus(REG_PLACE_X,  "W") or 0) / XY_SCALE
        job_place_y  = (ReadModbus(REG_PLACE_Y,  "W") or 0) / XY_SCALE
        job_place_z  = (ReadModbus(REG_PLACE_Z,  "W") or 0) / XY_SCALE
        job_place_rz = (ReadModbus(REG_PLACE_RZ, "W") or 0) / XY_SCALE
        WriteModbus(REG_PLACE_FLAG, "W", 0)
        have_job = true
        WriteModbus(REG_FLAG, "W", 0)
        WriteModbus(REG_FREE, "W", 0)
      else
        publish_telemetry()
        WriteModbus(REG_FREE, "W", 1)
        DELAY(0.005)
      end
    end
end

function Motion()
  while running do
    local ok, err = pcall(motion_body)
    if not ok then
      print("Motion: поймал ошибку, продолжаю: " .. tostring(err))
      DELAY(0.02)
    end
  end
end

-- =====================  СТАРТ  ====================================
Override(100)
SpdJ(25);  AccJ(100); DecJ(100)        -- ↓ скорость PTP (joint) в 4 раза: было 100% → 25%
SpdL(500); AccL(25000); DecL(25000)    -- ↓ линейная скорость в 4 раза: было 2000 → 500 мм/с

initCVT()

local rtn = SCM_FreePort(PORT, RS485_RATE, RS485_PROTOCOL, RS485_MODE, 0x1, 0x0, 0x0, 0x00, 0x00)
print("SCM_FreePort rtn = " .. tostring(rtn) .. " (0 = ок)")
DELAY(0.1)
mb_write(VFD_REG_CMD, CMD_STOP)
mb_write(VFD_REG_FREQ, 0)
last_cmd, last_freq = CMD_STOP, 0

RobotServoOn()
DO(2, "ON")                                          -- enable вакуумного эжектора/насоса на всю сессию (DO2). Захват диска — DO1 в run_job

-- объявить ПУЛ distinct-точек для рисования (id 101..200), координаты зададим под пачку
for i = 1, PTS_MAX do
  SetGlobalPoint(POOL_BASE + i, "GL_D" .. i, 0, 0, PEN_UP0, -100, 1, 0, 0, POSTURE)
end

have_job = false
WriteModbus(REG_MODE,  "W", 0)                       -- старт в режиме CVT
WriteModbus(REG_FLAG,  "W", 0)
WriteModbus(REG_STOP,  "W", 0)
WriteModbus(REG_SERVO, "W", 0)
WriteModbus(REG_FREE,  "W", 1)
WriteModbus(REG_DRAW_HOME, "W", 0)                   -- между проходами ждать на месте (не домой)
WriteModbus(REG_VFD_FLAG,  "W", 0)
WriteModbus(REG_CMD_RUN,   "W", 0)
WriteModbus(REG_CMD_DIR,   "W", 0)
WriteModbus(REG_CMD_FREQ,  "W", 0)
WriteModbus(REG_CMD_RESET, "W", 0)
WriteModbus(REG_CFG_FLAG,     "W", 0)
WriteModbus(REG_CFG_BASE + 0, "W", SPD_MOVE)
WriteModbus(REG_CFG_BASE + 1, "W", iround( 300 * XY_SCALE))
WriteModbus(REG_CFG_BASE + 2, "W", iround(-210 * XY_SCALE))
WriteModbus(REG_CFG_BASE + 3, "W", iround( -40 * XY_SCALE))
WriteModbus(REG_CFG_BASE + 4, "W", iround(Z_PICK * XY_SCALE))
WriteModbus(REG_CFG_BASE + 5, "W", iround( 450 * XY_SCALE))
WriteModbus(REG_CFG_BASE + 6, "W", iround(-300 * XY_SCALE))
WriteModbus(REG_CFG_BASE + 7, "W", iround( -90 * XY_SCALE))
WriteModbus(REG_CFG_BASE + 8,  "W", iround(GRIP_S * 1000))
WriteModbus(REG_CFG_BASE + 9,  "W", iround(zone_max * XY_SCALE))
WriteModbus(REG_CFG_BASE + 10, "W", iround(zone_min * XY_SCALE))
-- дефолты рисования
WriteModbus(REG_DRAW_FLAG,  "W", 0)
WriteModbus(REG_DRAW_TYPE,  "W", 0)
WriteModbus(REG_DRAW_COUNT, "W", 0)
WriteModbus(REG_DRAW_BUSY,  "W", 0)
WriteModbus(REG_DRAW_PROG,  "W", 0)
WriteModbus(REG_DRAW_DONE_N, "W", 0)
WriteModbus(REG_DRAW_ABORT, "W", 0)
WriteModbus(REG_CIRC_CX,    "W", 0)
WriteModbus(REG_CIRC_CY,    "W", 0)
WriteModbus(REG_CIRC_R,     "W", 0)
WriteModbus(REG_PEN_DOWN, "W", iround(PEN_DOWN0 * XY_SCALE))
WriteModbus(REG_PEN_UP,   "W", iround(PEN_UP0   * XY_SCALE))
WriteModbus(REG_DRAW_SPD, "W", DRAW_SPD0)
WriteModbus(REG_DRAW_TRAVEL, "W", TRAVEL_SPD0)
WriteModbus(REG_OVERLAP,  "W", iround(OVERLAP0 * XY_SCALE))
-- дефолты ручного режима (MANUAL)
WriteModbus(REG_MAN_FLAG,  "W", 0)
WriteModbus(REG_MAN_DX,    "W", 0)
WriteModbus(REG_MAN_DY,    "W", 0)
WriteModbus(REG_MAN_SPD,   "W", SPD_MOVE)
WriteModbus(REG_MAN_BUSY,  "W", 0)
WriteModbus(REG_MAN_ABORT, "W", 0)
WriteModbus(REG_MAN_ABS,   "W", 0)
-- дефолты возврата (RETURN)
WriteModbus(REG_RET_FLAG, "W", 0)
WriteModbus(REG_RET_BUSY, "W", 0)
-- дефолты смены инструмента (TOOLCHANGE)
WriteModbus(REG_TOOL_FLAG,   "W", 0)
WriteModbus(REG_TOOL_TARGET, "W", 0)
WriteModbus(REG_TOOL_BUSY,   "W", 0)
WriteModbus(REG_TOOL_CUR,    "W", instrument)

MovP("GL_HOME", SPD(SPD_MOVE))

print("cvt_universal_FULL: старт v2-NILSAFE (CVT + DRAW + MANUAL, MultiTask)")
print("enc=" .. tostring(CVT_GetEncoderPulseCount(CV)))

running = true
MultiTask(Motion, Mirror)

-- выход по стопу 2/3 (только в CVT-режиме)
mb_write(VFD_REG_CMD, CMD_STOP)
if exit_servo_off then
  RobotServoOff()
  print("СТОП: робот дома, серво OFF")
else
  print("СТОП: робот на месте, серво ON")
end
print("MultiTask завершён — программа остановлена")
