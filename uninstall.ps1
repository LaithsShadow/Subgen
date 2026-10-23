# Удаление Subgen: ярлыки и окружение Python. С ключом -All (или ответом «y») — ещё модели и настройки.
param([switch]$All)
$ErrorActionPreference = 'Stop'
$Data = Join-Path $env:LOCALAPPDATA 'Subgen'

foreach ($dir in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) {
    $lnk = Join-Path $dir 'Subgen.lnk'
    if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "удалён ярлык $lnk" }
}
$venv = Join-Path $Data 'venv'
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv; Write-Host "удалено окружение $venv" }

if (-not $All -and (Test-Path $Data)) {
    $All = (Read-Host "Удалить также скачанные модели и настройки ($Data)? [y/N]") -match '^(y|д)'
}
if ($All -and (Test-Path $Data)) { Remove-Item -Recurse -Force $Data; Write-Host "удалено $Data" }
Write-Host 'Готово. Папку с программой (где лежит этот файл), uv и ffmpeg можно удалить вручную.'
