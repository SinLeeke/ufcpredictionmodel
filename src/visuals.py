"""
visuals.py
FASE 4b — Visualización de datos.

Dos gráficos con Plotly:
  1) Donut de probabilidad de victoria A vs B (con el intervalo creíble en el
     subtítulo).
  2) Barras apiladas comparando cómo terminan históricamente las peleas de A y
     de B, más una barra 'Proyección' con la distribución de método simulada
     para ESTE combate (KO/TKO, Sub, Decisión).

Se exporta a HTML (interactivo) y, si tienes kaleido instalado, a PNG.
"""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

import sys
sys.path.append(str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import config as C
from src.simulate import SimulationResult

# Paleta coherente
COLOR_A = "#d64541"   # rojo (esquina roja / peleador A)
COLOR_B = "#2c6fbb"   # azul (esquina azul / peleador B)
COLOR_METHOD = {"KO/TKO": "#e74c3c", "Submission": "#8e44ad", "Decision": "#7f8c9b"}
FONT = "Arial, Helvetica, sans-serif"


def _short(name: str) -> str:
    """'Magomed Ankalaev' -> 'M. Ankalaev' para etiquetas cortas y legibles."""
    parts = name.split()
    return f"{parts[0][0]}. {parts[-1]}" if len(parts) > 1 else name


def donut_win_probability(sim: SimulationResult) -> go.Figure:
    """Anillo de probabilidad de victoria: % grandes, nombres en leyenda, favorito al centro."""
    fig = go.Figure(
        go.Pie(
            labels=[_short(sim.fighter_a), _short(sim.fighter_b)],
            values=[sim.p_a, sim.p_b],
            hole=0.60,
            marker=dict(colors=[COLOR_A, COLOR_B], line=dict(color="white", width=3)),
            texttemplate="%{percent:.0%}",     # solo el % dentro de la dona (grande)
            textposition="outside",
            textfont=dict(size=22, family=FONT),
            pull=[0.04 if sim.p_a >= sim.p_b else 0, 0.04 if sim.p_b > sim.p_a else 0],
            sort=False,
            direction="clockwise",
            hovertemplate="%{label}: %{percent:.1%}<extra></extra>",
        )
    )
    fig.update_layout(
        annotations=[
            dict(text=f"<b>{_short(sim.winner)}</b>", x=0.5, y=0.56,
                 font=dict(size=17, family=FONT, color="#222"), showarrow=False),
            dict(text="favorito", x=0.5, y=0.44,
                 font=dict(size=12, family=FONT, color="#777"), showarrow=False),
        ],
        legend=dict(orientation="h", y=-0.05, x=0.5, xanchor="center",
                    font=dict(size=13, family=FONT)),
        template="plotly_white",
        margin=dict(t=20, b=20, l=20, r=20),
    )
    return fig


def stacked_methods(sim: SimulationResult,
                    hist_a: dict[str, float],
                    hist_b: dict[str, float]) -> go.Figure:
    """
    Barras 100% apiladas: cómo termina históricamente A, cómo termina B, y la
    proyección simulada para ESTE combate. Etiquetas de % dentro de cada segmento.
    """
    categories = [_short(sim.fighter_a), _short(sim.fighter_b), "Proyección<br>(este combate)"]
    fig = go.Figure()
    for method in C.METHOD_CLASSES:
        vals = [hist_a.get(method, 0), hist_b.get(method, 0), sim.method_dist.get(method, 0)]
        fig.add_bar(
            name=method,
            x=categories,
            y=vals,
            marker_color=COLOR_METHOD[method],
            text=[f"{v*100:.0f}%" if v >= 0.08 else "" for v in vals],  # oculta % diminutos
            textposition="inside",
            textfont=dict(size=13, color="white", family=FONT),
            insidetextanchor="middle",
            hovertemplate="%{x} · " + method + ": %{y:.0%}<extra></extra>",
        )
    fig.update_layout(
        barmode="stack",
        yaxis=dict(title="", tickformat=".0%", range=[0, 1], showgrid=False),
        xaxis=dict(tickfont=dict(size=13, family=FONT)),
        template="plotly_white",
        legend=dict(orientation="h", y=-0.12, x=0.5, xanchor="center",
                    font=dict(size=13, family=FONT)),
        margin=dict(t=20, b=20, l=40, r=20),
    )
    return fig


def build_report(sim: SimulationResult,
                 hist_a: dict[str, float],
                 hist_b: dict[str, float],
                 filename: str = "fight_report",
                 include_plotlyjs: bool | str = True) -> str:
    """
    Combina ambos gráficos en un HTML claro y lo guarda en outputs/.
    include_plotlyjs=True  -> HTML autocontenido (~5 MB, se ve sin internet).
    include_plotlyjs='cdn' -> HTML liviano (~10 KB, requiere internet al abrir).
                              Útil al generar un reporte por pelea de una cartelera.
    """
    combo = make_subplots(
        rows=1, cols=2,
        specs=[[{"type": "domain"}, {"type": "xy"}]],
        subplot_titles=("<b>Probabilidad de victoria</b>",
                        "<b>Cómo termina la pelea</b>"),
        horizontal_spacing=0.14,
    )
    for tr in donut_win_probability(sim).data:
        tr.showlegend = False   # los nombres ya salen en subtítulo y eje; evita choque de colores
        combo.add_trace(tr, row=1, col=1)
    for tr in stacked_methods(sim, hist_a, hist_b).data:
        combo.add_trace(tr, row=1, col=2)

    # anotaciones del donut (favorito al centro) — recolocadas para el subplot izquierdo
    combo.add_annotation(text=f"<b>{_short(sim.winner)}</b>", x=0.19, y=0.55,
                         xref="paper", yref="paper", showarrow=False,
                         font=dict(size=16, family=FONT, color="#222"))
    combo.add_annotation(text="favorito", x=0.19, y=0.46,
                         xref="paper", yref="paper", showarrow=False,
                         font=dict(size=11, family=FONT, color="#777"))

    ci = f"IC 95%: {sim.ci_a[0]*100:.0f}–{sim.ci_a[1]*100:.0f}%"
    subtitle = (f"{_short(sim.fighter_a)} {sim.p_a*100:.0f}%  ·  "
                f"{_short(sim.fighter_b)} {sim.p_b*100:.0f}%   |   "
                f"termina antes del límite {sim.p_finish*100:.0f}%  ·  "
                f"a las tarjetas {sim.p_decision*100:.0f}%   |   {ci}")

    combo.update_layout(
        barmode="stack",
        template="plotly_white",
        title=dict(
            text=f"<b>UFC — {sim.fighter_a} vs {sim.fighter_b}</b><br>"
                 f"<span style='font-size:13px;color:#666'>{subtitle}</span>",
            x=0.5, xanchor="center", y=0.95, font=dict(size=20, family=FONT),
        ),
        legend=dict(orientation="h", y=-0.08, x=0.78, xanchor="center",
                    font=dict(size=12, family=FONT)),
        font=dict(family=FONT),
        margin=dict(t=95, b=60, l=40, r=40),
        height=520,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    combo.update_yaxes(tickformat=".0%", range=[0, 1], showgrid=False, col=2)
    # subtítulos de los subplots un poco más abajo para que no choquen con el título
    for ann in combo.layout.annotations[:2]:
        ann.font = dict(size=15, family=FONT, color="#333")

    # 'filename' puede traer subcarpetas (p.ej. "evento/pelea") -> se crean solas
    out_html = C.OUTPUTS / f"{filename}.html"
    out_html.parent.mkdir(parents=True, exist_ok=True)
    combo.write_html(str(out_html), include_plotlyjs=include_plotlyjs)
    print(f"[ok] reporte -> {out_html}")
    try:
        combo.write_image(str(C.OUTPUTS / f"{filename}.png"), width=1200, height=520, scale=2)
    except Exception:
        pass  # requiere kaleido; el HTML ya quedó guardado
    return str(out_html)
