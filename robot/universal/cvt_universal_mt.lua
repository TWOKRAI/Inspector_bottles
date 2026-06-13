-- =====================================================================
--  Delta SCARA · DRAStudio (Lua/RL) — ЭКСПЕРИМЕНТ: MultiTask вместо AuxTasks
--
--  ПОЧЕМУ. AuxTasks режет задачи по 15 мс ПО ОЧЕРЕДИ: блокирующий MovL/MovP
--  держит слайс до конца хода → Mirror в это время НЕ крутится → энкодер во
--  время движения замирает, а стоп ловится только МЕЖДУ движениями.
--  MultiTask (мануал RL 11.2.3): «During motion, other subfunction execute
--  CONCURRENTLY» — вторая функция реально работает ВО ВРЕМЯ хода первой.
--  Это даёт: (1) свежий энкодер во время движения (синхронизация кадра!),
--            (2) MotionStop на ходу.
--
--  ГИБРИД (два планировщика разом нельзя):
--    • Motion (function1) — ВЕСЬ цикл во внутреннем `while running`. В ПРОСТОЕ
--      function2 не получает управления (она крутится только во время ХОДА
--      function1), поэтому Motion САМ мирроит энкодер и ловит стоп в простое.
--    • Mirror (function2) — крошечная: миррор энкодера + детект стопа + MotionStop.
--      ⚠️ Требование MultiTask к function2+: НЕТ while/WAIT/DELAY (иначе не
--      вернёт управление в function1). У нас их нет — подходит.
--
--  Итого энкодер свежий ВСЕГДА: во время хода — через Mirror, в простое — через
--  сам Motion. ПК-сторона (pc_robot.py) без изменений — карта регистров та же.
--
--  Связь: ПК ──Modbus TCP master──▶ робот (:502, server, unit id=2)
--         робот ──RS-485 RTU (Free Port)──▶ INVT GD20
-- =====================================================================

-- =====================  КАРТА РЕГИСТРОВ  ============================
local REG_FLAG = 0x1100        -- W  : 1 = задание готово (ПК), 0 = принято (робот)
local REG_X    = 0x1101        -- W  : X в 0.1 мм
local REG_Y    = 0x1102        -- W  : Y в 0.1 мм
local REG_ECAP = 0x1104        -- DW : E_capture — энкодер в момент кадра (чётный!)
local REG_STOP = 0x1106        -- W  : СТОП. 0=нет | 1=домой+продолжить | 2=домой+выход+серво OFF | 3=на месте+выход+серво ON
local REG_SERVO = 0x1108       -- W  : серво (одноразовая). 0=нет | 1=включить | 2=выключить
local REG_FREE = 0x1110        -- W  : 1 = робот свободен, 0 = занят
local REG_ENC  = 0x1112        -- DW : живой энкодер (зеркалим — ПК читает как E_capture)
local REG_ECHO_X = 0x1120      -- W  : принятый job_x
local REG_ECHO_Y = 0x1121      -- W  : принятый job_y
local REG_PX     = 0x1122      -- W  : вычисленный px
local REG_PY     = 0x1123      -- W  : вычисленный py
local REG_TRAV   = 0x1124      -- W  : сдвиг ленты trav
-- VFD команда от ПК:
local REG_CMD_RUN   = 0x1200
local REG_CMD_DIR   = 0x1201
local REG_CMD_FREQ  = 0x1202
local REG_CMD_RESET = 0x1203
local REG_VFD_FLAG  = 0x1204   -- маркер «команда ПЧ»
-- VFD статус (робот пишет), 0x1210..0x1217:
local REG_ST_BASE   = 0x1210
local ST_BLOCK_CNT  = 8
-- Телеметрия робота (робот пишет), 0x1130..0x113A:
local REG_TLM_BASE = 0x1130
local TLM_CNT      = 11
--   0..3 X/Y/Z/RZ ×10 | 4 занят | 5 SPD | 6 лента | 7 рука | 8 hb | 9 серво(0/1) | 10 miss
local TLM_EVERY    = 5
-- Параметры робота от ПК, маркер 0x1300, блок 0x1301..0x130A:
local REG_CFG_FLAG = 0x1300
local REG_CFG_BASE = 0x1301
local CFG_CNT      = 10
--   0 SPD | 1..3 home X/Y/Z | 4 pick_z | 5..7 place X/Y/Z | 8 grip мс | 9 zone_r (0=выкл)

