
-- =====================================================================
--  Delta SCARA · DRAStudio (Lua/RL) — ШАГ 4: мирроринг энкодера + слот задания
--
--  Архитектура (твоя идея «вариант 2», но без round-trip на энкодер):
--    Робот НЕПРЕРЫВНО зеркалит живой энкодер в регистр REG_ENC.
--    ПК в момент КАДРА просто читает REG_ENC → это E_capture (без запроса).
--    ПК копит очередь у себя и отдаёт по одному заданию, когда робот «свободен».
--
--    Поток Mirror (лёгкий, каждый слайс):
--       - зеркалит энкодер в REG_ENC,
--       - выставляет REG_FREE=1, когда слот пуст,
--       - принимает задание {X, Y, E_capture} из регистров в локальный слот.
--    Поток Motion (единственный, кому можно двигаться):
--       - берёт слот, считает сдвиг ленты по энкодеру, едет, освобождает слот.
--
--  ⚠️ Mirror — ПРОХОДНОЙ: без WAIT/DELAY/внутренних while (мануал RL стр. 11-6).
--  ⚠️ Общее состояние (have_job, job_*) — ГЛОБАЛЬНОЕ: делят оба потока.
--
--  Команды: AuxTasksAdd/AuxTasks (11-4), CVT_GetEncoderPulseCount (CVT 21),
--           ReadModbus/WriteModbus DW (12-2/12-3), MovP/SPD.
--
--  PC-сторона: pc_cvt.py — handshake REG_FREE→REG_FLAG, чтение REG_ENC в кадре.
-- =====================================================================

-- =====================  КАРТА РЕГИСТРОВ  ============================
-- Вход задания (ПК пишет, робот читает):
local REG_FLAG = 0x1100        -- W  : 1 = задание в слоте готово (ПК), 0 = принято (робот)
local REG_X    = 0x1101        -- W  : X в 0.1 мм
local REG_Y    = 0x1102        -- W  : Y в 0.1 мм
local REG_ECAP = 0x1104        -- DW : E_capture — энкодер в момент кадра (чётный адрес!)
-- Выход состояния (робот пишет, ПК читает):
local REG_FREE = 0x1110        -- W  : 1 = робот свободен (слот пуст), 0 = занят
local REG_ENC  = 0x1112        -- DW : живой энкодер, робот зеркалит каждый слайс (чётный!)
-- Эхо принятых/вычисленных координат (робот пишет, ПК читает командой last):
local REG_ECHO_X = 0x1120      -- W  : принятый job_x (0.1 мм)
local REG_ECHO_Y = 0x1121      -- W  : принятый job_y
local REG_PX     = 0x1122      -- W  : вычисленный px = job_x + UX*trav (0.1 мм)
local REG_PY     = 0x1123      -- W  : вычисленный py
local REG_TRAV   = 0x1124      -- W  : сдвиг ленты trav (0.1 мм)

-- =====================  КАЛИБРОВКА / ГЕОМЕТРИЯ  ====================
local CV        = 1            -- группа конвейера (= CVID в CVT_Initialization)
local FACTOR_MM = 0.144473     -- пульсы → мм (из шаблона: cvtFactor 144473/1000 = 144.473 мкм/пульс)
local UX, UY    = 0, 1         -- единичный вектор ленты (cmpstVector 0,1000 → лента вдоль +Y)
local XY_SCALE  = 10.0         -- регистр W → мм (0.1 мм)

-- =====================  ТОЧКИ / ТАЙМИНГИ  =========================
local Z_PICK   = -100         -- высота захвата
local SPD_MOVE = 60            -- % скорость
local GRIP_S   = 2         -- отстой захвата, c
local DO_GRIP  = 1             -- DO захвата
local POSTURE  = {0,0,0,0,0,0,0,4}
-- Аргументы 4-axis: (Point, Name, X, Y, Z, RZ, Hand, UF, TF, JRC). Hand=1 → ЛЕВАЯ рука.
SetGlobalPoint(90, "GL_HOME",  300, -210, -40,    -100, 1, 0, 0, POSTURE)
SetGlobalPoint(91, "GL_PLACE", 450, -300, -90,    -100, 1, 0, 0, POSTURE)
-- GL_PICK ОБЪЯВЛЯЕМ здесь (координаты-заглушка); в Motion меняем только X/Y через WritePoint.
SetGlobalPoint(80, "GL_PICK",  300, -210, Z_PICK, -100, 1, 0, 0, POSTURE)

