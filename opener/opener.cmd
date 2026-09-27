@echo off
rem task-os opener — the per-PC handler behind the taskos:// URL scheme.
rem
rem   Windows hands it the whole URL the folder chip carried:
rem       taskos://open?ref=%7Bonedrive%7D%2Fhouse%2Fkitchen     (also taskos://open/<ref>)
rem   It URL-decodes the ref, expands the placeholders from what THIS PC knows,
rem   flips the slashes and opens the folder in Explorer (a file opens with its
rem   default app). When the path is not synced on this PC it says so — visibly —
rem   and shows the resolved path to copy. Pure cmd, so it runs where script
rem   files (.ps1) are blocked; no admin, no Python.
rem
rem   Placeholders:
rem       {onedrive}            %OneDriveCommercial% when set, else %OneDrive%
rem       {user}                %USERNAME%
rem       {sharepoint:<name>}   the "<name>=<path>" line in %LOCALAPPDATA%\task-os\opener.env
rem                             (a "<name>=<path>" line also overrides {<name>} — e.g. onedrive=D:\OneDrive)
rem   Env knobs (tests): TASKOS_OPENER_DRYRUN=1 prints "open: <path>" / "missing: <path>"
rem   / "refused: <path>" instead of launching anything; TASKOS_OPENER_ENV overrides
rem   the opener.env location.
rem
rem   What it opens: a folder on this PC, or a document on this PC with its default
rem   app. A ref that names another computer (\\host\...) before any placeholder is
rem   expanded, or a file Windows would run rather than open (the NOOPEN list below,
rem   plus %PATHEXT%), is refused visibly, exit 6. A placeholder this PC maps in
rem   opener.env may still point at a share - that value is this PC's own config.
rem
rem   Known limits: a "!" inside a path is lost (delayed expansion). A percent
rem   sequence outside the decoded set (accented letters, %C3%A9) hands the whole job
rem   to ONE inline PowerShell command (same rules; still no script file).
setlocal EnableExtensions EnableDelayedExpansion
title task-os opener
rem one list for both branches (the inline PowerShell one reads it from the env)
set "NOOPEN=.exe;.com;.bat;.cmd;.pif;.scr;.cpl;.msc;.msi;.msp;.mst;.hta;.js;.jse;.vbs;.vbe;.wsf;.wsh;.wsc;.sct;.ps1;.psm1;.psd1;.ps1xml;.psc1;.lnk;.url;.website;.reg;.inf;.scf;.jar;.application;.appref-ms;.gadget;.library-ms;.settingcontent-ms;.search-ms;.searchconnector-ms;.diagcab;.appx;.appxbundle;.msix;.msixbundle;.appinstaller;.chm;.hlp;.xbap;.xll;.iso;.img;.vhd;.vhdx;.rdp;.theme;.themepack;.desktopthemepackfile;%PATHEXT%"