-- =====================  ГЕОМЕТРИЯ / ТОЧКИ  ========================
local CV        = 1
local FACTOR_MM = 0.144473
local UX, UY    = 0, 1          -- лента в +Y (совпадает с cmpstVectorY=+1000)
local XY_SCALE  = 10.0

local Z_PICK   = -100
local SPD_MOVE = 60
local GRIP_S   = 2
local DO_GRIP  = 1
local POSTURE  = {0,0,0,0,0,0,0,4}
SetGlobalPoint(90, "GL_HOME",  300, -210, -40,    -100, 1, 0, 0, POSTURE)
SetGlobalPoint(91, "GL_PLACE", 450, -300, -90,    -100, 1, 0, 0, POSTURE)
SetGlobalPoint(80, "GL_PICK",  300, -210, Z_PICK, -100, 1, 0, 0, POSTURE)

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
-- ⚠️ Mirror и Motion делят состояние; helper'ы, зовущиеся из обеих задач, используют
--    ТОЛЬКО локальные переменные внутри (требование MultiTask, мануал 11.2.2).
have_job        = false
job_x, job_y, job_enc = 0, 0, 0
heartbeat       = 0
comm_errors     = 0
robot_hb        = 0
tlm_tick        = 0
stop_mode       = 0            -- 0/1/2/3 — запрошенный стоп
tracking_active = false        -- идёт CVT-подвод (VelIn..VelOut)
motion_stopped  = false        -- латч MotionStop (не спамить → WA004)
running         = true         -- главный цикл Motion; стоп 2/3 → false → выход
exit_servo_off  = false        -- стоп 2 → выключить серво после цикла (стоп 3 — оставить ON)
servo_on        = true         -- состояние серво (для гейта заданий и телеметрии)
zone_r          = 0            -- радиус круглой зоны досягаемости (мм) от базы; 0 = проверка ВЫКЛ
miss_count      = 0            -- счётчик «объект ушёл за зону»
zone_tripped    = false        -- зона: объект вышел за радиус → прервать подвод как MISS

-- =====================  МЕЛКИЕ ХЕЛПЕРЫ  ===========================
local function iround(v) return math.floor(v + 0.5) end

local function clampW(v)
  v = iround(v)
  if v >  32767 then return  32767 end
  if v < -32767 then return -32767 end
  return v
end

-- Зеркалирование энкодера — ЗОВЁТСЯ ИЗ ОБЕИХ ЗАДАЧ (только локальные переменные!).
-- Свежий REG_ENC — это и есть «кадр синхронизирован с энкодером»: ПК читает REG_ENC
-- в момент детекции и получает актуальное E_capture.
local function mirror_encoder()
  local enc = CVT_GetEncoderPulseCount(CV)
  if enc then WriteModbus(REG_ENC, "DW", enc) end
end

