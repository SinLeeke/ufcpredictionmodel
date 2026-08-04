@echo off
chcp 65001 >nul
rem Este .bat vive en scripts\, pero todo el proyecto asume la raiz como
rem directorio de trabajo: los .py hacen "import config" sin tocar sys.path.
cd /d "%~dp0.."
echo ==================================================
echo   Actualizar base de datos y reentrenar el modelo
echo ==================================================
echo.
echo [1/5] Borrando dataset viejo para forzar descarga nueva...
if exist "data\raw\kaggle_ufc.csv" del "data\raw\kaggle_ufc.csv"
echo.
echo [2/5] Actualizando resultados de UFCStats (rapido, ~1 min)...
echo       Necesario ANTES del paso 3: de aca sale la calidad de oposicion
echo       (ultimas 5 peleas de cada peleador). Sin esto quedaria vieja.
python -m src.ufcstats_events
if errorlevel 1 goto error
echo.
echo [3/5] Actualizando reemplazos (corto aviso) desde Wikipedia...
echo       Solo consulta los eventos nuevos, no rebaja todo.
python -m src.reemplazos
if errorlevel 1 goto error
echo.
echo [4/5] Descargando dataset actualizado y reconstruyendo features/ELO...
python -m src.scraper
if errorlevel 1 goto error
echo.
echo [5/5] Reentrenando modelos (mira las metricas Acc / Log loss / AUC / Brier)...
python -m modelado.train_model
if errorlevel 1 goto error
echo.
echo ==================================================
echo   Listo. Modelo y BD actualizados en models\ y data\
echo ==================================================
goto fin

:error
echo.
echo [ERROR] Algo fallo. Revisa el mensaje de arriba.
echo (Suele ser falta de internet o de dependencias: pip install -r requirements.txt)

:fin
echo.
pause
