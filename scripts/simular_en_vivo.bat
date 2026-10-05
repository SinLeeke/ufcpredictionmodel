@echo off
setlocal
chcp 65001 >nul
rem Este .bat vive en scripts\; el proyecto se ejecuta desde la raiz.
cd /d "%~dp0.."
echo ==================================================
echo   UFC Predictor - mercado en vivo simulado
echo ==================================================
echo.
echo Abre http://127.0.0.1:8010 para probar el grafico de cuotas.
echo Las cuotas simuladas son INVENTADAS y solo viven en memoria.
echo El servidor simulado y la UI normal comparten data\ufc.db y las caches.
echo Evita usar ambas a la vez para cargar carteleras.
echo Deja esta ventana ABIERTA mientras pruebas la simulacion.
echo Para apagar: Ctrl+C aqui, o cierra esta ventana.
echo.
set "UFC_MERCADO_SIMULADO=1"
rem El setlocal limita esta variable a este proceso y sus hijos.
call "%~dp0ejecutar_python.bat" -m webui.server --puerto 8010 %*
if errorlevel 1 goto error
goto fin

:error
echo.
echo El servidor se detuvo. Si no llego a abrir, causas tipicas:
echo   - Faltan dependencias: ejecuta scripts\instalar.bat.
echo   - Falta Python 3.10 o superior en el PATH o el launcher py.
echo   - El puerto 8010 esta ocupado por otro programa.
echo.
exit /b 0

:fin
exit /b 0
