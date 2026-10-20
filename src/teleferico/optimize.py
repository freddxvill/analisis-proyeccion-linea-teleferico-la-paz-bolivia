"""Ubicación de nuevas estaciones y trazado de una línea (Fase 5).

1. Demanda: hexágonos H3 r9 con su población **no cubierta** (a > 15 min a pie con pendiente).
2. Bolsones de subcobertura: DBSCAN sobre los hexágonos no cubiertos y densos, con la población como
   `sample_weight` (un núcleo exige una masa mínima de habitantes, no de celdas). Se evalúa la
   robustez en una grilla de `eps` y umbral de densidad.
3. Candidatos: centros de hexágonos en los bolsones y en sus bordes, con pendiente del terreno
   transitable para una estación.
4. Tiempo a pie candidato ← demanda con el mismo grafo y Tobler direccional que la Fase 3.
5. MCLP (máxima cobertura) y p-mediana (mínimo tiempo total) con `spopt`, para k = 3…10.
6. Trazado: búsqueda en haz de una línea que sale de una estación existente (transbordo), con vanos de
   700-2.500 m y giros ≤ 60° en las estaciones, que maximiza la población nueva por km de cable.
"""

import json
import logging

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import pulp
import rasterio
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString
from sklearn.cluster import DBSCAN
from spopt.locate import MCLP, PMedian

from teleferico import access as ac
from teleferico import demand_model, equidad
from teleferico.config import CRS_METRIC, CRS_WGS84, INTERIM, PROCESSED

log = logging.getLogger(__name__)

OUT_DIR = PROCESSED / "propuesta"
MATRIZ_PATH = INTERIM / "propuesta" / "tiempos_candidatos.npz"

UMBRAL_MIN = ac.UMBRAL_MIN
SIN_ACCESO = 999.0  # costo para pares sin camino dentro del límite de Dijkstra

# DBSCAN (base) y grilla de robustez.
EPS_M = 450  # ~1 anillo H3 r9 (centros a ~350 m) con holgura
POB_NUCLEO = 6000  # personas no cubiertas dentro de eps para ser núcleo
PCT_DENSIDAD = 50  # percentil de densidad (de los hexágonos habitados) para entrar al análisis
GRILLA_EPS = [350, 450, 600]
GRILLA_PCT = [40, 50, 60]
PERSISTENCIA_MIN = 0.5

ANILLO_CANDIDATOS = 2  # hexágonos alrededor de los bolsones que también son candidatos
PENDIENTE_TERRENO_MAX = 0.30
LIMITE_MATRIZ_MIN = 25

K_ESTACIONES = list(range(3, 11))
K_PMEDIANA = [3, 6, 10]  # la p-mediana tarda ~2-3 min por k
VANO_MIN_M, VANO_MAX_M, GIRO_MAX = 700, 2500, 60


# --- Demanda ---------------------------------------------------------------------------------

def demanda_no_cubierta(acc: pd.DataFrame, res: int = 9, umbral: float = UMBRAL_MIN) -> gpd.GeoDataFrame:
    """Hexágonos con población a > `umbral` min. El punto de demanda es el centroide de sus manzanos
    no cubiertos, ponderado por población (no el centro geométrico del hexágono)."""
    nc = acc[~(acc["t_pendiente_min"] <= umbral) & (acc["personas"] > 0)].copy()
    nc["h3"] = [h3.latlng_to_cell(la, lo, res) for la, lo in zip(nc["lat"], nc["lon"])]
    nc["t_actual"] = nc["t_pendiente_min"].clip(upper=ac.LIMITE_MIN)
    for c in ("lon", "lat", "t_actual"):
        nc[f"w_{c}"] = nc[c] * nc["personas"]
    g = nc.groupby("h3")
    d = pd.DataFrame({
        "personas": g["personas"].sum(),
        "municipio": g["municipio"].agg(lambda s: s.mode().iat[0]),
        "zona": g["zona"].agg(lambda s: s.mode().iat[0]),
    })
    for c in ("lon", "lat", "t_actual"):
        d[c] = g[f"w_{c}"].sum() / d["personas"]
    hx = pd.read_parquet(ac.OUT_DIR / f"h3_acceso_r{res}.parquet").set_index("h3")
    d["densidad_hab_km2"] = hx["densidad_hab_km2"].reindex(d.index)  # densidad total del hexágono
    d = d.reset_index()
    return gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d["lon"], d["lat"]), crs=CRS_WGS84).to_crs(CRS_METRIC)


