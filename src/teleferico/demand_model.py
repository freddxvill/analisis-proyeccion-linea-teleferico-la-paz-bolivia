"""Modelo de demanda por estación (Fase 4): binomial negativa sobre los abordajes 2025.

Unidad: las 26 estaciones físicas (los andenes de una estación de transbordo se suman). Con n = 26
se comparan pocos modelos simples con validación leave-one-out y se reportan intervalos.

Variables:
- pob_15 (log): población a ≤ 15 min a pie con pendiente (notebook 03).
- pob_voronoi_3km (log): población cuya estación más cercana en línea recta es esta, a ≤ 3 km
  (aproximación al área de alimentación en minibús).
- cabecera: la estación es extremo de al menos una línea (GTFS, stop_times).
- interurbana: está en una línea que une El Alto con La Paz (Roja, Amarilla, Morada).
- cabecera_interurbana = cabecera × interurbana: las puertas del flujo El Alto ↔ La Paz.
- transbordo, el_alto, dist_centro_km (a Plaza Murillo), anios_operacion.
"""

import logging
import warnings
import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from patsy import dmatrix
from sklearn.metrics import mean_absolute_error, mean_poisson_deviance
from sklearn.model_selection import LeaveOneOut

from teleferico import demanda
from teleferico.access import OUT_DIR as ACC_DIR
from teleferico.config import CRS_METRIC, CRS_WGS84, PROCESSED
from teleferico.ingest.gtfs import GTFS_PATH

log = logging.getLogger(__name__)

OUT_DIR = PROCESSED / "modelo_demanda"
PLAZA_MURILLO = (-68.1336, -16.4958)
RADIO_VORONOI_M = 3000
# Apertura de cada línea. La serie por línea del PDF empieza en 2015; Roja, Amarilla y Verde abrieron en 2014.
APERTURA = {"Roja": 2014, "Amarilla": 2014, "Verde": 2014, "Azul": 2017, "Naranja": 2017, "Blanca": 2018,
            "Celeste": 2018, "Morada": 2018, "Café": 2018, "Plateada": 2019}

MODELOS = {
    "Nulo": "y ~ 1",
    "Población a pie": "y ~ l_pob_15",
    "Área de alimentación": "y ~ l_pob_voronoi_3km",
    "Cabecera": "y ~ cabecera",
    "Cabecera interurbana": "y ~ cabecera_interurbana",
    "Cab. interurbana + transbordo": "y ~ cabecera_interurbana + transbordo",
    "Cab. interurbana + transbordo + pob. a pie": "y ~ cabecera_interurbana + transbordo + l_pob_15",
    "Cab. interurbana + transbordo + área alim.": "y ~ cabecera_interurbana + transbordo + l_pob_voronoi_3km",
    "Cabecera + interurbana + transbordo": "y ~ cabecera + interurbana + transbordo",
}

PRINCIPAL = "Cabecera interurbana"  # menor error LOO
EXTENDIDO = "Cab. interurbana + transbordo + pob. a pie"  # sensibilidad: deja que la población mueva la predicción


def cabeceras(path=GTFS_PATH) -> set[str]:
    """Estaciones que son primera o última parada de algún viaje del GTFS."""
    with zipfile.ZipFile(path) as z:
        st = pd.read_csv(z.open("stop_times.txt"), usecols=["trip_id", "stop_id", "stop_sequence"])
    st["slug"] = st["stop_id"].str.split("/").str[1]
    g = st.groupby("trip_id")["stop_sequence"]
    extremos = (st["stop_sequence"] == g.transform("min")) | (st["stop_sequence"] == g.transform("max"))
    return set(st.loc[extremos, "slug"])


def lineas_interurbanas(t: dict) -> list[str]:
    an = t["andenes"].merge(t["estaciones"][["slug", "municipio"]], on="slug")
    return sorted(l for l, g in an.groupby("linea") if g["municipio"].nunique() == 2)


def poblacion_voronoi(acc: pd.DataFrame, radio_m: float = RADIO_VORONOI_M) -> pd.Series:
    cerca = acc[acc["d_euclid_m"] <= radio_m]
    return cerca.groupby("estacion_euclid")["personas"].sum()


def dist_centro_km(lon, lat) -> np.ndarray:
    pts = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=CRS_WGS84).to_crs(CRS_METRIC)
    pm = gpd.GeoSeries(gpd.points_from_xy(*[[c] for c in PLAZA_MURILLO]), crs=CRS_WGS84).to_crs(CRS_METRIC).iat[0]
    return (pts.distance(pm) / 1000).to_numpy()


def variables(t: dict | None = None, acc: pd.DataFrame | None = None, anio: int = 2025) -> pd.DataFrame:
    """Tabla de estaciones con la demanda observada y las variables explicativas."""
    t = t or demanda.cargar()
    acc = acc if acc is not None else pd.read_parquet(ACC_DIR / "manzanos_acceso.parquet")
    cap = pd.read_parquet(ACC_DIR / "estaciones_captacion.parquet")
    est = demanda.estaciones_fisicas(t, periodo=str(anio))
    df = est.merge(cap.drop(columns=["nombre", "municipio"]), on="slug")
    lineas = df["lineas"].str.split(", ")
    inter = lineas_interurbanas(t)

    df["y"] = df["pasajeros_est"].round()
    df["pob_15"] = df["pob_pendiente_15"]
    df["pob_voronoi_3km"] = df["slug"].map(poblacion_voronoi(acc)).fillna(0)
    df["cabecera"] = df["slug"].isin(cabeceras()).astype(int)
    df["interurbana"] = lineas.apply(lambda ls: any(l in inter for l in ls)).astype(int)
    df["cabecera_interurbana"] = df["cabecera"] * df["interurbana"]
    df["transbordo"] = df["transbordo"].astype(int)
    df["el_alto"] = (df["municipio"] == "El Alto").astype(int)
    df["dist_centro_km"] = dist_centro_km(df["stop_lon"], df["stop_lat"])
    df["anios_operacion"] = anio + 1 - lineas.apply(lambda ls: min(APERTURA[l] for l in ls))
    return transformar(df)


