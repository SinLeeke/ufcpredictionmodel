@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==================================================
echo   Bajar datos de UFCStats (fuente oficial, al dia)
echo ==================================================
echo.
echo [1/3] Historial de eventos y resultados...
python -m src.ufcstats_events
if errorlevel 1 goto error
echo.
echo [2/3] Biometria de cada peleador (altura, alcance, fecha de nacimiento)...
echo       Sin esto, edad/alcance/altura quedan en 0 en las features.
python -m src.ufcstats_fighters
if errorlevel 1 goto error
echo.
echo [3/3] Estadisticas de cada pelea (golpes, derribos, CONTROL)...
echo       Esto tarda ~20-25 min la primera vez.
echo       Puedes cortar con Ctrl+C: al volver a correrlo sigue donde quedo.
echo.
python -m src.ufcstats_fightstats
if errorlevel 1 goto error
echo.
echo ==================================================
echo   Listo. Datos en data\processed\
echo ==================================================
goto fin

:error
echo.
echo [ERROR] Algo fallo. Revisa el mensaje de arriba (internet?).
echo Si se corto a mitad, vuelve a correrlo: retoma donde quedo.

:fin
echo.
pause