-- =====================  ОБЩЕЕ СОСТОЯНИЕ (глобалы)  =================
have_job = false               -- занят ли слот задания
job_x, job_y, job_enc = 0, 0, 0


-- =====================  ИНИЦИАЛИЗАЦИЯ CVT  =========================
-- ⚠️ БЕЗ CVT_Initialization функции CVT_GetEncoderPulseCount/CVT_VelIn = -1.
--    Это «Wizard в коде». Параметры — из твоего рабочего шаблона (show.md).
local function initCVT()
  CVT_ChangeMotion()                              -- режим CVT-движения
  local CVID = CV
  CVT_SelectMode(CVID, 2)                         -- 1:со зрением 2:без зрения
  CVT_SetTriggerMode(CVID, 2)                     -- 1:DO trigger 2:DI sensor trigger

  -- Encoder Unit Ratio (фактор энкодера)
  local cvtFactor_num = 144473
  local cvtFactor_den = 1000
  local interval      = 10                        -- Encoder AMF window (ms)
  -- CCD & Robot Transform Offset (um) — для зрения, в режиме 2 не важны
  local trans_ccd_x, trans_ccd_y, rotat_ccd_c = 0, 0, 0
  -- CCD Unit Ratio
  local vuPix2UmNum, vuPix2UmDen = 10, 1
  local vuAgRatioNum, vuAgRatioDen = 10, 1
  local vuXYExchgFlag = 0
  -- Вектор направления ленты относительно робота
  local cmpstVectorX, cmpstVectorY, cmpstVectorZ = 0, 1000, 0
  -- CV parameters
  local srcType, srcIdx = 1, 1
  local cvtUFIdx = 1
  local NGZoneRadius = 20000                      -- um
  -- Trigger Line
  local robotTrigLinePX, robotTrigLinePY = 334631, -381077
  local robotTrigLine = CVT_CalRobotTrigLine(robotTrigLinePX, robotTrigLinePY, cmpstVectorX, cmpstVectorY)
  -- End Line
  local zoneEndPX, zoneEndPY = 334631, -200000
  local zoneEndLine = CVT_CalZoneEndLine(zoneEndPX, zoneEndPY, cmpstVectorX, cmpstVectorY)
  -- Advance
  local cvtuIdx = 1
  local CV_instSlotIdx = 1
  local instType, instIdx = 2, 1
  cvtFactor_den = cvtFactor_den * interval        -- den *= interval (как в шаблоне)
  local vuIdx = 1
  local CRotatSwFlag = 0                          -- 0:C вращается 1:C фикс
  CVT_SetUserDefineDI(1, 2)

  CVT_Initialization(cvtuIdx, instType, instIdx, srcType, srcIdx,
    cvtFactor_num, cvtFactor_den, interval, cmpstVectorX, cmpstVectorY, cmpstVectorZ, cvtUFIdx,
    trans_ccd_x, trans_ccd_y, rotat_ccd_c, vuIdx, vuPix2UmNum, vuPix2UmDen, vuAgRatioNum, vuAgRatioDen,
    vuXYExchgFlag, CRotatSwFlag, NGZoneRadius, zoneEndLine, robotTrigLine, CV_instSlotIdx)
end

