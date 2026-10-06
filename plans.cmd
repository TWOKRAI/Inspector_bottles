@echo off
setlocal
chcp 65001 >nul
REM Страница прогресса планов: собрать и открыть в браузере.
REM Из корня проекта: PowerShell ".\plans", cmd "plans", или двойной клик.
REM Аргументы идут в plans_progress.py как есть: ".\plans --active-window 12h".
REM Справка по ключам: scripts\plans_progress\README.md

cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PAGE=data\plans_progress.html"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" scripts\plans_progress\plans_progress.py --html "%PAGE%" %*
if errorlevel 1 (
  echo.
  echo Страница не собрана, код %errorlevel%.
  pause
  exit /b 1
)

echo Страница: %CD%\%PAGE%
start "" "%PAGE%"
