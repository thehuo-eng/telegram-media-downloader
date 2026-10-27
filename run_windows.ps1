$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '먼저 build_windows.ps1을 실행하거나 .venv에 requirements.txt를 설치하세요.'
}
Start-Process -FilePath $pythonPath -ArgumentList @('src\gui.py') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
