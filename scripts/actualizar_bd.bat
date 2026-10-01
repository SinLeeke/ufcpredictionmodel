@echo off
setlocal
chcp 65001 >nul
rem Este .bat vive en scripts\, pero todo el proyecto asume la raiz como
rem directorio de trabajo: los .py hacen "import config" sin tocar sys.path.
cd /d "%~dp0.."
echo ==================================================
echo   Actualizar base de datos y reentrenar el modelo
echo ==================================================
echo.
echo [1/6] Actualizando resultados de UFCStats (rapido, ~1 min)...
echo       Necesario ANTES del paso 5: de aca sale la calidad de oposicion
echo       (ultimas 5 peleas de cada peleador). Sin esto quedaria vieja.
call "%~dp0ejecutar_python.bat" -m src.ufcstats_events
if errorlevel 1 goto error
echo.
echo [2/6] Fichas de UFCStats de quien debuto (altura, alcance, edad)...
call "%~dp0ejecutar_python.bat" -m src.ufcstats_fighters
if errorlevel 1 goto error
echo.
echo [3/6] Estadisticas de las peleas nuevas (golpes, derribos, CONTROL)...
echo       Solo baja las que faltan. De aca sale el control y la defensa real
echo       de cada peleador al predecir.
call "%~dp0ejecutar_python.bat" -m src.ufcstats_fightstats
if errorlevel 1 goto error
echo.
echo [4/6] Actualizando reemplazos (corto aviso) desde Wikipedia...
echo       Solo consulta los eventos nuevos, no rebaja todo.
call "%~dp0ejecutar_python.bat" -m src.reemplazos
if errorlevel 1 goto error
echo.
echo [5/6] Dataset de Kaggle y reconstruccion de features/ELO...
echo       Intenta bajar la version nueva; si no puede (falta kaggle.json o
echo       internet), sigue con la copia que ya hay en vez de borrarla.
call "%~dp0ejecutar_python.bat" -m src.scraper --refrescar-kaggle
if errorlevel 1 goto error
echo.
echo [6/6] Reentrenando modelos (mira las metricas Acc / Log loss / AUC / Brier)...
call "%~dp0ejecutar_python.bat" -m modelado.train_model
if errorlevel 1 goto error
echo.
echo ==================================================
echo   Listo. Modelo y BD actualizados en models\ y data\
echo ==================================================
goto fin

:error
echo.
echo [ERROR] Algo fallo. Revisa el mensaje de arriba.
echo (Suele ser falta de internet o de dependencias: ejecuta scripts\instalar.bat)
pause
exit /b 1

:fin
echo.
pause
exit /b 0
