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
# Каждый процесс открывается в своём окне PowerShell — там же его лог.
# Остановка: закрыть окно прототипа, Ctrl+C в окне «line_sim», закрыть окно робота.
#
# Что важно знать:
#  - окно GUI даёт только вход multiprocess_prototype/frontend/run.py; вход
#    multiprocess_prototype/run.py — бэкенд без окна (урок памяти «GUI-стенд боевым входом»);
#  - окно робота v2 — отдельный симулятор в своём процессе; робот линии (Modbus 5021),
#    которым управляет прототип, пока на протоколе v1 и окна не имеет (связка v2 — T3.5);
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

function Start-Window([string]$Title, [string]$EnvLine, [string]$PyArgs) {
    $cmd = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location '$Root'; $EnvLine; & '$Py' $PyArgs"
    Start-Process powershell -ArgumentList @("-NoExit", "-NoProfile", "-Command", $cmd) | Out-Null
    Write-Host "запущено: $Title"
}

# 0. Ассеты сима: data/ не в git, собираем из фикстур репозитория, если их нет
#    (рецепты — apps/line_sim/pipeline.yaml у background_layers и Services/line_sim/presets/README.md)
Set-Location $Root
$SimData = Join-Path $Root "data\line_sim"
New-Item -ItemType Directory -Force $SimData | Out-Null
if (-not (Test-Path (Join-Path $SimData "belt_tile.png"))) {
    Write-Host "собираю тайл ленты data\line_sim\belt_tile.png"
    Copy-Item "Services\line_sim\tests\fixtures\belt_photo_full.png" (Join-Path $SimData "belt_photo_full.png")
    & $Py -m Services.line_sim.tools.make_seamless_texture data/line_sim/belt_photo_full.png --out data/line_sim/belt_tile.png --force-period --gap-alpha
    if ($LASTEXITCODE) { throw "тайл ленты не собрался" }
}
if (-not (Test-Path (Join-Path $SimData "letters_ink"))) {
    Write-Host "собираю каталог букв data\line_sim\letters_ink"
    $Fonts = Join-Path (& $Py -c "import matplotlib; print(matplotlib.get_data_path())") "fonts\ttf"
    foreach ($F in "DejaVuSans", "DejaVuSansMono") {
        & $Py -m Services.line_sim.tools.make_font_letters --letters "АКРХ" --font (Join-Path $Fonts "$F.ttf") `
            --stroke-px 3 --size-px 300 --letter-frac 0.4763 --ink-rgb 65,70,82 --grain-sigma 9 --edge-blur-px 1 --seed 1 `
            --disk-from-photo Services/line_sim/tests/fixtures/real_disk_snapshot.png `
            --out data/line_sim/letters_ink --disk-out data/line_sim/letters_ink_disk.png
        if ($LASTEXITCODE) { throw "каталог букв не собрался ($F)" }
    }
}

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
Write-Host "Логи: $Logs\prototype и $Logs\line_sim"
