# Установка Subgen: uv, ffmpeg, Python 3.12 (uv), окружение с зависимостями и ярлыки «Subgen».
# Повторный запуск безопасен: уже установленное пропускается, зависимости и ярлыки обновляются.
# install.ps1 -Lang de — язык интерфейса без вопроса (код из subgen\locales: en, ru, de, ja...).
param([string]$Lang)
$ErrorActionPreference = 'Stop'
$Repo = $PSScriptRoot
$Data = Join-Path $env:LOCALAPPDATA 'Subgen'
$Venv = Join-Path $Data 'venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$PyW = Join-Path $Venv 'Scripts\pythonw.exe'

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nОШИБКА: $text" -ForegroundColor Red; exit 1 }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Find-Uv {
    $c = Get-Command uv -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in "$env:USERPROFILE\.local\bin\uv.exe", "$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe") {
        if (Test-Path $p) { return $p }
    }
}
function Find-Ffmpeg {
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { return $true }
    $hits = @(Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg*\*\bin\ffmpeg.exe" -ErrorAction SilentlyContinue)
    return $hits.Count -gt 0
}
$HasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)

Write-Host "Subgen: установка из $Repo"
Write-Host "Окружение и модели: $Data"

Step 'Язык интерфейса / Interface language'
$Langs = @(Get-ChildItem (Join-Path $Repo 'subgen\locales\*.json') | ForEach-Object { $_.BaseName } | Sort-Object)
$Names = @{}
foreach ($c in $Langs) {
    $Names[$c] = (Get-Content -Raw -Encoding UTF8 (Join-Path $Repo "subgen\locales\$c.json") | ConvertFrom-Json).'lang.name'
}
if ($Lang) {
    if ($Langs -notcontains $Lang) { Fail "неизвестный язык / unknown language -Lang $Lang. Есть / available: $($Langs -join ', ')" }
    $UiLang = $Lang
} else {
    $sys = (Get-UICulture).TwoLetterISOLanguageName
    if ($sys -in 'nb', 'nn') { $sys = 'no' } elseif ($sys -eq 'fil') { $sys = 'tl' }
    $UiLang = if ($Langs -contains $sys) { $sys } else { 'en' }
    for ($i = 0; $i -lt $Langs.Count; $i += 3) {  # три колонки, чтобы список влез в окно
        Write-Host (($i..[Math]::Min($i + 2, $Langs.Count - 1) | ForEach-Object {
            ('{0,3}. {1} ({2})' -f ($_ + 1), $Names[$Langs[$_]], $Langs[$_]).PadRight(30) }) -join '')
    }
    $ans = (Read-Host "Номер или код / number or code [Enter = $($Names[$UiLang]) ($UiLang)]")
    if ($ans) { $ans = $ans.Trim().ToLower() }
    if ($ans -match '^\d+$' -and [int]$ans -ge 1 -and [int]$ans -le $Langs.Count) { $UiLang = $Langs[[int]$ans - 1] }
    elseif ($Langs -contains $ans) { $UiLang = $ans }
    elseif ($ans) { Write-Host "не понял «$ans» / not understood — $UiLang" }
}
Write-Host "-> $($Names[$UiLang]) ($UiLang)"

Step 'uv (менеджер Python)'
$Uv = Find-Uv
if ($Uv) {
    Write-Host "уже есть: $Uv"
} else {
    if ($HasWinget) {
        winget install --id astral-sh.uv -e --source winget
        Refresh-Path
        $Uv = Find-Uv
    }
    if (-not $Uv) {
        Write-Host 'winget не помог — ставлю uv официальным скриптом astral.sh'
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        Refresh-Path
        $Uv = Find-Uv
    }
    if (-not $Uv) { Fail 'не удалось установить uv. Установите вручную: https://docs.astral.sh/uv/ и запустите install.cmd снова.' }
}

Step 'ffmpeg'
if (Find-Ffmpeg) {
    Write-Host 'уже есть'
} elseif ($HasWinget) {
    winget install --id Gyan.FFmpeg -e --source winget
    Refresh-Path
    if (-not (Find-Ffmpeg)) { Fail 'ffmpeg не установился. Выполните: winget install --id Gyan.FFmpeg -e' }
} else {
    Fail 'нет winget, поставьте ffmpeg вручную (https://www.gyan.dev/ffmpeg/builds/) и добавьте его в PATH.'
}

Step 'Python 3.12 (управляется uv)'
& $Uv python install 3.12
if ($LASTEXITCODE) { Fail 'uv не смог установить Python 3.12' }

Step 'Окружение Python'
$ok = $false
if (Test-Path $Py) {
    & $Py -c "import sys; assert sys.version_info[:2] == (3, 12)"
    $ok = -not $LASTEXITCODE
}
if ($ok) {
    Write-Host "уже есть: $Venv"
} else {
    New-Item -ItemType Directory -Force $Data | Out-Null
    & $Uv venv --python 3.12 --managed-python --clear $Venv
    if ($LASTEXITCODE) { Fail 'не удалось создать окружение' }
}

Step 'Зависимости (первый раз — около 1,5 ГБ, в основном библиотеки CUDA)'
& $Uv pip install --python $Py -r (Join-Path $Repo 'requirements.txt')
if ($LASTEXITCODE) { Fail 'не удалось установить зависимости' }
& $Py -c "import faster_whisper, ctranslate2, sentencepiece, customtkinter, tkinterdnd2, send2trash"
if ($LASTEXITCODE) { Fail 'зависимости установились, но не импортируются' }

Step 'Настройки / settings'
# через Python программы: остальные настройки сохраняются, файл пишется в UTF-8 без BOM
& $Py -c "import sys; sys.path.insert(0, sys.argv[1]); from subgen import models; models.save_settings(ui_lang=sys.argv[2])" $Repo $UiLang
if ($LASTEXITCODE) { Fail 'не удалось записать settings.json' }
Write-Host "ui_lang = $UiLang"

Step 'Ярлыки'
# WScript.Shell портит кириллицу в путях, поэтому ярлык создаётся через IShellLinkW
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
[ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder f, int c, IntPtr fd, uint fl);
    void GetIDList(out IntPtr p); void SetIDList(IntPtr p);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetHotkey(out short h); void SetHotkey(short h);
    void GetShowCmd(out int i); void SetShowCmd(int i);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c, out int i);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int i);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint r);
    void Resolve(IntPtr h, uint f);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
}
[ComImport, Guid("00021401-0000-0000-C000-000000000046")] class CShellLink {}
public static class SubgenLnk {
    public static void Create(string lnk, string target, string args, string dir, string icon, string desc) {
        var l = (IShellLinkW)new CShellLink();
        l.SetPath(target); l.SetArguments(args); l.SetWorkingDirectory(dir); l.SetIconLocation(icon, 0); l.SetDescription(desc);
        ((System.Runtime.InteropServices.ComTypes.IPersistFile)l).Save(lnk, true);
    }
}
'@
$Icon = Join-Path $Repo 'assets\subgen.ico'
$Gui = Join-Path $Repo 'subgen-gui.pyw'
foreach ($dir in [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) {
    $lnk = Join-Path $dir 'Subgen.lnk'
    [SubgenLnk]::Create($lnk, $PyW, "`"$Gui`"", $Repo, $Icon, 'Subgen — subtitles and translation for video')
    Write-Host $lnk
}

Write-Host "`nГотово. Запускайте «Subgen» с рабочего стола или из меню Пуск; видео можно перетаскивать прямо на ярлык." -ForegroundColor Green
Write-Host 'Модель Whisper (~1,5 ГБ) скачается при первой обработке или на вкладке «Модели».'