-- =====================  ПОТОК 2: MIRROR (проходной)  ==============
function Mirror()
  -- 1) зеркалим живой энкодер — ПК читает его в момент кадра как E_capture
  WriteModbus(REG_ENC, "DW", CVT_GetEncoderPulseCount(CV))

  if not have_job then
    -- 2) приём нового задания, если ПК выставил флаг
    if ReadModbus(REG_FLAG, "W") == 1 then
      job_x   = ReadModbus(REG_X, "W") / XY_SCALE
      job_y   = ReadModbus(REG_Y, "W") / XY_SCALE
      job_enc = ReadModbus(REG_ECAP, "DW")        -- энкодер на момент кадра (от ПК)
      have_job = true

      WriteModbus(REG_FLAG, "W", 0)               -- квитируем приём
      WriteModbus(REG_FREE, "W", 0)               -- больше не свободен
    else
      WriteModbus(REG_FREE, "W", 1)               -- слот пуст → сообщаем «свободен»
    end
  end
  -- НЕТ while/WAIT/DELAY → отдаём слайс мотиону
end

-- =====================  ПОТОК 1: MOTION  ==========================
function Motion()
  if not have_job then return end                 -- нет задания — уступаем

  -- guard: лента стоит → энкодер = -1 → trav был бы мусором → рука улетит. Ждём.
  local enc_now = CVT_GetEncoderPulseCount(CV)
  if enc_now < 0 then return end

  -- сдвиг ленты от кадра до СЕЙЧАС: энкодер посчитал весь путь, что бы ни задержалось
  local trav = (enc_now - job_enc) * FACTOR_MM
  local px = job_x + UX * trav
  local py = job_y + UY * trav

  -- обратная связь на ПК: что принято и что вычислено (команда last / авто-печать)
  WriteModbus(REG_ECHO_X, "W", job_x * XY_SCALE)
  WriteModbus(REG_ECHO_Y, "W", job_y * XY_SCALE)
  WriteModbus(REG_PX,     "W", px * XY_SCALE)
  WriteModbus(REG_PY,     "W", py * XY_SCALE)
  WriteModbus(REG_TRAV,   "W", trav * XY_SCALE)

  -- меняем ТОЛЬКО координаты заранее объявленной GL_PICK (один item за вызов)
  WritePoint("GL_PICK", "X", px)
  WritePoint("GL_PICK", "Y", py)

  CVT_VelIn(CV)

  MovL("GL_PICK")                   -- подвод над объектом
  --DO(DO_GRIP, 1)
  DELAY(GRIP_S)

  CVT_VelOut(CV)

  MovP("GL_PLACE")                  -- укладка
  --DO(DO_GRIP, 0)
  DELAY(GRIP_S)
  MovP("GL_HOME")                   -- домой

  have_job = false                                 -- слот свободен (Mirror выставит FREE=1)
end



-- =====================  СТАРТ  =====================================

Override(100)     -- глобально 100%
SpdJ(100)
SpdL(2000)        -- макс линейная скорость
AccL(25000)       -- макс ускорение
DecL(25000)       -- макс замедление

initCVT()                                          -- ← полная инициализация CVT-группы
RobotServoOn()

have_job = false
WriteModbus(REG_FLAG, "W", 0)
WriteModbus(REG_FREE, "W", 1)                      -- стартуем «свободны»
MovP("GL_HOME", SPD(SPD_MOVE))

print('hello')
print(CVT_GetEncoderPulseCount(1))

AuxTasksAdd(Motion, Mirror)                        -- Motion первым (только он двигается)
while 1 do
  AuxTasks()
end

-- =====================================================================
--  СИНХРОН С ЛЕНТОЙ (для движущейся ленты) — вставить в Motion перед DO_GRIP:
--    CVT_VelIn(CV)                       -- захватить скорость ленты (родной CVT)
--    MovL("GL_PICK", SPD(SPD_MOVE))      -- спуск на захват «на ходу»
--    DO(DO_GRIP, 1); DELAY(GRIP_S)
--    MovL("GL_PICK", SPD(SPD_MOVE))      -- подъём
--    CVT_VelOut(CV)                      -- отпустить синхрон
--  Тогда рука едет вместе с лентой и время подвода не вносит ошибку.
--  Без этого блока шаг 4 корректен для стоящей/медленной ленты и как демо
--  архитектуры (мирроринг + слот + энкодер-стамп).
-- =====================================================================
