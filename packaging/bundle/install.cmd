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

rem An existing installation (service, program or data) is asked about before anything is stopped or copied;
rem a no changes nothing. A yes deletes it all, database included, and installs from scratch.
set "DATA=%ProgramData%\TiQR"
sc query TiQR >nul 2>&1
if not errorlevel 1 goto :ask
if exist "%TARGET%\tiqr.exe" goto :ask
if exist "%DATA%" goto :ask
goto :fresh
:ask
set "ANSWER="
set /p "ANSWER=TiQR is already installed. Reinstalling deletes the program and all its data, including the database and users, and starts from scratch. Reinstall it? [y/N] "
if /i "%ANSWER%"=="y" goto :confirmed
echo Install cancelled; nothing was changed.
pause
exit /b 1
:confirmed
set "TIQR_REINSTALL_CONFIRMED=1"
:fresh

rem An upgrade replaces the program under a running service; stop it first.
sc query TiQR >nul 2>&1 && net stop TiQR >nul 2>&1
if defined TIQR_REINSTALL_CONFIRMED (
    if /i not "%HERE%"=="%TARGET%\" rd /s /q "%TARGET%" 2>nul
    rd /s /q "%DATA%" 2>nul
)

rem Everything in this folder except the scripts. The branding copied here is only the default for a
rem first install; the installer keeps the one already in the data folder.
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
