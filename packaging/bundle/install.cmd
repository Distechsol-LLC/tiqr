@echo off
rem Installs TiQR as a Windows service from this folder. Double-click, or run it from a terminal.
rem The folder is copied to %ProgramFiles%\TiQR (data and settings there survive an upgrade), then
rem `tiqr install` sets up the address, database, first admin, firewall and service.
setlocal
set "HERE=%~dp0"
set "TARGET=%ProgramFiles%\TiQR"

net session >nul 2>&1
if errorlevel 1 (
    echo Needs administrator rights; asking Windows to elevate.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    exit /b
)

rem An upgrade replaces the program under a running service; stop it first.
sc query TiQR >nul 2>&1 && net stop TiQR >nul 2>&1

rem Everything in this folder except the scripts. A reinstall keeps the branding already edited.
set "SKIP=install.cmd install.sh"
if exist "%TARGET%\tiqr_brand.jsonc" set "SKIP=%SKIP% tiqr_brand.jsonc"
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
