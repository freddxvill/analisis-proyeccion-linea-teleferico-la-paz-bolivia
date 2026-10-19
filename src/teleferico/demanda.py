"""Indicadores de demanda (Fase 2): cálculos compartidos por el notebook 01 y el sitio."""

import geopandas as gpd
import numpy as np
import pandas as pd

from teleferico.config import PROCESSED

MT = PROCESSED / "mt"
RED = PROCESSED / "red"

ANIO_PREVIO_COVID = 2019
ANIO_ACTUAL = 2025
# Años "normales" para estacionalidad: sin cuarentena (2020) ni recuperación (2021).
ANIOS_ESTACIONALIDAD = [2022, 2023, 2024, 2025]
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
INICIO_OPERACION = pd.Timestamp("2014-05-30")  # Línea Roja


def cargar() -> dict[str, pd.DataFrame]:
    return {
        "anual": pd.read_parquet(MT / "anual_total.parquet"),
        "por_linea": pd.read_parquet(MT / "anual_por_linea.parquet"),
        "mensual": pd.read_parquet(MT / "mensual.parquet"),
        "diario": pd.read_parquet(MT / "promedio_diario.parquet"),
        "demanda_est": pd.read_parquet(RED / "demanda_estaciones.parquet"),
        "estaciones": gpd.read_parquet(RED / "estaciones.parquet"),
        "andenes": gpd.read_parquet(RED / "andenes.parquet"),
        "lineas": gpd.read_parquet(RED / "lineas.parquet"),
    }


def dias_operacion(mensual: pd.DataFrame) -> pd.Series:
    """Días con servicio por año: meses con pasajeros > 0; en 2014 la red abrió el 30 de mayo.

    Aproximación: los meses con cierre parcial (p. ej. marzo de 2020) cuentan completos.
    """
    m = mensual[mensual["pasajeros"] > 0]
    dias = m["mes"].dt.days_in_month.where(m["mes"] != INICIO_OPERACION.to_period("M").to_timestamp(),
                                           INICIO_OPERACION.days_in_month - INICIO_OPERACION.day + 1)
    return dias.groupby(m["mes"].dt.year).sum().rename("dias_operacion")


def serie_anual(anual: pd.DataFrame, mensual: pd.DataFrame) -> pd.DataFrame:
    df = anual.copy()
    df["var_pct"] = df["pasajeros"].pct_change() * 100
    base = df.set_index("anio").loc[ANIO_PREVIO_COVID, "pasajeros"]
    df["indice_2019"] = df["pasajeros"] / base * 100
    df = df.merge(dias_operacion(mensual), left_on="anio", right_index=True)
    df["promedio_diario"] = df["pasajeros"] / df["dias_operacion"]
    return df


def resumen_lineas(t: dict[str, pd.DataFrame], anio: int = ANIO_ACTUAL) -> pd.DataFrame:
    """Pasajeros, participación, km, estaciones y productividad por línea en `anio`."""
    pl = t["por_linea"].pivot(index="linea", columns="anio", values="pasajeros")
    km = t["lineas"].groupby("linea")["longitud_m"].sum() / 1000
    n_est = t["andenes"].groupby("linea")["slug"].nunique()
    df = pd.DataFrame({
        "pasajeros": pl[anio],
        "participacion_pct": pl[anio] / pl[anio].sum() * 100,
        "km": km,
        "estaciones": n_est,
        "var_vs_anio_previo_pct": (pl[anio] / pl[anio - 1] - 1) * 100,
        "var_vs_2019_pct": (pl[anio] / pl[ANIO_PREVIO_COVID] - 1) * 100,
    })
    df["pasajeros_por_km"] = df["pasajeros"] / df["km"]
    df["pasajeros_por_estacion"] = df["pasajeros"] / df["estaciones"]
    df["km_pct"] = df["km"] / df["km"].sum() * 100
    return df.sort_values("pasajeros", ascending=False)


def indice_por_linea(por_linea: pd.DataFrame, base: int = ANIO_PREVIO_COVID) -> pd.DataFrame:
    """Pasajeros por línea indexados a `base` = 100 (solo líneas con año base completo)."""
    pl = por_linea.pivot(index="anio", columns="linea", values="pasajeros")
    pl = pl.loc[:, pl.loc[base].notna()]
    return pl / pl.loc[base] * 100