-- Прочитать запрошенный стоп (nil-безопасно: только 1/2/3, иначе 0).
local function poll_stop()
  local sm = ReadModbus(REG_STOP, "W")
  if sm == 1 or sm == 2 or sm == 3 then return sm end
  return 0
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
  if freq ~= last_freq then
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
  local hx, hy, hz = c[2] / XY_SCALE, c[3] / XY_SCALE, c[4] / XY_SCALE     -- HOME
  local pz = c[5] / XY_SCALE                                               -- PICK высота
  local qx, qy, qz = c[6] / XY_SCALE, c[7] / XY_SCALE, c[8] / XY_SCALE     -- PLACE
  local grip_ms = c[9]
  local zr = c[10] / XY_SCALE                                              -- радиус зоны

  if spd >= 1 and spd <= 100 then SPD_MOVE = spd; Override(spd) end
  WritePoint("GL_HOME",  "X", hx); WritePoint("GL_HOME",  "Y", hy); WritePoint("GL_HOME",  "Z", hz)
  Z_PICK = pz; WritePoint("GL_PICK", "Z", pz)                             -- X/Y берётся с камеры
  WritePoint("GL_PLACE", "X", qx); WritePoint("GL_PLACE", "Y", qy); WritePoint("GL_PLACE", "Z", qz)
  if grip_ms >= 0 then GRIP_S = grip_ms / 1000.0 end
  if zr >= 0 then zone_r = zr end
  print("CFG: SPD=" .. SPD_MOVE .. " HOME=" .. hx .. "," .. hy .. "," .. hz ..
        " PICKZ=" .. Z_PICK .. " PLACE=" .. qx .. "," .. qy .. "," .. qz ..
        " GRIP=" .. GRIP_S .. " ZONE_R=" .. zone_r)
end

-- =====================  СТОП  =====================================
-- Зовётся ТОЛЬКО из Motion (function1) — там разрешено движение (MovP домой).
local function handle_stop()
  if tracking_active then CVT_VelOut(CV); tracking_active = false end
  local mode = stop_mode
  have_job = false
  if mode == 3 then
    running = false                                 -- на месте; серво ON; домой НЕ едем
  else
    MovP("GL_HOME")
    WriteModbus(REG_FREE, "W", 1)
    if mode == 2 then running = false; exit_servo_off = true end  -- домой; выход; серво OFF
  end
  motion_stopped = false
  WriteModbus(REG_STOP, "W", 0)
  stop_mode = 0
  print("STOP mode " .. mode .. " выполнен")
end

-- MISS: объект ушёл за круг досягаемости во время подвода. Снять слежение, посчитать,
-- вернуться домой, освободиться (как стоп-1, но это авто-промах). Зовётся ТОЛЬКО из Motion.
local function handle_miss()
  if tracking_active then CVT_VelOut(CV); tracking_active = false end
  miss_count = (miss_count + 1) % 32767
  have_job = false
  zone_tripped = false
  motion_stopped = false
  MovP("GL_HOME")
  WriteModbus(REG_FREE, "W", 1)
  print("MISS #" .. miss_count .. " — объект за зоной (R=" .. zone_r .. ")")
end

-- =====================  ОДНО ЗАДАНИЕ (pick-place)  ================
-- Зовётся из Motion. Во время MovL/MovP параллельно крутится Mirror (свежий энкодер,
-- детект стопа). Стоп прерывает ход через MotionStop в Mirror → здесь чекпойнт ловит.
local function run_job()
  if not servo_on then return end                   -- серво выкл — задания не берём
  local enc_now = CVT_GetEncoderPulseCount(CV) or -1
  if enc_now < 0 then return end                    -- лента не готова — подождём след. итерацию

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

  -- пред-полётная зона: цель уже за радиусом досягаемости → MISS, погоню не начинаем
  if zone_r > 0 and (px * px + py * py) > zone_r * zone_r then
    miss_count = (miss_count + 1) % 32767
    have_job = false
    WriteModbus(REG_FREE, "W", 1)
    print("MISS #" .. miss_count .. " — цель за зоной (не начинаем)")
    return
  end

  tracking_active = true
  CVT_VelIn(CV)
  MovL("GL_PICK")                                   -- подвод (Mirror крутится параллельно)
  if stop_mode ~= 0 then handle_stop(); return end
  if zone_tripped then handle_miss(); return end    -- объект ушёл за зону на ходу
  --DO(DO_GRIP, 1)
  DELAY(GRIP_S)
  if stop_mode ~= 0 then handle_stop(); return end
  if zone_tripped then handle_miss(); return end
  CVT_VelOut(CV); tracking_active = false
  MovP("GL_PLACE")
  if stop_mode ~= 0 then handle_stop(); return end
  --DO(DO_GRIP, 0)
  DELAY(GRIP_S)
  if stop_mode ~= 0 then handle_stop(); return end
  MovP("GL_HOME")

  have_job = false
  WriteModbus(REG_FREE, "W", 1)
