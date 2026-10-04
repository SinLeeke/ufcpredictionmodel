"""Capa común de cuotas: todas las fuentes detrás de una sola interfaz.

La UI consume solo /api/mercado/* (webui/server.py) y nunca sabe de qué fuente
viene cada dato. Contrato: docs/contrato-datos.md, sección 2.

Módulos:
    registro.py     qué fuentes existen (el único lugar que se toca para agregar una)
    fuentes/        una por fuente: betano (pasiva), bfo, odds_api, polymarket
    simulado.py     fuente y evento falsos (UFC_MERCADO_SIMULADO=1)
    cruce.py        nombres de la fuente → ficha de la base, match exacto
    conversion.py   americana / decimal / probabilidad y la Cotización validada
    consenso.py     consenso sin margen, etiquetas, mejor cuota
    historial.py    SQLite: cuotas_historial, cuotas_peleas, cuotas_no_calzados, cuotas_cache
    calendario.py   evento_en_vivo() desde la caché de UFC.com
    capa.py         ingesta, hilos de polling y lecturas para los endpoints
"""
