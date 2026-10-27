param([string]$ExePath, [string]$ReportPath)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ExePath) { $ExePath = Join-Path $repoRoot 'dist\TelegramFileOrganizer.exe' }
$ExePath = (Resolve-Path -LiteralPath $ExePath).Path
if (-not $ReportPath) {
    $ReportPath = Join-Path $repoRoot ('.test-data\exe-smoke-' + [guid]::NewGuid().ToString('N'))
}
if (Test-Path -LiteralPath $ReportPath) { throw '검증 결과 폴더는 아직 존재하지 않는 새 경로를 지정하세요.' }
$ReportPath = [System.IO.Path]::GetFullPath($ReportPath)
$oldData = $env:TSD_DATA_DIR
$oldPlatform = $env:QT_QPA_PLATFORM
try {
    $env:TSD_DATA_DIR = $ReportPath
    $env:QT_QPA_PLATFORM = 'offscreen'
    $process = Start-Process -FilePath $ExePath -ArgumentList '--smoke-test' -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(30000)) {
        & taskkill.exe /PID $process.Id /T /F | Out-Null
        throw "EXE 시작 검증 시간 초과. 결과 폴더: $ReportPath"
    }
    if ($process.ExitCode -ne 0) { throw "EXE 검증 실패: 종료 코드 $($process.ExitCode). 결과 폴더: $ReportPath" }
    $result = Get-Content -LiteralPath (Join-Path $ReportPath 'smoke-result.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $result.window_created -or $result.smart_tabs -ne 5 -or $result.telegram_started -ne $false -or -not $result.local_mode -or -not $result.folder_picker) {
        throw 'EXE의 오프라인 GUI 검증 결과가 올바르지 않습니다.'
    }
    Write-Output "EXE 오프라인 GUI 검증 통과: $($result.version) / 탭 $($result.smart_tabs)개"
    Write-Output "결과 폴더: $ReportPath"
} finally {
    $env:TSD_DATA_DIR = $oldData
    $env:QT_QPA_PLATFORM = $oldPlatform
}
