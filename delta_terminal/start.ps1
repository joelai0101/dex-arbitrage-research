$ErrorActionPreference = 'Stop'
$folder = Get-Item $PSScriptRoot
$python = $null
while ($folder) {
    $candidate = Join-Path $folder.FullName '.venv/Scripts/python.exe'
    if (Test-Path -LiteralPath $candidate) { $python = $candidate; break }
    $folder = $folder.Parent
}
if (-not $python) {
    throw '找不到專案 .venv/Scripts/python.exe；請在 repository 目錄以 Python 執行 -m delta_terminal。'
}
$env:PYTHONIOENCODING = 'utf-8'
Push-Location (Split-Path $PSScriptRoot)
try { & $python -m delta_terminal }
finally { Pop-Location }
