@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==================================================
echo   Predecir una cartelera de UFC
echo ==================================================
echo.
echo Sugerencia: para usar stats frescos, borra la cache antes:
echo   del data\raw\ufcstats_cache.json
echo.
if "%~1"=="" (
    echo Sin CSV indicado -^> uso la cartelera por defecto ^(Ankalaev vs Guskov^).
    echo Para otra: arrastra un CSV encima de este .bat, o corre:
    echo   python -m src.card cards\mi_evento.csv
    echo.
    python -m src.card
) else (
    echo Cartelera: %~1
    echo.
    python -m src.card "%~1"
)
if errorlevel 1 goto error
echo.
echo ==================================================
echo   Listo. Resultados en la carpeta outputs\
echo ==================================================
goto fin

:error
echo.
echo [ERROR] Algo fallo. Revisa el mensaje de arriba.
echo (Si no hay modelo entrenado, corre primero actualizar_bd.bat)

:fin
echo.
pause