end

-- =====================  FUNCTION2: MIRROR (параллельная)  =========
-- Крутится ВО ВРЕМЯ хода Motion. Свежий энкодер + детект стопа + MotionStop.
-- ⚠️ НЕТ while/WAIT/DELAY — иначе MultiTask не вернёт управление в Motion.
function Mirror()
  local enc = CVT_GetEncoderPulseCount(CV)
  if enc then WriteModbus(REG_ENC, "DW", enc) end             -- свежий энкодер (кадр-синхрон)

  -- стоп с ПК
  local sm = poll_stop()
  if sm ~= 0 then
    stop_mode = sm
    if not motion_stopped then MotionStop(); motion_stopped = true end  -- прервать ход немедленно
  end

  -- живые координаты робота → телеметрия (поза обновляется в т.ч. В ДВИЖЕНИИ). RobotX/Y в Task2 ОК.
  local rx = RobotX() or 0
  local ry = RobotY() or 0
  WriteModbus(REG_TLM_BASE + 0, "W", clampW(rx * XY_SCALE))   -- 0x1130 X (живой)
  WriteModbus(REG_TLM_BASE + 1, "W", clampW(ry * XY_SCALE))   -- 0x1131 Y

  -- ЗОНА: проверяем ОБЪЕКТ (проекция из энкодера), а НЕ робота. Робот физически не выедет за
  -- свой вылет — RobotX/Y упрётся в предел раньше, чем превысит zone_r. Объект же на ленте
  -- уезжает за зону свободно, и его позиция = job + (enc−E_cap)·F (лента жёсткая).
  if tracking_active and zone_r > 0 and not zone_tripped and enc then
    local t  = (enc - job_enc) * FACTOR_MM
    local ox = job_x + UX * t
    local oy = job_y + UY * t
    if ox * ox + oy * oy > zone_r * zone_r then
      zone_tripped = true
      if not motion_stopped then MotionStop(); motion_stopped = true end
    end
  end
end

-- =====================  FUNCTION1: MOTION (главный цикл)  =========
function Motion()
  while running do
    mirror_encoder()                                -- свежий энкодер и в ПРОСТОЕ (Mirror тут не крутится)

    if stop_mode == 0 then stop_mode = poll_stop() end

    if stop_mode ~= 0 then
      handle_stop()                                 -- может выставить running=false
    elseif ReadModbus(REG_VFD_FLAG, "W") == 1 then
      WriteModbus(REG_VFD_FLAG, "W", 0)
      handle_vfd()
    elseif ReadModbus(REG_CFG_FLAG, "W") == 1 then
      WriteModbus(REG_CFG_FLAG, "W", 0)
      handle_config()
    elseif ReadModbus(REG_SERVO, "W") == 1 then     -- серво ВКЛ
      WriteModbus(REG_SERVO, "W", 0); RobotServoOn();  servo_on = true;  print("SERVO ON")
    elseif ReadModbus(REG_SERVO, "W") == 2 then     -- серво ВЫКЛ (в простое — безопасно)
      WriteModbus(REG_SERVO, "W", 0); RobotServoOff(); servo_on = false; print("SERVO OFF")
    elseif have_job then
      run_job()
    elseif ReadModbus(REG_FLAG, "W") == 1 then      -- приём задания (в простое)
      job_x   = ReadModbus(REG_X, "W") / XY_SCALE
      job_y   = ReadModbus(REG_Y, "W") / XY_SCALE
      job_enc = ReadModbus(REG_ECAP, "DW")
      have_job = true
      WriteModbus(REG_FLAG, "W", 0)
      WriteModbus(REG_FREE, "W", 0)
    else                                            -- истинный простой
      publish_telemetry()
      WriteModbus(REG_FREE, "W", 1)
      DELAY(0.005)                                  -- лёгкий троттлинг busy-loop (~200 Гц)
    end
  end
