"""Lente de equidad (Fase 3): vulnerabilidad socioeconómica del Censo 2024 × acceso al teleférico.

Índice de vulnerabilidad (IV) por manzano: promedio de los rangos percentiles (ponderados por
población) de 7 carencias de la ficha censal. 0 = el manzano menos carenciado, 1 = el más.
Brecha de accesibilidad = IV × falta de acceso, con la falta de acceso = 0 a ≤ 10 min de una
estación y 1 a ≥ 30 min (lineal en medio). Solo manzanos con ficha (~96 % de la población).
"""

import h3
import pandas as pd

from teleferico.config import PROCESSED

FICHA_PATH = PROCESSED / "censo" / "ficha_manzanos.parquet"


def _hm(f: pd.DataFrame, var: str) -> pd.Series:
    return f[f"{var}_h"] + f[f"{var}_m"]


def _cociente(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den.where(den > 0)).clip(0, 1)


# nombre -> (etiqueta, función sobre la ficha que devuelve la proporción con la carencia)
INDICADORES = {
    "sin_superior": ("19+ años sin educación superior",
                     lambda f: 1 - _cociente(_hm(f, "edu_superior"), _hm(f, "edu_total"))),
    "sin_seguro": ("Sin seguro de salud",
                   lambda f: _cociente(_hm(f, "salud_seguro_ninguno"), _hm(f, "salud_seguro_total"))),
    "sin_agua_red": ("Vivienda sin agua por cañería de red",
                     lambda f: 1 - _cociente(f["serv_agua_caneria"], f["serv_agua_total"])),
    "sin_alcantarillado": ("Vivienda sin alcantarillado",
                           lambda f: 1 - _cociente(f["serv_desague_alcantarillado"], f["serv_desague_total"])),
    "sin_internet": ("Hogar sin internet",
                     lambda f: 1 - _cociente(f["tic_internet"], f["tic_total"])),
    "hacinamiento_alto": ("Vivienda con hacinamiento alto",
                          lambda f: _cociente(f["hac_alto"], f[["hac_alto", "hac_medio", "hac_sin"]].sum(axis=1))),
    "piso_tierra": ("Vivienda con piso de tierra",
                    lambda f: _cociente(f["mat_piso_tierra"], f.filter(like="mat_piso_").sum(axis=1))),
}
T_SIN_BRECHA, T_BRECHA_MAX = 10, 30


def rango_ponderado(x: pd.Series, w: pd.Series) -> pd.Series:
    """Rango percentil (0-1) de x ponderado por w: qué fracción de la población tiene un valor menor."""
    orden = x.sort_values(kind="mergesort").index
    cw = w.loc[orden].cumsum()
    r = (cw - w.loc[orden] / 2) / w.sum()
    # Empates: el mismo rango para valores iguales (el promedio del grupo).
    r = r.groupby(x.loc[orden].to_numpy()).transform("mean")
    return r.reindex(x.index)


def indicadores(acc: pd.DataFrame) -> pd.DataFrame:
    """Tabla de manzanos con ficha: carencias (proporción), IV, quintil de IV y brecha."""
    f = pd.read_parquet(FICHA_PATH)
    df = acc.merge(f, on="codigo", how="inner")
    df = df[df["personas"] > 0]
    out = df[[c for c in acc.columns]].copy()
    for nombre, (_, fn) in INDICADORES.items():
        out[nombre] = fn(df).to_numpy()
    w = out["personas"]
    rangos = pd.DataFrame({n: rango_ponderado(out[n].fillna(out[n].median()), w) for n in INDICADORES})
    out["iv"] = rangos.mean(axis=1)
    out["iv_quintil"] = pd.cut(rango_ponderado(out["iv"], w), [0, .2, .4, .6, .8, 1],
                               labels=["Q1 (menos vulnerable)", "Q2", "Q3", "Q4", "Q5 (más vulnerable)"],
                               include_lowest=True)
    out["falta_acceso"] = ((out["t_pendiente_min"] - T_SIN_BRECHA) / (T_BRECHA_MAX - T_SIN_BRECHA)).clip(0, 1)
    out["brecha"] = out["iv"] * out["falta_acceso"]
    return out


def cobertura_por_quintil(eq: pd.DataFrame, umbral: float = 15, por: str | None = None) -> pd.DataFrame:
    claves = ["iv_quintil"] if por is None else [por, "iv_quintil"]
    g = eq.assign(cub=(eq["t_pendiente_min"] <= umbral) * eq["personas"],
                  tp=eq["t_pendiente_min"].clip(upper=60) * eq["personas"])
    r = g.groupby(claves, observed=True)[["personas", "cub", "tp"]].sum()
    return pd.DataFrame({
        "poblacion": r["personas"],
        f"pct_cubierta_{umbral:g}min": r["cub"] / r["personas"] * 100,
        "t_medio_min": r["tp"] / r["personas"],
    })


def media_ponderada(df: pd.DataFrame, cols, w: str = "personas", por: str = "h3") -> pd.DataFrame:
    """Medias ponderadas por población de `cols` agregadas por `por` (p. ej. hexágono H3)."""
    cols = list(cols)
    x = df[cols].mul(df[w], axis=0).assign(**{w: df[w]})
    g = x.groupby(df[por]).sum()
    return g[cols].div(g[w], axis=0).assign(**{w: g[w]})


def correlaciones(eq: pd.DataFrame) -> pd.Series:
    """Correlación de Spearman (ponderación implícita por manzano) entre cada carencia y el tiempo."""
    t = eq["t_pendiente_min"].clip(upper=60)
    return pd.Series({n: eq[n].corr(t, method="spearman") for n in [*INDICADORES, "iv"]}).round(3)



def por_h3(eq: pd.DataFrame, res: int = 9) -> pd.DataFrame:
    """IV, brecha y carencias medias (ponderadas por población) por hexágono H3."""
    df = eq.assign(h3=[h3.latlng_to_cell(la, lo, res) for la, lo in zip(eq["lat"], eq["lon"])])
    out = media_ponderada(df, [*INDICADORES, "iv", "brecha"], por="h3")
    return out.rename(columns={"personas": "personas_ficha"}).reset_index()
