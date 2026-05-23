# Idempotent setup для qex embedding-модели на Windows: форсирует 100% GPU.
# См. setup-embedding-model.sh для подробностей. PowerShell-эквивалент для Win-юзеров,
# у которых нет Git Bash.
#
# Usage: powershell -ExecutionPolicy Bypass -File setup-embedding-model.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Modelfile = Join-Path $ScriptDir "templates\qwen3-embedding-4b-win.Modelfile"
$Base = "qwen3-embedding:4b"
$Variant = "qwen3-embedding:4b-qex"

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
if ($Tags -notmatch "qwen3-embedding\s+4b") {
    Write-Host "-> pulling $Base (первый запуск)..."
    ollama pull $Base
}

Write-Host "-> создаю GPU-оптимизированный вариант $Variant"
ollama create $Variant -f $Modelfile

Write-Host "-> подменяю $Base на $Variant"
ollama stop $Base 2>$null
ollama rm $Base 2>$null
ollama cp $Variant $Base

Write-Host "-> прогрев"
$Body = @{ model = $Base; prompt = "warm-up" } | ConvertTo-Json
Invoke-WebRequest -Uri "http://localhost:11434/api/embeddings" -Method POST -Body $Body -ContentType "application/json" -UseBasicParsing | Out-Null

Write-Host ""
ollama ps
Write-Host ""
Write-Host "OK. PROCESSOR должен быть '100% GPU'. Если 'CPU' — проверь VRAM (nvidia-smi)."