end

-- =====================  СТАРТ  ====================================
Override(100)
SpdJ(100); AccJ(100); DecJ(100)
SpdL(2000); AccL(25000); DecL(25000)

initCVT()

local rtn = SCM_FreePort(PORT, RS485_RATE, RS485_PROTOCOL, RS485_MODE, 0x1, 0x0, 0x0, 0x00, 0x00)
print("SCM_FreePort rtn = " .. tostring(rtn) .. " (0 = ок)")
DELAY(0.1)
mb_write(VFD_REG_CMD, CMD_STOP)
mb_write(VFD_REG_FREQ, 0)
last_cmd, last_freq = CMD_STOP, 0

RobotServoOn()

have_job = false
WriteModbus(REG_FLAG, "W", 0)
WriteModbus(REG_STOP, "W", 0)
WriteModbus(REG_SERVO, "W", 0)
WriteModbus(REG_FREE, "W", 1)
WriteModbus(REG_VFD_FLAG,  "W", 0)
WriteModbus(REG_CMD_RUN,   "W", 0)
WriteModbus(REG_CMD_DIR,   "W", 0)
WriteModbus(REG_CMD_FREQ,  "W", 0)
WriteModbus(REG_CMD_RESET, "W", 0)
WriteModbus(REG_CFG_FLAG,     "W", 0)
WriteModbus(REG_CFG_BASE + 0, "W", SPD_MOVE)                  -- speed %
WriteModbus(REG_CFG_BASE + 1, "W", iround( 300 * XY_SCALE))  -- home X
WriteModbus(REG_CFG_BASE + 2, "W", iround(-210 * XY_SCALE))  -- home Y
WriteModbus(REG_CFG_BASE + 3, "W", iround( -40 * XY_SCALE))  -- home Z
WriteModbus(REG_CFG_BASE + 4, "W", iround(Z_PICK * XY_SCALE)) -- pick Z
WriteModbus(REG_CFG_BASE + 5, "W", iround( 450 * XY_SCALE))  -- place X
WriteModbus(REG_CFG_BASE + 6, "W", iround(-300 * XY_SCALE))  -- place Y
WriteModbus(REG_CFG_BASE + 7, "W", iround( -90 * XY_SCALE))  -- place Z
WriteModbus(REG_CFG_BASE + 8, "W", iround(GRIP_S * 1000))    -- grip мс
WriteModbus(REG_CFG_BASE + 9, "W", iround(zone_r * XY_SCALE)) -- zone_r (0=выкл)

MovP("GL_HOME", SPD(SPD_MOVE))

print("cvt_universal_MT: старт (MultiTask)")
print("enc=" .. tostring(CVT_GetEncoderPulseCount(CV)))

-- ⚠️ MultiTask: Motion (с движением) — ПЕРВОЙ; Mirror крутится параллельно во время её хода.
--    Motion зациклена внутри (while running) — MultiTask завершится, когда running=false.
running = true
MultiTask(Motion, Mirror)

-- Выход по стопу 2/3:
mb_write(VFD_REG_CMD, CMD_STOP)                     -- привод стоп при выходе
if exit_servo_off then
  RobotServoOff()
  print("СТОП: робот дома, серво OFF")
else
  print("СТОП: робот на месте, серво ON")
end
print("MultiTask завершён — программа остановлена")
