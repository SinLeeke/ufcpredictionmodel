@echo off
setlocal
rem Python comun para los BAT: funciona al doble clic y desde otra carpeta.
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" goto entorno_local
where py >nul 2>nul
if not errorlevel 1 goto launcher
python %*
exit /b %errorlevel%

:entorno_local
".venv\Scripts\python.exe" %*
exit /b %errorlevel%

:launcher
py -3 %*
exit /b %errorlevel%
