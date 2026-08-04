"""
modelado
Los scripts del ciclo del modelo: entrenarlo, medirlo y validarlo contra el
pasado. Se corren a mano, no se importan desde `src/`.

    modelado/
      train_model.py         entrena ganador + método (y el modelo de medición)
      evaluar_modelo.py      acierto fuera de muestra y calibración por tramo
      backtest_valor.py      walk-forward del mercado de GANADOR
      backtest_metodo.py     walk-forward del mercado de MÉTODO
      backtest_carteleras.py replay de carteleras reales, peleador por peleador

Los dos primeros backtests **no son solo tests**: dejan `calibrador_mercado.pkl`,
`calibrador_metodo.pkl` y `metodo6_xgb.pkl` en `models/`.

CÓMO SE CORREN — con `-m` y desde la raíz del repo:

    python -m modelado.train_model

Y NO `python modelado/train_model.py`. La diferencia importa: con la ruta suelta
Python pone `modelado/` al frente de `sys.path` y `import config` revienta,
porque `config.py` vive en la raíz. Con `-m` el que entra a `sys.path` es el
directorio de trabajo, que es justo lo que estos scripts asumen.

Este paquete no exporta nada a propósito: importarlo no debe disparar el
entrenamiento ni cargar pandas.
"""