# --- Bolsones (DBSCAN) -----------------------------------------------------------------------

def umbral_densidad(pct: float = PCT_DENSIDAD, res: int = 9) -> float:
    hx = pd.read_parquet(ac.OUT_DIR / f"h3_acceso_r{res}.parquet")
    return float(np.percentile(hx["densidad_hab_km2"], pct))


def dbscan(dem: gpd.GeoDataFrame, eps_m: float = EPS_M, pob_nucleo: float = POB_NUCLEO,
           pct_densidad: float = PCT_DENSIDAD) -> pd.Series:
    """Etiqueta de bolsón por hexágono de demanda (−1 = ruido o por debajo del umbral de densidad)."""
    sel = dem["densidad_hab_km2"] >= umbral_densidad(pct_densidad)
    etiqueta = pd.Series(-1, index=dem.index)
    X = np.column_stack([dem.geometry.x[sel], dem.geometry.y[sel]])
    db = DBSCAN(eps=eps_m, min_samples=pob_nucleo).fit(X, sample_weight=dem.loc[sel, "personas"].to_numpy())
    etiqueta[sel] = db.labels_
    return etiqueta


def distancia_k_vecino(dem: gpd.GeoDataFrame, k: int = 6, pct_densidad: float = PCT_DENSIDAD) -> np.ndarray:
    """Distancia al k-ésimo vecino (ordenada) entre hexágonos densos no cubiertos, para calibrar eps."""
    sel = dem[dem["densidad_hab_km2"] >= umbral_densidad(pct_densidad)]
    X = np.column_stack([sel.geometry.x, sel.geometry.y])
    d, _ = cKDTree(X).query(X, k=k + 1)
    return np.sort(d[:, -1])


def persistencia(dem: gpd.GeoDataFrame, grilla_eps=GRILLA_EPS, grilla_pct=GRILLA_PCT,
                 pob_nucleo: float = POB_NUCLEO) -> pd.Series:
    """Fracción de combinaciones (eps × umbral de densidad) en que cada hexágono cae en algún bolsón."""
    marcas = [dbscan(dem, e, pob_nucleo, p) >= 0 for e in grilla_eps for p in grilla_pct]
    return pd.concat(marcas, axis=1).mean(axis=1)


def resumen_bolsones(dem: gpd.GeoDataFrame, eq_h3: pd.DataFrame | None = None) -> pd.DataFrame:
    """Una fila por bolsón: población, área, densidad, tiempo actual, municipio, persistencia, IV."""
    b = dem[dem["bolson"] >= 0].copy()
    if eq_h3 is not None:
        b = b.merge(eq_h3[["h3", "iv", "brecha"]], on="h3", how="left")
    area_hex = h3.average_hexagon_area(9, unit="km^2")
    filas = []
    for k, g in b.groupby("bolson"):
        w = g["personas"]
        c = g.to_crs(CRS_WGS84).geometry
        fila = {
            "bolson": k, "personas_no_cubiertas": w.sum(), "hexagonos": len(g), "area_km2": len(g) * area_hex,
            "t_actual_min": np.average(g["t_actual"], weights=w),
            "municipio": g.groupby("municipio")["personas"].sum().idxmax(),
            "zona": g.groupby("zona")["personas"].sum().idxmax(),
            "persistencia": np.average(g["persistencia"], weights=w),
            "lon": np.average(c.x, weights=w), "lat": np.average(c.y, weights=w),
        }
        if eq_h3 is not None:
            ok = g["iv"].notna()
            fila["iv"] = np.average(g.loc[ok, "iv"], weights=w[ok]) if ok.any() else np.nan
        filas.append(fila)
    r = pd.DataFrame(filas)
    r["densidad_no_cubierta_hab_km2"] = r["personas_no_cubiertas"] / r["area_km2"]
    return r.sort_values("personas_no_cubiertas", ascending=False).reset_index(drop=True)


