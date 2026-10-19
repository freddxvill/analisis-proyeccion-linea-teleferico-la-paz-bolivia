"""Estilo de gráficos compartido por notebooks y sitio.

Las líneas del teleférico se identifican por su color oficial (el nombre de la línea
*es* un color), así que se usan como paleta categórica de identidad. Dos ajustes de
legibilidad sobre fondo claro: Amarilla se oscurece un poco y Blanca se dibuja como
gris claro con borde oscuro (como en los gráficos oficiales). Como varios pares no son
separables con daltonismo (Roja/Naranja/Café), la identidad nunca va solo por color:
siempre hay etiqueta directa o leyenda, y con muchas líneas se usan small multiples.
"""

import matplotlib as mpl

# Color oficial (route_color del GTFS).
COLOR_OFICIAL = {
    "Roja": "#e40613", "Amarilla": "#ffed03", "Verde": "#0b983a", "Azul": "#26348d",
    "Naranja": "#ea5b0d", "Blanca": "#ffffff", "Celeste": "#009fe3", "Morada": "#82358c",
    "Café": "#683b12", "Plateada": "#9c9aa0",
}
# Color para marcas sobre fondo claro.
COLOR_LINEA = COLOR_OFICIAL | {"Amarilla": "#e8c400", "Blanca": "#d9d9d9", "Plateada": "#8a8890"}
BORDE_LINEA = {"Blanca": "#333333"}
# En gráficos de líneas (trazo fino) la Blanca se dibuja oscura, como en el PDF oficial.
TRAZO_LINEA = COLOR_LINEA | {"Blanca": "#333333"}

# Neutros y rampa secuencial (azul) de la paleta de referencia.
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
TINTA_3 = "#8a8985"
GRILLA = "#e6e5e1"
SUPERFICIE = "#fcfcfb"
ACENTO = "#2a78d6"
SECUENCIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

ORDEN_LINEAS = ["Roja", "Amarilla", "Verde", "Azul", "Naranja", "Blanca",
                "Celeste", "Morada", "Café", "Plateada"]


def estilo() -> None:
    mpl.rcParams.update({
        "figure.facecolor": SUPERFICIE,
        "axes.facecolor": SUPERFICIE,
        "savefig.facecolor": SUPERFICIE,
        "figure.dpi": 110,
        "font.size": 10,
        "axes.edgecolor": GRILLA,
        "axes.labelcolor": TINTA_2,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlecolor": TINTA,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRILLA,
        "grid.linewidth": 0.8,
        "xtick.color": TINTA_2,
        "ytick.color": TINTA_2,
        "lines.linewidth": 2,
        "legend.frameon": False,
    })


def num(x: float, dec: int = 1) -> str:
    """Número con formato español: punto de miles y coma decimal (12.345,6)."""
    return f"{x:,.{dec}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def millones(x, _pos=None) -> str:
    return f"{x / 1e6:,.0f} M".replace(",", ".")


def miles(x, _pos=None) -> str:
    return f"{x / 1e3:,.0f} mil".replace(",", ".")


def fmt_int(x: float) -> str:
    """Entero con separador de miles español (punto)."""
    return f"{x:,.0f}".replace(",", ".")


def barras_lineas(ax, lineas, valores, **kw):
    """Barras horizontales coloreadas por línea, con borde para la Blanca."""
    colores = [COLOR_LINEA[l] for l in lineas]
    bordes = [BORDE_LINEA.get(l, c) for l, c in zip(lineas, colores)]
    return ax.barh(lineas, valores, color=colores, edgecolor=bordes, linewidth=1, **kw)


def guardar(fig, nombre: str) -> None:
    """Guarda la figura en reports/figures (para README y presentaciones)."""
    from teleferico.config import ROOT

    out = ROOT / "reports" / "figures"
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out / f"{nombre}.png", bbox_inches="tight", dpi=150)
