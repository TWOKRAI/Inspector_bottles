@echo off
chcp 65001 >nul
REM Открыть порт 8080 для приёма фото/слова с телефона (phone_gateway).
REM Двойной клик по файлу -> согласиться на запрос прав администратора.

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Запрашиваю права администратора...
  powershell -Command "Start-Process '%~f0' -Verb RunAs"
  exit /b
)

echo Удаляю старое правило (если было)...
netsh advfirewall firewall delete rule name="Phone Gateway 8080" >nul 2>&1

echo Добавляю правило: входящий TCP 8080 разрешён (все профили)...
netsh advfirewall firewall add rule name="Phone Gateway 8080" dir=in action=allow protocol=TCP localport=8080 profile=any

echo.
echo Готово. Правило "Phone Gateway 8080" добавлено.
echo Теперь на телефоне открой http://192.168.1.240:8080/ (или QR).
echo.
pause
