@echo off
rem Installs TiQR as a Windows service from this folder. Double-click, or run it from a terminal.
rem The program is copied to %ProgramFiles%\TiQR. Settings and data stay in %ProgramData%\TiQR, which
rem the program uses by default, so an upgrade never touches them. Then `tiqr install` sets up the
rem address, database, first admin, firewall, service and health probe.
setlocal
set "HERE=%~dp0"
set "TARGET=%ProgramFiles%\TiQR"

net session >nul 2>&1
if errorlevel 1 (
    echo Needs administrator rights; asking Windows to elevate.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b
)

rem An existing installation (service, program or data) is asked about before anything is stopped or copied.
rem The first question is reinstall or update. An update keeps the database, settings and license and
rem replaces only the program; a reinstall deletes it all, database included, and starts from scratch.
set "DATA=%ProgramData%\TiQR"
sc query TiQR >nul 2>&1
if not errorlevel 1 goto :ask
if exist "%TARGET%\tiqr.exe" goto :ask
if exist "%DATA%" goto :ask
goto :fresh
:ask
set "ANSWER="
echo TiQR is already installed. Is this a reinstall or an update?
echo   update    keeps the database, users, settings and license; only the program is replaced
echo   reinstall deletes the program and all its data, including the database and users
set /p "ANSWER=Type update, reinstall, or anything else to cancel [update/reinstall/N] "
if /i "%ANSWER%"=="update" goto :update
if /i "%ANSWER%"=="u" goto :update
if /i "%ANSWER%"=="reinstall" goto :sure
if /i "%ANSWER%"=="r" goto :sure
goto :cancel
:sure
set "SURE="
set /p "SURE=This deletes all data, including the database and users. Continue? [y/N] "
if /i "%SURE%"=="y" goto :confirmed
:cancel
echo Install cancelled; nothing was changed.
pause
exit /b 1
:update
set "TIQR_UPDATE_CONFIRMED=1"
goto :fresh
:confirmed
set "TIQR_REINSTALL_CONFIRMED=1"
:fresh

rem An upgrade replaces the program under a running service; stop it first.
sc query TiQR >nul 2>&1 && net stop TiQR >nul 2>&1
if defined TIQR_REINSTALL_CONFIRMED (
    if /i not "%HERE%"=="%TARGET%\" rd /s /q "%TARGET%" 2>nul
    rd /s /q "%DATA%" 2>nul
)

rem Everything in this folder except the scripts. The branding copied here is applied to the data
rem folder by the installer, which keeps the file it replaces as tiqr_brand.jsonc.bak.
set "SKIP=install.cmd install.sh"
robocopy "%HERE%." "%TARGET%" /XF %SKIP% /NFL /NDL /NJH /NJS /NP
if errorlevel 8 (
    echo Copying to %TARGET% failed.
    pause
    exit /b 1
)

cd /d "%TARGET%"
tiqr.exe install %*
set "CODE=%ERRORLEVEL%"
echo.
pause
exit /b %CODE%