# --- Candidatos y matriz de tiempos ------------------------------------------------------------

def pendiente_terreno(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Pendiente del terreno (m/m) en puntos CRS_METRIC, desde el DEM suavizado de la Fase 3."""
    z, transform, crs = ac._dem_suavizado()
    lat0 = transform.f + transform.e * z.shape[0] / 2
    dy = abs(transform.e) * 111_320
    dx = transform.a * 111_320 * np.cos(np.radians(lat0))
    gy, gx = np.gradient(np.where(z == ac.NODATA, np.nan, z), dy, dx)
    s = np.hypot(gx, gy)
    lon, lat = Transformer.from_crs(CRS_METRIC, crs, always_xy=True).transform(x, y)
    f, c = rasterio.transform.rowcol(transform, lon, lat)
    return s[np.asarray(f), np.asarray(c)]


def candidatos(dem: gpd.GeoDataFrame, anillo: int = ANILLO_CANDIDATOS) -> gpd.GeoDataFrame:
    """Centros de hexágonos habitados en los bolsones y a ≤ `anillo` celdas de ellos, en terreno transitable."""
    nucleo = dem.loc[dem["bolson"] >= 0, "h3"]
    celdas = set().union(*(h3.grid_disk(c, anillo) for c in nucleo))
    habitados = set(pd.read_parquet(ac.OUT_DIR / "h3_acceso_r9.parquet", columns=["h3"])["h3"])
    celdas = sorted(celdas & habitados)
    pts = gpd.GeoDataFrame({"h3": celdas}, geometry=gpd.points_from_xy(
        [h3.cell_to_latlng(c)[1] for c in celdas], [h3.cell_to_latlng(c)[0] for c in celdas]), crs=CRS_WGS84
    ).to_crs(CRS_METRIC)
    pts["en_bolson"] = pts["h3"].isin(set(nucleo))
    pts["pendiente_terreno"] = pendiente_terreno(pts.geometry.x.to_numpy(), pts.geometry.y.to_numpy())
    pts = pts[pts["pendiente_terreno"] <= PENDIENTE_TERRENO_MAX].reset_index(drop=True)
    return pts


def matriz_tiempos(cand: gpd.GeoDataFrame, dem: gpd.GeoDataFrame, aristas: pd.DataFrame, nod: gpd.GeoDataFrame,
                   variantes=("pendiente", "plana"), lote: int = 150) -> dict[str, np.ndarray]:
    """Minutos de caminata demanda → candidato (candidatos × demanda), con la penalidad de acceso a la red."""
    tree = cKDTree(np.column_stack([nod.geometry.x, nod.geometry.y]))
    d_nodo, i_nodo = tree.query(np.column_stack([dem.geometry.x, dem.geometry.y]))
    pen = (d_nodo / ac.V_PLANA_MS / 60).astype("float32")
    out = {v: [] for v in variantes}
    for i in range(0, len(cand), lote):
        T = ac.tiempos_por_estacion(aristas, nod, cand.iloc[i:i + lote], variantes=variantes,
                                    limite_min=LIMITE_MATRIZ_MIN, columnas=i_nodo)
        for v in variantes:
            out[v].append(T[v] + pen)
        log.info("Matriz de tiempos: %d/%d candidatos", min(i + lote, len(cand)), len(cand))
    return {v: np.where(np.isfinite(m := np.vstack(out[v])), m, SIN_ACCESO).astype("float32") for v in variantes}


# --- Modelos de localización ---------------------------------------------------------------

def _solver():
    return pulp.PULP_CBC_CMD(msg=False)


def mclp(T: np.ndarray, pesos: np.ndarray, k: int, umbral: float = UMBRAL_MIN) -> dict:
    """Máxima cobertura: k candidatos que maximizan la población no cubierta a ≤ umbral min."""
    m = MCLP.from_cost_matrix(T.T, pesos, service_radius=umbral, p_facilities=k).solve(_solver())
    elegidos = np.array([j for j, x in enumerate(m.fac_vars) if x.value() > 0.5])
    cubre = (T[elegidos] <= umbral).any(axis=0)
    return {"k": k, "umbral": umbral, "elegidos": elegidos, "cubiertos": cubre,
            "personas": float(pesos[cubre].sum())}


def p_mediana(T: np.ndarray, pesos: np.ndarray, t_actual: np.ndarray, k: int) -> dict:
    """Minimiza el tiempo total ponderado. El costo de asignar i a j es min(t_ij, t_actual_i): nadie
    empeora, y el óptimo equivale a elegir la mejor entre la estación existente y las nuevas."""
    C = np.minimum(T, t_actual[None, :]).T
    m = PMedian.from_cost_matrix(C, pesos, p_facilities=k).solve(_solver())
    elegidos = np.array([j for j, x in enumerate(m.fac_vars) if x.value() > 0.5])
    t_nuevo = np.minimum(T[elegidos].min(axis=0), t_actual)
    return {"k": k, "elegidos": elegidos, "t_medio_antes": float(np.average(t_actual, weights=pesos)),
            "t_medio_despues": float(np.average(t_nuevo, weights=pesos)),
            "personas_a_15": float(pesos[t_nuevo <= UMBRAL_MIN].sum())}


def curva_mclp(Ts: dict, pesos: np.ndarray, ks=K_ESTACIONES, umbrales=(10, 15)) -> tuple[pd.DataFrame, dict]:
    filas, soluciones = [], {}
    for var, T in Ts.items():
        for u in umbrales:
            for k in ks:
                r = mclp(T, pesos, k, u)
                soluciones[(var, u, k)] = r
                filas.append({"variante": var, "umbral": u, "k": k, "personas": r["personas"]})
    return pd.DataFrame(filas), soluciones


# --- Trazado de línea ------------------------------------------------------------------------

def _angulo(a, b, c) -> float:
    """Giro (grados) en b al ir de a a b y luego a c (0 = sigue recto)."""
    v1, v2 = b - a, c - b
    cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
    return float(np.degrees(np.arccos(np.clip(cos, -1, 1))))


def trazar_linea(cand: gpd.GeoDataFrame, T: np.ndarray, pesos: np.ndarray, estaciones: gpd.GeoDataFrame,
                 n_max: int = 8, umbral: float = UMBRAL_MIN, haz: int = 12, vano_min: float = VANO_MIN_M,
                 vano_max: float = VANO_MAX_M, giro_max: float = GIRO_MAX, criterio: str = "por_km") -> pd.DataFrame:
    """Búsqueda en haz de líneas que salen de una estación existente.

    Estado: (estación de origen, secuencia de candidatos). Se ordena por población nueva cubierta por
    km de cable. Devuelve la mejor línea para cada número de estaciones nuevas (1…n_max).
    """
    P = np.column_stack([cand.geometry.x, cand.geometry.y])
    E = np.column_stack([estaciones.geometry.x, estaciones.geometry.y])
    cubre = T <= umbral
    D = np.hypot(P[:, None, 0] - P[None, :, 0], P[:, None, 1] - P[None, :, 1])

    def puntaje(s):
        return s["personas"] / s["km"] if criterio == "por_km" else s["personas"]

    estados = []
    for e, pe in enumerate(E):
        d = np.hypot(*(P - pe).T)
        for j in np.flatnonzero((d >= vano_min) & (d <= vano_max)):
            cub = cubre[j]
            estados.append({"origen": e, "seq": [j], "km": d[j] / 1000, "cub": cub,
                            "personas": float(pesos[cub].sum())})
    mejores = []
    for n in range(1, n_max + 1):
        estados.sort(key=puntaje, reverse=True)
        estados = estados[:haz * 20] if n == 1 else estados[:haz]
        if not estados:
            break
        mejores.append(max(estados, key=lambda s: s["personas"] / s["km"]) | {"n": n})
        if n == n_max:
            break
        nuevos = []
        for s in estados:
            ult = P[s["seq"][-1]]
            prev = P[s["seq"][-2]] if len(s["seq"]) > 1 else E[s["origen"]]
            for j in np.flatnonzero((D[s["seq"][-1]] >= vano_min) & (D[s["seq"][-1]] <= vano_max)):
                if j in s["seq"] or _angulo(prev, ult, P[j]) > giro_max:
                    continue
                cub = s["cub"] | cubre[j]
                nuevos.append({"origen": s["origen"], "seq": s["seq"] + [j],
                               "km": s["km"] + D[s["seq"][-1], j] / 1000, "cub": cub,
                               "personas": float(pesos[cub].sum())})
        # Sin duplicados (misma estación final y mismo conjunto): se queda el de mayor puntaje.
        unicos = {}
        for s in sorted(nuevos, key=puntaje, reverse=True):
            unicos.setdefault((s["origen"], frozenset(s["seq"])), s)
        estados = list(unicos.values())
    filas = [{"n_estaciones": s["n"], "origen": estaciones["slug"].iat[s["origen"]], "secuencia": s["seq"],
              "km": s["km"], "personas": s["personas"], "personas_por_km": s["personas"] / s["km"]}
             for s in mejores]
    return pd.DataFrame(filas)


def geometria_linea(fila: pd.Series, cand: gpd.GeoDataFrame, estaciones: gpd.GeoDataFrame):
    origen = estaciones.set_index("slug").geometry[fila["origen"]]
    return LineString([origen, *cand.geometry.iloc[list(fila["secuencia"])]])


def elegir_n(lineas: pd.DataFrame, referencia: float) -> int:
    """Mayor número de estaciones tal que cada estación agregada rinde ≥ `referencia` personas por km."""
    L = lineas.sort_values("n_estaciones")
    marginal = L["personas"].diff().fillna(L["personas"]) / L["km"].diff().fillna(L["km"])
    ok = (marginal >= referencia).cumprod().astype(bool)
    return int(L.loc[ok, "n_estaciones"].max()) if ok.any() else 1


# --- Evaluación de una propuesta a nivel de manzano ------------------------------------------

def personas_por_km_red(acc: pd.DataFrame, lineas_gtfs: gpd.GeoDataFrame) -> float:
    """Referencia: población a ≤ 15 min de la red actual por km de cable."""
    cubiertos = acc.loc[acc["t_pendiente_min"] <= UMBRAL_MIN, "personas"].sum()
    return float(cubiertos / (lineas_gtfs["longitud_m"].sum() / 1000))


def evaluar(nuevas: gpd.GeoDataFrame, acc: pd.DataFrame, aristas: pd.DataFrame, nod: gpd.GeoDataFrame,
            mz: gpd.GeoDataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recalcula el acceso de cada manzano con las estaciones nuevas (además de las existentes).

    Devuelve (manzanos con t_antes / t_despues, población a ≤ 5/10/15/20 min de cada estación nueva).
    """
    mz = mz if mz is not None else ac.manzanos_centroides()
    T = ac.tiempos_por_estacion(aristas, nod, nuevas, variantes=("pendiente",))
    r, por_est = ac.acceso_manzanos(mz, nod, nuevas.assign(slug=nuevas["id"]), T)
    m = acc[["codigo", "municipio", "zona", "personas", "t_pendiente_min"]].rename(
        columns={"t_pendiente_min": "t_antes"}).merge(
        r[["codigo", "t_pendiente_min", "estacion_pendiente"]].rename(
            columns={"t_pendiente_min": "t_nueva", "estacion_pendiente": "estacion_nueva"}), on="codigo")
    m["t_despues"] = np.minimum(m["t_antes"], m["t_nueva"])
    pers = r["personas"].to_numpy()  # mismo orden que las columnas de por_est
    est = nuevas[["id"]].copy()
    for b in ac.BANDAS_MIN:
        est[f"pob_pendiente_{b}"] = ((por_est["pendiente"] <= b) * pers).sum(axis=1)
    return m, est


def resumen_propuesta(m: pd.DataFrame, km: float, eq: pd.DataFrame | None = None) -> dict:
    pob = m["personas"].sum()
    antes, despues = m["t_antes"] <= UMBRAL_MIN, m["t_despues"] <= UMBRAL_MIN
    nuevos = despues & ~antes
    out = {
        "km_cable": km,
        "personas_nuevas_15": float(m.loc[nuevos, "personas"].sum()),
        "personas_nuevas_10": float(m.loc[(m["t_despues"] <= 10) & ~(m["t_antes"] <= 10), "personas"].sum()),
        "pct_15_antes": float(m.loc[antes, "personas"].sum() / pob * 100),
        "pct_15_despues": float(m.loc[despues, "personas"].sum() / pob * 100),
    }
    out["personas_nuevas_por_km"] = out["personas_nuevas_15"] / km
    for mun in ("El Alto", "La Paz"):
        g = m[m["municipio"] == mun]
        out[f"pct_15_despues_{mun.lower().replace(' ', '_')}"] = float(
            g.loc[g["t_despues"] <= UMBRAL_MIN, "personas"].sum() / g["personas"].sum() * 100)
    if eq is not None:
        v = eq.loc[eq["iv_quintil"].astype(str).str.startswith(("Q4", "Q5")), "codigo"]
        out["personas_nuevas_vulnerables_15"] = float(m.loc[nuevos & m["codigo"].isin(v), "personas"].sum())
    return out


def pasajeros(est_nuevas: pd.DataFrame, df_modelo: pd.DataFrame | None = None, n_sim: int = 5000) -> dict:
    """Abordajes/año de las estaciones nuevas con los modelos de la Fase 4 (media e intervalo del 90 %).

    Las estaciones nuevas no son cabeceras de una línea El Alto ↔ La Paz ni de transbordo (la de origen,
    que pasa a ser de transbordo, ya existe). Son abordajes, no viajeros nuevos: una parte se desviaría
    de estaciones existentes.
    """
    df_modelo = df_modelo if df_modelo is not None else demand_model.variables()
    X = demand_model.transformar(est_nuevas.assign(cabecera_interurbana=0, transbordo=0,
                                                   pob_15=est_nuevas["pob_pendiente_15"], pob_voronoi_3km=0))
    out = {}
    for nombre in (demand_model.PRINCIPAL, demand_model.EXTENDIDO):
        sim = demand_model.simular(demand_model.ajustar(demand_model.MODELOS[nombre], df_modelo), X, n=n_sim)
        out[nombre] = {"total": demand_model.intervalo(sim.sum(axis=1)),
                       "por_estacion": {i: demand_model.intervalo(sim[:, j]) for j, i in enumerate(est_nuevas["id"])}}
    return out


def run(overwrite: bool = False) -> None:
    acc = pd.read_parquet(ac.OUT_DIR / "manzanos_acceso.parquet")
    est = gpd.read_parquet(PROCESSED / "red" / "estaciones.parquet").to_crs(CRS_METRIC)
    lineas_gtfs = gpd.read_parquet(PROCESSED / "red" / "lineas.parquet")
    nod, a = ac.nodos(), ac.aristas_tiempo()

    dem = demanda_no_cubierta(acc)
    dem["bolson"] = dbscan(dem)
    dem["persistencia"] = persistencia(dem)
    eq = equidad.indicadores(acc)
    bol = resumen_bolsones(dem, equidad.por_h3(eq))
    # Solo se reportan como bolsones los que persisten en la mayoría de las combinaciones.
    robustos = set(bol.loc[bol["persistencia"] >= PERSISTENCIA_MIN, "bolson"])
    dem.loc[~dem["bolson"].isin(robustos), "bolson"] = -1
    bol = bol[bol["bolson"].isin(robustos)].reset_index(drop=True)
    cand = candidatos(dem)

    if MATRIZ_PATH.exists() and not overwrite:
        Ts = dict(np.load(MATRIZ_PATH))
        assert Ts["pendiente"].shape == (len(cand), len(dem)), "Matriz en caché desactualizada: usar --overwrite"
    else:
        Ts = matriz_tiempos(cand, dem, a, nod)
        MATRIZ_PATH.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(MATRIZ_PATH, **Ts)

    w = dem["personas"].to_numpy()
    curva, sol = curva_mclp({"pendiente": Ts["pendiente"]}, w, umbrales=(10, 15))
    curva_p, sol_p = curva_mclp({"plana": Ts["plana"]}, w, umbrales=(15,))
    curva = pd.concat([curva, curva_p], ignore_index=True)
    sol |= sol_p
    elegidos = pd.DataFrame([{"variante": v, "umbral": u, "k": k, "candidato": j, "h3": cand["h3"].iat[j]}
                             for (v, u, k), r in sol.items() for j in r["elegidos"]])

    ib, cb = (dem["bolson"] >= 0).to_numpy(), cand["en_bolson"].to_numpy()
    h3_cb = cand.loc[cb, "h3"].to_numpy()
    pmed = []
    for k in K_PMEDIANA:
        r = p_mediana(Ts["pendiente"][cb][:, ib], w[ib], dem["t_actual"].to_numpy()[ib], k)
        pmed.append({c: v for c, v in r.items() if c != "elegidos"} | {"h3": list(h3_cb[r["elegidos"]])})
        log.info("p-mediana k=%d: %.1f → %.1f min", k, r["t_medio_antes"], r["t_medio_despues"])

    lineas = trazar_linea(cand, Ts["pendiente"], w, est)
    ref = personas_por_km_red(acc, lineas_gtfs)
    n = elegir_n(lineas, ref)
    fila = lineas.set_index("n_estaciones").loc[n]
    nuevas = cand.iloc[list(fila["secuencia"])][["h3", "geometry"]].reset_index(drop=True)
    nuevas["id"] = [f"N{i + 1}" for i in range(len(nuevas))]
    m, est_nuevas = evaluar(nuevas, acc, a, nod)
    resumen = resumen_propuesta(m, float(fila["km"]), eq) | {
        "origen": fila["origen"], "n_estaciones": n, "referencia_personas_por_km_red": ref}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dem.drop(columns="geometry").to_parquet(OUT_DIR / "demanda_h3.parquet", index=False)
    bol.to_parquet(OUT_DIR / "bolsones.parquet", index=False)
    cand.to_crs(CRS_WGS84).to_parquet(OUT_DIR / "candidatos.parquet")
    curva.to_parquet(OUT_DIR / "curva_mclp.parquet", index=False)
    elegidos.to_parquet(OUT_DIR / "mclp_elegidos.parquet", index=False)
    pd.DataFrame(pmed).to_parquet(OUT_DIR / "pmediana.parquet", index=False)
    lineas.assign(secuencia=lineas["secuencia"].map(lambda s: [cand["h3"].iat[j] for j in s])).to_parquet(
        OUT_DIR / "lineas_haz.parquet", index=False)
    linea = gpd.GeoDataFrame([{"origen": fila["origen"], "km": fila["km"]}],
                             geometry=[geometria_linea(fila, cand, est)], crs=CRS_METRIC)
    linea.to_crs(CRS_WGS84).to_parquet(OUT_DIR / "linea_propuesta.parquet")
    nuevas.merge(est_nuevas, on="id").to_crs(CRS_WGS84).to_parquet(OUT_DIR / "estaciones_propuestas.parquet")
    m.to_parquet(OUT_DIR / "manzanos_propuesta.parquet", index=False)
    (OUT_DIR / "resumen_propuesta.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "pasajeros_propuesta.json").write_text(
        json.dumps(pasajeros(est_nuevas), ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Propuesta: %d estaciones desde %s, %.1f km, %d personas nuevas a ≤15 min (%.0f/km)",
             n, fila["origen"], fila["km"], resumen["personas_nuevas_15"], resumen["personas_nuevas_por_km"])
    comparaciones(acc, a, nod, est, resumen)


# --- Comparaciones: líneas actuales y proyecto anunciado ---------------------------------------

# Extensión anunciada de la Línea Café (Las Villas → Pampahasi, Ley N° 1759, crédito BID BO-L1229).
# Punto de Pampahasi en OSM: nodo 1740962925.
PAMPAHASI = (-68.1037712, -16.4997213)


def rendimiento_lineas(acc: pd.DataFrame, aristas: pd.DataFrame, nod: gpd.GeoDataFrame,
                       est: gpd.GeoDataFrame, mz: gpd.GeoDataFrame) -> pd.DataFrame:
    """Población a ≤ 15 min de alguna estación de cada línea, por km de cable."""
    T = ac.tiempos_por_estacion(aristas, nod, est, variantes=("pendiente",))
    _, por_est = ac.acceso_manzanos(mz, nod, est, T)
    pers = mz["personas"].to_numpy()
    km = gpd.read_parquet(PROCESSED / "red" / "lineas.parquet").groupby("linea")["longitud_m"].sum() / 1000
    andenes = pd.read_parquet(PROCESSED / "red" / "andenes.parquet")
    filas = []
    for linea, g in andenes.groupby("linea"):
        cub = (por_est["pendiente"][est.index[est["slug"].isin(g["slug"])]] <= UMBRAL_MIN).any(axis=0)
        filas.append({"linea": linea, "km": km[linea], "personas_15": float(pers[cub].sum())})
    df = pd.DataFrame(filas)
    df["personas_por_km"] = df["personas_15"] / df["km"]
    return df


def contraste_pampahasi(acc: pd.DataFrame, aristas: pd.DataFrame, nod: gpd.GeoDataFrame,
                        est: gpd.GeoDataFrame, mz: gpd.GeoDataFrame, dem_h: pd.DataFrame) -> dict:
    p = gpd.GeoDataFrame({"id": ["Pampahasi"]}, geometry=gpd.points_from_xy(*[[c] for c in PAMPAHASI]),
                         crs=CRS_WGS84).to_crs(CRS_METRIC)
    m, est_p = evaluar(p, acc, aristas, nod, mz)
    km = est.set_index("slug").geometry["las_villas"].distance(p.geometry.iat[0]) / 1000
    celda = h3.latlng_to_cell(PAMPAHASI[1], PAMPAHASI[0], 9)
    bolson = dem_h.loc[dem_h["h3"] == celda, "bolson"]
    return resumen_propuesta(m, km) | {
        "lon": PAMPAHASI[0], "lat": PAMPAHASI[1], "bolson": int(bolson.iat[0]) if len(bolson) else None,
        "abordajes": pasajeros(est_p)[demand_model.EXTENDIDO]["total"],
    }


def comparaciones(acc=None, aristas=None, nod=None, est=None, resumen=None) -> None:
    """Rendimiento por km de las líneas actuales y contraste con Pampahasi (sin rehacer la optimización)."""
    acc = acc if acc is not None else pd.read_parquet(ac.OUT_DIR / "manzanos_acceso.parquet")
    nod = nod if nod is not None else ac.nodos()
    aristas = aristas if aristas is not None else ac.aristas_tiempo()
    est = est if est is not None else gpd.read_parquet(PROCESSED / "red" / "estaciones.parquet").to_crs(CRS_METRIC)
    resumen = resumen or json.loads((OUT_DIR / "resumen_propuesta.json").read_text(encoding="utf-8"))
    mz = ac.manzanos_centroides()
    rl = rendimiento_lineas(acc, aristas, nod, est, mz)
    rl = pd.concat([rl, pd.DataFrame([{"linea": "Propuesta", "km": resumen["km_cable"],
                                        "personas_15": resumen["personas_nuevas_15"],
                                        "personas_por_km": resumen["personas_nuevas_por_km"]}])], ignore_index=True)
    rl.to_parquet(OUT_DIR / "rendimiento_lineas.parquet", index=False)
    dem_h = pd.read_parquet(OUT_DIR / "demanda_h3.parquet")
    cp = contraste_pampahasi(acc, aristas, nod, est, mz, dem_h)
    (OUT_DIR / "contraste_pampahasi.json").write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Pampahasi: %d personas nuevas (%.0f/km)", cp["personas_nuevas_15"], cp["personas_nuevas_por_km"])
