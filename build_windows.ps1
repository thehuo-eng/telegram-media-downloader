param([switch]$SkipInstall, [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 가상환경 생성 실패' }
}
if (-not $SkipInstall) {
    & $pythonPath -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw '의존성 설치 실패' }
}
if (-not $SkipTests) {
    & $pythonPath -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw '테스트 실패: 빌드를 중단합니다.' }
}
& $pythonPath -m PyInstaller --noconfirm TelegramSmartDownloader.spec
if ($LASTEXITCODE -ne 0) { throw 'EXE 빌드 실패' }
$exePath = Join-Path $PSScriptRoot 'dist\TelegramSmartDownloader.exe'
& (Join-Path $PSScriptRoot 'tools\verify_exe.ps1') -ExePath $exePath
$exeInfo = Get-Item -LiteralPath $exePath
$exeHash = Get-FileHash -LiteralPath $exePath -Algorithm SHA256
[PSCustomObject]@{ Path = $exeInfo.FullName; Bytes = $exeInfo.Length; Modified = $exeInfo.LastWriteTime; SHA256 = $exeHash.Hash } | Format-List
