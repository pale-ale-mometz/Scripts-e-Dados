# schedule_clevertap_export.ps1 — wrapper para o Agendador (mesmo padrão do schedule_controle_2026.ps1: a ação em cmd.exe
# quebrava com aspas + caminho com "Álex"). Fica na MESMA pasta do clevertap_export.py e do .env (Scripts e Dados).
# Tarefa "gt7 clevertap_export": diário 10:20 (depois do clevertap.gs das 09:45), StartWhenAvailable, limite 2 h.
#   powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "<esta pasta>\schedule_clevertap_export.ps1"
param([string]$Modo = "daily", [string[]]$Extra = @())
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py   = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$log  = Join-Path $root ("out\logs\clevertap_export_" + (Get-Date -Format "yyyyMMdd") + ".log")
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"   # stdout redirecionado cai em cp1252 e o "→" do log derrubava o run
[Console]::OutputEncoding = [Text.Encoding]::UTF8   # para o pipe do PowerShell ler o UTF-8 do Python sem "ÔåÆ"
"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Modo $Extra ===" | Out-File -Append -Encoding utf8 $log
& $py (Join-Path $root "clevertap_export.py") $Modo @Extra 2>&1 | Out-File -Append -Encoding utf8 $log
"exit $LASTEXITCODE" | Out-File -Append -Encoding utf8 $log
exit $LASTEXITCODE
