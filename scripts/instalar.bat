@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0.."
echo ==================================================
echo   Instalar UFC Predictor en un entorno local
echo ==================================================
echo.
where py >nul 2>nul
if errorlevel 1 goto python_path
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto python_error
py -3 -m venv .venv
if errorlevel 1 goto error
goto dependencias

:python_path
where python >nul 2>nul
if errorlevel 1 goto python_error
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto python_error
python -m venv .venv
if errorlevel 1 goto error

:dependencias
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error
echo.
echo [OK] Dependencias instaladas en .venv.
echo Para probar sin datos ni modelos: scripts\lanzar_ui.bat --demo
echo Para la interfaz normal: scripts\lanzar_ui.bat
echo La base y los modelos se construyen aparte: consulta README.md.
pause
exit /b 0

:python_error
echo.
echo [ERROR] Instala Python 3.10 o superior desde python.org.
echo Activa el launcher py o la opcion de agregar Python al PATH.
goto fin_error

:error
echo.
echo [ERROR] La instalacion no termino. Revisa el mensaje anterior.
echo Comprueba la conexion y vuelve a ejecutar este archivo.

:fin_error
pause
exit /b 1
