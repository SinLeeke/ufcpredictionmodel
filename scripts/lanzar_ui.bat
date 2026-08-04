@echo off
chcp 65001 >nul
rem Este .bat vive en scripts\, pero todo el proyecto asume la raiz como
rem directorio de trabajo: los .py hacen "import config" sin tocar sys.path.
cd /d "%~dp0.."
echo ==================================================
echo   UFC Predictor - interfaz web
echo ==================================================
echo.
echo Abriendo http://127.0.0.1:8000 en el navegador.
echo Deja esta ventana ABIERTA mientras uses la UI.
echo Para cerrar: Ctrl+C aqui, o cierra esta ventana.
echo.
python -m webui.server
if errorlevel 1 goto error
goto fin

:error
echo.
echo [ERROR] No arranco. Causas tipicas:
echo   - Faltan dependencias:  pip install -r requirements.txt
echo   - El puerto 8000 esta ocupado por otro programa.
echo.
pause

:fin
