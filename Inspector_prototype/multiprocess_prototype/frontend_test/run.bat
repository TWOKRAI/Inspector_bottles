@echo off
REM Запуск теста только фронтенда (без процессов и бэкенда)
cd /d "%~dp0..\.."
set PYTHONPATH=%CD%;%CD%\multiprocess_framework\refactored\modules
python multiprocess_prototype\frontend_test\main.py
