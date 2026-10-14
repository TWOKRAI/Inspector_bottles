# Стенд «посмотреть симулятор» одной командой, по порядку:
#   1) прототип с окном GUI на лёгком рецепте pult_demo (камеры и робота нет — ждёт);
#   2) линия: лента + камера + пульт (apps/line_sim);
#   3) окно робота v2;
#   4) старт — вы сами: в прототипе вкладка «Рецепты» → letter_robot_sim → «Сделать активным»
#      (GUI выбирает рецепт, оркестратор применяет топологию — принцип 6 владельца).
#
# Запуск из корня репо (PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\run_sim_all.ps1
# Ключи: -Recipe <имя>, -NoPrototype, -NoRobotView, -NoBrowser, -TimeoutSec 90
#   -Recipe pult_demo — порядок выше: прототип ждёт, рецепт вы активируете сами;
#   -Recipe letter_robot_sim (по умолчанию) — сначала симуляторы, затем прототип сразу на сим-рецепте
#     (обход: горячая замена «Сделать активным» на 2026-10-12 роняет камеру и устройства).
#
# Каждый процесс открывается в своём окне PowerShell — там же его лог; копия консоли окна —
# data\logs\console\<окно>_<время>.log.
# Остановка: закрыть окно прототипа, Ctrl+C в окне «line_sim», закрыть окно робота.
#
# Что важно знать:
#  - окно GUI даёт только вход multiprocess_prototype/frontend/run.py; вход
#    multiprocess_prototype/run.py — бэкенд без окна (урок памяти «GUI-стенд боевым входом»);
#  - окно робота v2 — отдельный симулятор в своём процессе; робот линии (Modbus 5021),
#    которым управляет прототип, на протоколе v2 (T3.7), но в этом окне не виден (T3.8);
#  - запуск и выбор рецепта в GUI записывают рецепт в multiprocess_prototype/app.yaml —
#    вернуть: git checkout -- multiprocess_prototype/app.yaml
param(
    [string]$Recipe = "letter_robot_sim",
    [switch]$NoPrototype,
    [switch]$NoRobotView,
    [switch]$NoBrowser,
    [int]$TimeoutSec = 90
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "Нет $Py — сначала создайте venv проекта" }
$Logs = Join-Path $Root "data\logs"

function Test-Port([int]$Port) {
    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect("127.0.0.1", $Port); return $true } catch { return $false } finally { $client.Close() }
}

function Wait-Port([int]$Port, [string]$What) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Port $Port) { Write-Host "  готово: $What (:$Port)"; return }
        Start-Sleep -Milliseconds 500
    }
    throw "За $TimeoutSec с не открылся порт $Port ($What) — смотрите окно процесса"
}

# Консоль каждого окна дублируется в файл data\logs\console\<окно>_<время>.log (UTF-8):
# туда попадает то, что идёт мимо логгера — print, stderr нативных библиотек (ffmpeg, Qt),
# traceback процесса, упавшего до старта логгера. Дочерние процессы наследуют тот же поток.
$ConsoleDir = Join-Path $Logs "console"
New-Item -ItemType Directory -Force $ConsoleDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

function Start-Window([string]$Title, [string]$EnvLine, [string]$PyArgs) {
    $ConsoleLog = Join-Path $ConsoleDir "${Title}_$Stamp.log"
    $tee = "`$env:PYTHONUNBUFFERED='1'; `$env:PYTHONIOENCODING='utf-8'; [Console]::OutputEncoding = [Text.Encoding]::UTF8; " +
        "`$w = New-Object IO.StreamWriter('$ConsoleLog', `$true, (New-Object Text.UTF8Encoding `$false)); `$w.AutoFlush = `$true; " +
        "& '$Py' $PyArgs 2>&1 | ForEach-Object { `$s = [string]`$_; Write-Host `$s; `$w.WriteLine(`$s) }; `$w.Close()"
    $cmd = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location '$Root'; $EnvLine; $tee"
    Start-Process powershell -ArgumentList @("-NoExit", "-NoProfile", "-Command", $cmd) | Out-Null
    Write-Host "запущено: $Title (консоль: $ConsoleLog)"
}

# 0. Ассеты сима: data/ не в git, собираем из фикстур репозитория, если их нет
#    (рецепты — apps/line_sim/pipeline.yaml у background_layers и Services/line_sim/presets/README.md)
Set-Location $Root
& $Py -m Services.line_sim.tools.build_stand_assets
if ($LASTEXITCODE) { throw "ассеты сима не собрались" }

# Прототип с окном GUI (backend_ctl на 8765); вход frontend/run.py — единственный с окном
function Start-Prototype {
    if (-not $NoPrototype) {
        if (Test-Port 8765) {
            Write-Host "прототип уже работает (порт 8765 занят) — не запускаю второй"
        } else {
            Start-Window "prototype" "`$env:BACKEND_CTL='1'; `$env:MULTIPROCESS_LOG_DIR='$Logs\prototype'" "multiprocess_prototype\frontend\run.py $Recipe"
            Wait-Port 8765 "бэкенд прототипа"
        }
    }
}

$Waits = ($Recipe -eq "pult_demo")

# 1. Прототип первым — только в режиме ожидания (pult_demo)
if ($Waits) { Start-Prototype }

# 2. Линия: robot (Modbus 5021), camera, mjpeg (8091), pult (8092); backend_ctl на 8766
if (Test-Port 8091) {
    Write-Host "line_sim уже работает (порт 8091 занят) — не запускаю второй"
} else {
    Start-Window "line_sim" "`$env:BACKEND_CTL='1'; `$env:BACKEND_CTL_PORT='8766'; `$env:MULTIPROCESS_LOG_DIR='$Logs\line_sim'" "apps\line_sim\run.py"
    Wait-Port 5021 "робот линии, Modbus"
    Wait-Port 8091 "видео ленты, MJPEG"
}
Wait-Port 8092 "веб-пульт"

# 2б. Прототип после симуляторов — когда рецепт задан сразу
if (-not $Waits) { Start-Prototype }

# 3. Окно робота v2 (вид сверху, Z, RZ) — отдельный симулятор
if (-not $NoRobotView) {
    Start-Window "robot_v2_view" "`$env:PYTHONPATH='$Root'" "-m Services.robot_comm.gui.sim_view"
}

# 4. Пульт линии в браузере
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:8092/" }

Write-Host ""
if ($Waits) { Write-Host "Всё поднято. Старт: в окне прототипа вкладка «Рецепты» -> letter_robot_sim -> «Сделать активным»." }
else { Write-Host "Всё поднято. Прототип работает на рецепте $Recipe." }
Write-Host "Пульт линии: http://127.0.0.1:8092/   видео ленты: http://127.0.0.1:8091/"
Write-Host "Логи: $Logs\prototype и $Logs\line_sim; консоль окон: $ConsoleDir"