def transformar(df: pd.DataFrame) -> pd.DataFrame:
    """Logaritmos en decenas de miles (coeficiente = elasticidad); +1 evita log(0)."""
    df = df.copy()
    for c in ("pob_15", "pob_voronoi_3km"):
        if c in df:
            df[f"l_{c}"] = np.log((df[c] + 1) / 1e4)
    return df


def ajustar(formula: str, df: pd.DataFrame):
    """Binomial negativa (NB2, con alfa estimado), arrancando desde los coeficientes de una Poisson.

    Con conteos de millones, Newton desde cero diverge; si BFGS no converge se prueba Nelder-Mead.
    """
    poisson = smf.glm(formula, df, family=sm.families.Poisson()).fit()
    inicio = np.r_[poisson.params.to_numpy(), 0.5]
    for metodo in ("bfgs", "newton", "nm"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = smf.negativebinomial(formula, df).fit(start_params=inicio, method=metodo, maxiter=5000, disp=0)
        if res.mle_retvals.get("converged", False) and np.isfinite(res.params).all():
            return res
    raise RuntimeError(f"La binomial negativa no convergió: {formula}")


def loo(formula: str, df: pd.DataFrame) -> np.ndarray:
    pred = np.empty(len(df))
    for tr, te in LeaveOneOut().split(df):
        pred[te] = ajustar(formula, df.iloc[tr]).predict(df.iloc[te]).to_numpy()
    return pred


def comparar(df: pd.DataFrame, modelos: dict[str, str] = MODELOS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Métricas de ajuste (AIC) y de validación leave-one-out para cada fórmula."""
    filas, preds = [], {}
    for nombre, f in modelos.items():
        res = ajustar(f, df)
        p = loo(f, df)
        preds[nombre] = p
        filas.append({
            "modelo": nombre, "formula": f, "n_coef": len(res.params) - 1, "aic": res.aic,
            "pseudo_r2": res.prsquared, "alpha": res.params["alpha"],
            "loo_mae": mean_absolute_error(df["y"], p),
            "loo_dev_poisson": mean_poisson_deviance(df["y"], p),
            "loo_mape_mediana": float(np.median(np.abs(p / df["y"] - 1)) * 100),
            "loo_r2_log": 1 - np.sum((np.log(df["y"]) - np.log(p)) ** 2)
            / np.sum((np.log(df["y"]) - np.log(df["y"]).mean()) ** 2),
        })
    return pd.DataFrame(filas).set_index("modelo"), pd.DataFrame(preds, index=df["slug"])


def simular(res, nuevos: pd.DataFrame, n: int = 5000, semilla: int = 0) -> np.ndarray:
    """Simulación de pasajeros/año (n × estaciones): incertidumbre de parámetros + ruido NB.

    Los coeficientes se toman de una normal multivariada (estimación y covarianza del ajuste) y,
    para cada media, se sortea una binomial negativa con el alfa simulado.
    """
    rng = np.random.default_rng(semilla)
    params = rng.multivariate_normal(res.params.to_numpy(), res.cov_params().to_numpy(), size=n)
    rhs = res.model.formula.split("~", 1)[1]
    X = dmatrix(rhs, nuevos, return_type="dataframe")[res.model.exog_names[:-1]]  # sin alpha.to_numpy(dtype=float)
    mu = np.exp(params[:, :-1] @ X.T)
    alpha = np.clip(params[:, -1:], 1e-6, None)
    # NB2: var = mu + alpha·mu². Parametrización de numpy: n = 1/alpha, p = n / (n + mu).
    r = 1 / alpha
    return rng.negative_binomial(r, r / (r + mu)).astype(float)


def intervalo(sim: np.ndarray, nivel: float = 0.9) -> dict:
    a = (1 - nivel) / 2
    return {"media": float(sim.mean()), "p05": float(np.quantile(sim, a)), "p50": float(np.median(sim)),
            "p95": float(np.quantile(sim, 1 - a))}


def run(overwrite: bool = False) -> None:
    df = variables()
    comp, preds = comparar(df)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.drop(columns="geometry", errors="ignore").to_parquet(OUT_DIR / "estaciones_variables.parquet", index=False)
    comp.reset_index().to_parquet(OUT_DIR / "comparacion_modelos.parquet", index=False)
    preds.reset_index().to_parquet(OUT_DIR / "predicciones_loo.parquet", index=False)
    mejor = comp["loo_dev_poisson"].idxmin()
    log.info("Modelo con menor devianza LOO: %s (MAE %.2f M)", mejor, comp.loc[mejor, "loo_mae"] / 1e6)