rem ---- 0. where the URL comes from ----------------------------------------
rem opener.ps1 (the registered launcher) passes it in TASKOS_OPENER_URL, never on
rem a command line: a URL on a command line is re-parsed by cmd, and a quote inside
rem it starts a second command (task-os#40). !VAR! expansion is never re-tokenised,
rem so this route cannot. %* stays for a direct call - the tests, a manual run, the
rem fallback registration - where the quotes cmd wraps the argument in are stripped
rem as before (%* not %1: an unquoted "=" would split the URL into two arguments).
if defined TASKOS_OPENER_URL (
  set "URL=!TASKOS_OPENER_URL!"
  set "VIAPS=1"
) else (
  set "URL=%*"
  set "VIAPS="
)
if not defined VIAPS if defined URL set "URL=!URL:"=!"
if not defined URL (
  echo   task-os opener: no URL given. Usage: opener.cmd "taskos://open?ref=%%7Bonedrive%%7D%%2Ffolder"
  exit /b 2
)

rem Via the launcher the URL arrives bare, so a quote in it is not framing - it is
rem a link the app never built (every ref it makes is percent-encoded). Refuse it
rem visibly instead of stripping it and opening whatever is left. This is a second
rem gate, not the mitigation: opener.ps1 has already refused, and on the fallback
rem registration cmd has already re-parsed the string before this line runs.
rem (!VAR! is substituted after the line is parsed, so a quote inside the value
rem cannot unbalance this comparison the way a %VAR% one would)
rem This whole block only runs when VIAPS is defined (the goto above skips it
rem otherwise), i.e. only via the launcher - which is headless now (task-os#130).
rem No pause: opener.ps1 captures this echoed text and pops it up on exit 3.
if not defined VIAPS goto :url_ready
set "NOQ=!URL:"=!"
if not "!NOQ!"=="!URL!" (
  echo.
  echo   task-os opener
  echo.
  echo   This link carries a quote character, which the app never sends.
  echo   Nothing was opened.
  echo.
  exit /b 3
)
:url_ready
rem taskos://resume needs PowerShell (transcript search + terminal launch, #77);
rem reaching it here means the machine runs the fallback .cmd registration.
rem (goto + top-level exits: an `exit /b N` inside an if-block does not
rem propagate its code through the registration's `cmd.exe /c` wrapper)
if /i "!URL:~0,15!"=="taskos://resume" goto :resume_fallback
set "ENVFILE=%TASKOS_OPENER_ENV%"
if not defined ENVFILE set "ENVFILE=%LOCALAPPDATA%\task-os\opener.env"

rem ---- 1. the ref part of the URL -----------------------------------------
set "REF=!URL!"
if /i "!REF:~0,17!"=="taskos://open?ref" set "REF=!REF:*ref=!"
if /i "!REF:~0,18!"=="taskos://open/?ref" set "REF=!REF:*ref=!"
if /i "!REF:~0,14!"=="taskos://open/" set "REF=!REF:~14!"
if /i "!REF:~0,9!"=="taskos://" set "REF=!REF:~9!"
if /i "!REF:~0,7!"=="taskos:" set "REF=!REF:~7!"
rem "*ref=" above stops at the "=" separator, so the "=" itself is still there
if "!REF:~0,1!"=="=" set "REF=!REF:~1!"
set "RAW=!REF!"

rem ---- 2. URL-decode (pure cmd; %25 last so an encoded percent is not re-decoded)
set "REF=!REF:%%20= !"
set "REF=!REF:%%23=#!"
set "REF=!REF:%%26=&!"
set "REF=!REF:%%27='!"
set "REF=!REF:%%28=(!"
set "REF=!REF:%%29=)!"
set "REF=!REF:%%2B=+!"
set "REF=!REF:%%2C=,!"
set "REF=!REF:%%2F=/!"
set "REF=!REF:%%3A=:!"
set "REF=!REF:%%3B=;!"
set "REF=!REF:%%3D==!"
set "REF=!REF:%%40=@!"
set "REF=!REF:%%5B=[!"
set "REF=!REF:%%5C=\!"
set "REF=!REF:%%5D=]!"
set "REF=!REF:%%7B={!"
set "REF=!REF:%%7D=}!"
set "REF=!REF:%%7E=~!"
set "REF=!REF:%%25=%%!"
rem anything still encoded (an accented letter: %C3%A9) is beyond what cmd can decode
rem byte-safely, so ONE inline PowerShell command (no script file) finishes the whole
rem job — decode, the same placeholder rules, open or notice — in a single process
set "PROBE=%TEMP%\task-os-opener-%RANDOM%.txt"
>"%PROBE%" echo(!REF!
findstr /r /c:"%%[0-9A-Fa-f][0-9A-Fa-f]" "%PROBE%" >nul 2>&1
set "STILL=%ERRORLEVEL%"
del "%PROBE%" >nul 2>&1
if "%STILL%"=="0" (
  powershell -NoProfile -NonInteractive -Command "if([Console]::IsOutputRedirected){[Console]::OutputEncoding=[Text.Encoding]::UTF8}; $q=[char]34; $n=[Environment]::NewLine; function Refuse($p){ if($env:TASKOS_OPENER_DRYRUN){ Write-Output ('refused: '+$p); exit 0 }; Write-Host ($n+'  task-os opener'+$n+$n+'  The opener only opens folders and documents on this PC,'+$n+'  and this link points somewhere else:'+$n+$n+'      '+$p+$n+$n+'  Nothing was opened.'+$n); if(-not $env:VIAPS){ Read-Host 'Press Enter to close' | Out-Null }; exit 6 }; $r=[uri]::UnescapeDataString($env:RAW); if($r.Contains($q)){ Write-Host ($n+'  task-os opener'+$n+$n+'  This link carries a quote character, which the app never sends.'+$n+'  Nothing was opened.'+$n); if(-not $env:TASKOS_OPENER_DRYRUN -and -not $env:VIAPS){ Read-Host 'Press Enter to close' | Out-Null }; exit 3 }; $d=$r.Replace('/','\'); if($d.StartsWith('\\')){ Refuse $d }; $f=$env:ENVFILE; if($f -and (Test-Path -LiteralPath $f)){ Get-Content -LiteralPath $f | ForEach-Object { if($_ -match '^\s*([^#=][^=]*?)\s*=(.*)$'){ $k=[regex]::Escape($matches[1]); $v=[Environment]::ExpandEnvironmentVariables($matches[2]).Replace('$','$$'); $r=$r -replace ('(?i)\{sharepoint:'+$k+'\}'),$v -replace ('(?i)\{'+$k+'\}'),$v } } }; $od=$env:OneDriveCommercial; if(-not $od){$od=$env:OneDrive}; if($od){$r=$r -replace '(?i)\{onedrive\}',$od.Replace('$','$$')}; if($env:USERNAME){$r=$r -replace '(?i)\{user\}',$env:USERNAME}; $r=$r.Replace('/','\'); if($r -notmatch '^[A-Za-z]:\\$'){$r=$r.TrimEnd('\')}; $deny=@($env:NOOPEN -split ';' | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ }); function Runs($p){ try { $x=[IO.Path]::GetFullPath($p) } catch { return $true }; if($x.IndexOf(':',2) -ge 0){ return $true }; return ($deny -contains [IO.Path]::GetExtension($x.TrimEnd('. ')).ToLower()) }; if(Test-Path -LiteralPath $r -PathType Container){ if($env:TASKOS_OPENER_DRYRUN){ 'open: '+$r; exit 0 }; Start-Process explorer.exe -ArgumentList ($q+$r+$q); exit 0 }; if(Test-Path -LiteralPath $r){ if(Runs $r){ Refuse $r }; if($env:TASKOS_OPENER_DRYRUN){ 'open: '+$r; exit 0 }; Start-Process -LiteralPath $r; exit 0 }; if($env:TASKOS_OPENER_DRYRUN){ 'missing: '+$r; exit 0 }; Write-Host ($n+'  task-os opener'+$n+$n+'  This folder is not synced on this PC, or a placeholder is missing:'+$n+$n+'      '+$r+$n+$n+'  Copy the path above, sync the folder here, or add its placeholder to'+$n+'      '+$f+$n+'  - one name=path line per placeholder'+$n); if(-not $env:VIAPS){ Read-Host 'Press Enter to close' | Out-Null }; exit 1"
  exit /b !ERRORLEVEL!
)

rem ---- 3. placeholders from what this PC knows ----------------------------
rem Every ref the app builds starts at a placeholder or a drive letter, so one
rem that already names another computer is refused before anything touches it.
set "DEC=!REF:/=\!"
if "!DEC:~0,2!"=="\\" (
  set "REF=!DEC!"
  goto :refused
)
rem opener.env first: "name=path" → {sharepoint:name} and {name} (so it can override {onedrive}/{user});
rem a value may use %VARS% (call expands them once)
if exist "%ENVFILE%" for /f "usebackq eol=# tokens=1* delims==" %%A in ("%ENVFILE%") do (
  call set "VAL=%%B"
  if defined VAL for /f "delims=" %%V in ("!VAL!") do (
    set "REF=!REF:{sharepoint:%%A}=%%V!"
    set "REF=!REF:{%%A}=%%V!"
  )
)
set "OD=%OneDriveCommercial%"
if not defined OD set "OD=%OneDrive%"
if defined OD set "REF=!REF:{onedrive}=%OD%!"
if defined USERNAME set "REF=!REF:{user}=%USERNAME%!"
set "REF=!REF:/=\!"
rem drop a trailing backslash (not on a drive root)
if "!REF:~-1!"=="\" if not "!REF:~-2!"==":\" set "REF=!REF:~0,-1!"

rem ---- 4. open, or say why not -------------------------------------------
rem (goto + top-level exits, as for resume: a non-zero exit /b inside a block
rem does not reach the fallback registration's cmd.exe /c wrapper)
if exist "!REF!\" goto :open_folder
if not exist "!REF!" goto :missing
rem A file goes to its default app only when that app opens it rather than runs
rem it. %%~f normalises first: Windows drops trailing dots and spaces from a name,
rem so "x.exe." is x.exe, and a colon past the drive is not a plain file name.
for %%F in ("!REF!") do set "FULL=%%~fF"
set "TAIL=!FULL:~2!"
if not "!TAIL::=!"=="!TAIL!" goto :refused
set "EXT="
for %%F in ("!FULL!") do set "EXT=%%~xF"
rem (";" separates the items of a for set, so the list iterates as it is)
if defined EXT for %%E in (!NOOPEN!) do if /i "!EXT!"=="%%E" goto :refused
if defined TASKOS_OPENER_DRYRUN (
  echo open: !REF!
  exit /b 0
)
start "" "!REF!"
exit /b 0

:open_folder
if defined TASKOS_OPENER_DRYRUN (
  echo open: !REF!
  exit /b 0
)
start "" explorer "!REF!"
exit /b 0

:missing
if defined TASKOS_OPENER_DRYRUN (
  echo missing: !REF!
  exit /b 0
)
echo.
echo   task-os opener
echo.
echo   This folder is not synced on this PC (or a placeholder is missing):
echo.
echo       !REF!
echo.
echo   Copy the path above, sync the folder here, or add its placeholder to
echo       %ENVFILE%
echo   (one "name=path" line per placeholder, e.g. docs=C:\Users\me\Tenant\docs)
echo.
rem via the launcher (VIAPS) opener.ps1 captures this text and pops it up
rem instead - a paused console here would be invisible (task-os#130)
if not defined VIAPS pause
exit /b 1

:refused
if defined TASKOS_OPENER_DRYRUN echo refused: !REF!
if defined TASKOS_OPENER_DRYRUN exit /b 0
echo.
echo   task-os opener
echo.
echo   The opener only opens folders and documents on this PC,
echo   and this link points somewhere else:
echo.
echo       !REF!
echo.
echo   Nothing was opened.
echo.
if not defined VIAPS pause
exit /b 6

:resume_fallback
if defined TASKOS_OPENER_DRYRUN echo resume-unsupported
if defined TASKOS_OPENER_DRYRUN exit /b 5
echo.
echo   task-os opener
echo.
echo   Resuming a session needs the PowerShell opener, which this PC's
echo   policy blocked at install time. Open the conversation link instead.
echo.
if not defined VIAPS pause
exit /b 5