def matriz_mensual(mensual: pd.DataFrame) -> pd.DataFrame:
    m = mensual.assign(anio=mensual["mes"].dt.year, m=mensual["mes"].dt.month)
    return m.pivot(index="anio", columns="m", values="pasajeros")


def indice_estacional(mensual: pd.DataFrame, anios=ANIOS_ESTACIONALIDAD) -> pd.Series:
    """Promedio, en los años normales, del mes / media mensual del año (1 = mes típico)."""
    mat = matriz_mensual(mensual).loc[anios]
    return (mat.div(mat.mean(axis=1), axis=0)).mean().rename("indice")


def estaciones_fisicas(t: dict[str, pd.DataFrame], periodo: str = "2025") -> pd.DataFrame:
    """Suma la demanda de los andenes de cada estación física (transbordos incluidos)."""
    d = t["demanda_est"].query("periodo == @periodo")
    agg = d.groupby("slug").agg(
        pct=("pct", "sum"),
        pasajeros_est=("pasajeros_est", "sum"),
        lineas=("linea", lambda s: ", ".join(sorted(s))),
    )
    est = t["estaciones"].set_index("slug")[["nombre", "municipio", "transbordo", "stop_lat", "stop_lon"]]
    return est.join(agg).sort_values("pasajeros_est", ascending=False).reset_index()


def curva_concentracion(valores: pd.Series) -> pd.DataFrame:
    """Curva de Pareto: % acumulado de demanda vs % acumulado de estaciones (de mayor a menor)."""
    v = valores.sort_values(ascending=False).to_numpy(dtype=float)
    return pd.DataFrame({
        "pct_estaciones": np.arange(1, len(v) + 1) / len(v) * 100,
        "pct_demanda": v.cumsum() / v.sum() * 100,
    })


def gini(valores: pd.Series) -> float:
    v = np.sort(valores.to_numpy(dtype=float))
    n = len(v)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(v) / (n * v.sum()))


def kpis(t: dict[str, pd.DataFrame]) -> dict:
    anual = serie_anual(t["anual"], t["mensual"]).set_index("anio")
    lin = resumen_lineas(t)
    est = estaciones_fisicas(t)
    conc = curva_concentracion(est["pasajeros_est"])
    top5 = est.head(5)
    por_mun = est.groupby("municipio")["pct"].sum()
    return {
        "pct_abordajes_el_alto_2025": round(float(por_mun.get("El Alto", 0)), 1),
        "estaciones_el_alto": int((est["municipio"] == "El Alto").sum()),
        "pasajeros_2025": int(anual.loc[2025, "pasajeros"]),
        "pasajeros_2024": int(anual.loc[2024, "pasajeros"]),
        "var_2025_vs_2024_pct": round(float(anual.loc[2025, "var_pct"]), 1),
        "pasajeros_2019": int(anual.loc[2019, "pasajeros"]),
        "indice_2025_vs_2019": round(float(anual.loc[2025, "indice_2019"]), 1),
        "caida_2020_pct": round(float(anual.loc[2020, "var_pct"]), 1),
        "acumulado_2014_2025": int(anual["pasajeros"].sum()),
        "promedio_diario_2025": int(round(anual.loc[2025, "promedio_diario"])),
        "km_red": round(float(lin["km"].sum()), 1),
        "linea_top": lin.index[0],
        "linea_top_participacion_pct": round(float(lin["participacion_pct"].iat[0]), 1),
        "linea_top_km_pct": round(float(lin["km_pct"].iat[0]), 1),
        "top5_estaciones": top5["nombre"].tolist(),
        "top5_estaciones_pct": round(float(top5["pct"].sum()), 1),
        "pct_estaciones_para_50pct_demanda": round(
            float(conc.loc[conc["pct_demanda"] >= 50, "pct_estaciones"].iat[0]), 1
        ),
        "gini_estaciones_2025": round(gini(est["pasajeros_est"]), 2),
    }
