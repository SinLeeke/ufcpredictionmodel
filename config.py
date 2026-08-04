"""
config.py
Configuración central del proyecto: rutas, constantes del sistema ELO,
clases de peso y parámetros de scraping. Todo se importa desde aquí para
que no haya "números mágicos" dispersos por el código.
"""
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Consola Windows
# --------------------------------------------------------------------------- #
# La consola de Windows usa cp1252, que no sabe imprimir nombres como
# 'Błachowicz' o 'Ľudovít' y lanza UnicodeEncodeError a mitad de una corrida.
# Se fuerza UTF-8 tolerante: si un carácter no se puede representar, se
# reemplaza en vez de tirar todo el programa.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"
MODELS = ROOT / "models"

for _p in (DATA_RAW, DATA_PROCESSED, OUTPUTS, MODELS):
    _p.mkdir(parents=True, exist_ok=True)

# Archivos canónicos que van fluyendo por el pipeline
FIGHTERS_CSV = DATA_PROCESSED / "fighters.csv"      # 1 fila por peleador (stats de carrera)
FIGHTS_CSV = DATA_PROCESSED / "fights.csv"          # 1 fila por pelea histórica (para entrenar)
FEATURES_CSV = DATA_PROCESSED / "features.csv"      # dataset diferencial listo para el modelo

WINNER_MODEL = MODELS / "winner_xgb.pkl"
METHOD_MODEL = MODELS / "method_xgb.pkl"

# Modelo de MEDICIÓN del ganador. Es el de la primera fase de train_model.py: se
# entrena solo con <= TRAIN_END_DATE, así que 2025+ le es desconocido y se puede
# evaluar sobre esas peleas sin mentir. WINNER_MODEL, en cambio, se reentrena con
# TODO el historial (incluido 2025-2026) porque para PREDECIR conviene, pero
# medirlo sobre 2025+ da ~80% de acierto que es dentro de muestra y no significa
# nada. Este .pkl lo lee evaluar_modelo.py y nadie más: nunca se usa para predecir.
WINNER_MODEL_SPLIT = MODELS / "winner_xgb_split.pkl"
ELO_TABLE = DATA_PROCESSED / "elo_ratings.csv"

# --------------------------------------------------------------------------- #
# Scraping
# --------------------------------------------------------------------------- #
# Headers "de navegador" y delays para hacer scraping educado (respeta robots.txt).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_DELAY_SEC = 1.5          # pausa entre requests para no gatillar rate-limits
REQUEST_TIMEOUT_SEC = 20
MAX_RETRIES = 3

UFCSTATS_BASE = "http://ufcstats.com"
SHERDOG_BASE = "https://www.sherdog.com"
TAPOLOGY_BASE = "https://www.tapology.com"
BETANO_BASE = "https://lat.betano.com"

# Dataset de contingencia / entrenamiento en Kaggle (ver scraper.py -> load_from_kaggle).
# Usamos 'mdabbert/ultimate-ufc-dataset' porque:
#   * se ACTUALIZA (llega a 2026) -> el Time-Based Split tiene test set real (métricas).
#   * trae columna 'finish' -> permite entrenar el modelo de MÉTODO (KO/Sub/Dec).
# Nota: NO trae stats de golpes ABSORBIDOS por el rival (avg_opp_*), así que
# SApM/Str.Def/TD.Def caen a default en el entrenamiento (documentado en kaggle_ingest).
# La predicción EN VIVO sí usa esos stats reales vía UFCStats.
KAGGLE_DATASET = "mdabbert/ultimate-ufc-dataset"
# Alternativa clásica (más vieja, sin método, sin 2025): "rajeevw/ufcdata"

# --------------------------------------------------------------------------- #
# Sistema ELO
# --------------------------------------------------------------------------- #
ELO_BASE = 1500.0        # rating inicial de un peleador que debuta
ELO_K = 32.0             # sensibilidad del ajuste por pelea
ELO_FINISH_BONUS = 1.10  # multiplicador de K cuando la victoria es por finalización (KO/Sub)

# Categorías de peso (el ELO se calcula por categoría para no mezclar poblaciones)
WEIGHT_CLASSES = [
    "Flyweight", "Bantamweight", "Featherweight", "Lightweight",
    "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight",
    "Women's Strawweight", "Women's Flyweight",
    "Women's Bantamweight", "Women's Featherweight",
    "Catch Weight", "Open Weight",
]

# --------------------------------------------------------------------------- #
# Modelado
# --------------------------------------------------------------------------- #
# Corte temporal para el Time-Based Split (evita data leakage).
TRAIN_END_DATE = "2024-12-31"   # entrena con <= esta fecha
TEST_START_DATE = "2025-01-01"  # testea con >= esta fecha

# VENTANA DE ENTRENAMIENTO, en años hacia atrás desde el final del set.
# El MMA cambia: pelear en 2012 y en 2024 no es el mismo deporte, y las peleas
# viejas meten patrones que ya no aplican. Hay un trade-off entre MÁS datos
# (ir atrás) y datos MÁS RELEVANTES (quedarse cerca).
#
# Medido sobre el test 2025+ (AUC): desde 2010 0,7140 | 2016 0,7155 |
# 2018 0,7207 | 2020 0,7245 | 2022 0,7172 (acá ya escasean los datos).
# Validado en 5 períodos distintos, la ventana de 5 años le gana a usar TODO el
# historial en 4 de 5 (media +0,0117 de AUC):
#     2021 +0,0136 | 2022 +0,0065 | 2023 −0,0013 | 2024 +0,0293 | 2025 +0,0105
# Poner None usa todo el historial.
TRAIN_WINDOW_YEARS = 5

RANDOM_STATE = 42

# Clases del modelo de método de victoria
METHOD_CLASSES = ["KO/TKO", "Submission", "Decision"]

# Tasa base de cada método (frecuencia real en el set de entrenamiento, 13.082
# peleas hasta 2024). Sirve para leer la predicción del modelo como LIFT: decir
# "Decisión 52%" no informa nada porque la mitad de las peleas terminan así; lo
# informativo es "KO 45%" cuando la base es 31% (= 1,5x más finalizable que la
# pelea promedio). El modelo de método está calibrado (ver train_model.py), así
# que estas tasas y sus probabilidades son directamente comparables.
METHOD_BASE_RATES = {"KO/TKO": 0.308, "Submission": 0.177, "Decision": 0.515}

# Nº de simulaciones Monte Carlo
N_SIMULATIONS = 10_000
