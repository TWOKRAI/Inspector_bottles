# Idempotent setup для qex embedding-модели на Windows: форсирует 100% GPU.
# См. setup-embedding-model.sh для подробностей. PowerShell-эквивалент для Win-юзеров,
# у которых нет Git Bash.
#
# Usage: powershell -ExecutionPolicy Bypass -File setup-embedding-model.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Modelfile = Join-Path $ScriptDir "templates\qwen3-embedding-0.6b-win.Modelfile"
$Base = "qwen3-embedding:0.6b"
$Variant = "qwen3-embedding:0.6b-qex"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Error "ollama не найдена в PATH. Установи Ollama и перезапусти."
    exit 1
}

try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
} catch {
    Write-Error "ollama сервер не отвечает на :11434. Запусти Ollama Desktop."
    exit 1
}

$Tags = (ollama list) -join "`n"
if ($Tags -notmatch "qwen3-embedding\s+0\.6b") {
    Write-Host "-> pulling $Base (первый запуск)..."
    ollama pull $Base
}

Write-Host "-> создаю GPU-оптимизированный вариант $Variant"
ollama create $Variant -f $Modelfile

Write-Host "-> прогрев $Variant"
$Body = @{ model = $Variant; prompt = "warm-up" } | ConvertTo-Json
Invoke-WebRequest -Uri "http://localhost:11434/api/embeddings" -Method POST -Body $Body -ContentType "application/json" -UseBasicParsing | Out-Null

Write-Host ""
ollama ps
Write-Host ""
Write-Host "OK. qex-launcher грузит $Variant напрямую — правки кода не нужны."
Write-Host "PROCESSOR должен быть '100% GPU'. Если 'CPU' — проверь VRAM (nvidia-smi)."
