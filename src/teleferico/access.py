"""Accesibilidad peatonal a Mi Teleférico con pendiente (Fase 3).

Modelo:
- Velocidad de caminata de Tobler, v = 6·exp(−3.5·|s + 0.05|) km/h, **direccional**: s es la
  pendiente en el sentido de la marcha (subir ≠ bajar). La caminata "plana" usa la misma función
  con s = 0 (≈ 5,04 km/h), así las dos variantes solo difieren por la pendiente.
- La pendiente no se toma solo entre los extremos de la arista: se muestrea el DEM cada
  PASO_PERFIL_M a lo largo de su geometría y el tiempo es la suma por tramo. Una calle que baja y
  vuelve a subir cuesta más que su pendiente neta.
- Tiempo **desde cada nodo hasta la estación** (el viaje de la casa al cable): Dijkstra sobre el
  grafo invertido, con un súper-origen por estación unido a los nodos a ≤ RADIO_ACCESO_M de ella.
- Cada manzano toma el tiempo de su nodo más cercano más la caminata recta (plana) hasta él.
"""

import logging

import geopandas as gpd
import h3
import numpy as np
import osmnx as ox
import pandas as pd
import rasterio
import shapely
from pyproj import Transformer
from scipy import sparse
from scipy.ndimage import gaussian_filter
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

from teleferico.config import CRS_METRIC, CRS_WGS84, INTERIM, PROCESSED
from teleferico.ingest.censo import OUT_DIR as CENSO_DIR
from teleferico.ingest.dem import ARISTAS_PATH, DEM_PATH, GRAFO_ELEV_PATH, NODATA
from teleferico.ingest.limites import LIMITES_PATH

log = logging.getLogger(__name__)

OUT_DIR = PROCESSED / "accesibilidad"
NODOS_PATH = INTERIM / "osm" / "nodos_elev.parquet"
ARISTAS_TIEMPO_PATH = INTERIM / "osm" / "aristas_tiempo.parquet"

BANDAS_MIN = [5, 10, 15, 20]
UMBRAL_MIN = 15  # umbral principal de "cubierto"
BUFFER_CLASICO_M = 500  # buffer euclidiano típico de los estudios de cobertura
ESCENARIOS = ["euclidiano", "plana", "pendiente"]

PASO_PERFIL_M = 30  # ~ resolución del DEM (GLO-30)
# Suavizado del DEM antes de muestrear perfiles: GLO-30 es un DSM y los techos meten "baches"
# de pocos metros que, a 30 m de paso, se leen como subidas y bajadas falsas.
SIGMA_SUAVIZADO_PX = 1.0
# Recorte de la pendiente por tramo: más allá del 50 % (~27°) es casi siempre ruido del DSM
# (bordes de edificios o quebradas) y no una calle; las gradas reales quedan por debajo.
PENDIENTE_MAX = 0.5
RADIO_ACCESO_M = 75  # nodos de la red que se consideran "puerta" de una estación
LIMITE_MIN = 60  # Dijkstra no explora más allá (los manzanos más lejos quedan en inf)
H3_ISOCRONAS = 10


def tobler_kmh(s):
    return 6 * np.exp(-3.5 * np.abs(np.asarray(s) + 0.05))


V_PLANA_KMH = float(tobler_kmh(0.0))
V_PLANA_MS = V_PLANA_KMH / 3.6


# --- Red ---------------------------------------------------------------------------------

def nodos(overwrite: bool = False) -> gpd.GeoDataFrame:
    """Nodos de la red peatonal con elevación, en CRS métrico (caché en interim)."""
    if NODOS_PATH.exists() and not overwrite:
        return gpd.read_parquet(NODOS_PATH)
    G = ox.load_graphml(GRAFO_ELEV_PATH)
    n = ox.graph_to_gdfs(G, edges=False)[["elevation", "street_count", "geometry"]].to_crs(CRS_METRIC)
    n.index.name = "osmid"
    n.to_parquet(NODOS_PATH)
    return n


def _dem_suavizado() -> tuple[np.ndarray, rasterio.Affine, object]:
    with rasterio.open(DEM_PATH) as src:
        z = src.read(1).astype("float64")
        transform, crs = src.transform, src.crs
    valido = z != NODATA
    if SIGMA_SUAVIZADO_PX > 0:
        # Suavizado normalizado: los píxeles sin dato (fuera del recorte) no contaminan el borde.
        num = gaussian_filter(np.where(valido, z, 0), SIGMA_SUAVIZADO_PX)
        den = gaussian_filter(valido.astype("float64"), SIGMA_SUAVIZADO_PX)
        z = np.where(valido, num / np.maximum(den, 1e-9), NODATA)
    return z, transform, crs


def muestrear_dem(x: np.ndarray, y: np.ndarray, dem=None) -> np.ndarray:
    """Elevación (m) en puntos con coordenadas en CRS_METRIC; NaN fuera del recorte del DEM."""
    z, transform, crs = dem or _dem_suavizado()
    lon, lat = Transformer.from_crs(CRS_METRIC, crs, always_xy=True).transform(x, y)
    filas, cols = rasterio.transform.rowcol(transform, lon, lat)
    filas, cols = np.asarray(filas), np.asarray(cols)
    dentro = (filas >= 0) & (filas < z.shape[0]) & (cols >= 0) & (cols < z.shape[1])
    out = np.full(len(filas), np.nan)
    out[dentro] = z[filas[dentro], cols[dentro]]
    return np.where(out == NODATA, np.nan, out)  # NaN = fuera del recorte del DEM


def perfil_aristas(aristas: gpd.GeoDataFrame, paso_m: float = PASO_PERFIL_M) -> pd.DataFrame:
    """Tiempo de caminata por arista (en su sentido u→v) muestreando el DEM a lo largo de la geometría.

    Devuelve, por arista: t_pendiente_s, t_plana_s, t_neta_s (solo pendiente entre extremos),
    subida_m y bajada_m acumuladas en el perfil.
    """
    geoms = aristas.geometry.to_crs(CRS_METRIC).values
    largo = aristas["length"].to_numpy()
    n_seg = np.maximum(1, np.round(largo / paso_m)).astype(int)
    n_pts = n_seg + 1

    arista_pt = np.repeat(np.arange(len(aristas)), n_pts)
    inicio = np.repeat(np.cumsum(n_pts) - n_pts, n_pts)
    frac = (np.arange(n_pts.sum()) - inicio) / np.repeat(n_seg, n_pts)
    pts = shapely.line_interpolate_point(geoms[arista_pt], frac, normalized=True)
    z = muestrear_dem(shapely.get_x(pts), shapely.get_y(pts))
    if np.isnan(z).any():
        # Pocas aristas largas salen del recorte: se interpola dentro de la misma arista.
        malas = np.unique(arista_pt[np.isnan(z)])
        log.info("%d aristas con puntos fuera del DEM; se interpolan", len(malas))
        sel = np.isin(arista_pt, malas)
        z[sel] = (pd.Series(z[sel]).groupby(arista_pt[sel])
                  .transform(lambda s: s.interpolate(limit_direction="both")).to_numpy())

    # Tramos: pares de puntos consecutivos de la misma arista.
    dz = np.diff(z)
    es_tramo = arista_pt[1:] == arista_pt[:-1]
    dz, arista_seg = dz[es_tramo], arista_pt[1:][es_tramo]
    largo_seg = (largo / n_seg)[arista_seg]
    s = np.clip(dz / largo_seg, -PENDIENTE_MAX, PENDIENTE_MAX)
    t_seg = largo_seg / (tobler_kmh(s) / 3.6)

    n = len(aristas)
    s_neta = np.clip(aristas["grade"].to_numpy(), -PENDIENTE_MAX, PENDIENTE_MAX)
    return pd.DataFrame({
        "t_pendiente_s": np.bincount(arista_seg, t_seg, minlength=n),
        "t_plana_s": largo / V_PLANA_MS,
        "t_neta_s": largo / (tobler_kmh(s_neta) / 3.6),
        "subida_m": np.bincount(arista_seg, np.clip(dz, 0, None), minlength=n),
        "bajada_m": np.bincount(arista_seg, np.clip(-dz, 0, None), minlength=n),
    }, index=aristas.index)


def aristas_tiempo(overwrite: bool = False) -> gpd.GeoDataFrame:
    """Aristas con tiempos de caminata (caché en interim; ~1 min la primera vez)."""
    if ARISTAS_TIEMPO_PATH.exists() and not overwrite:
        return gpd.read_parquet(ARISTAS_TIEMPO_PATH)
    a = gpd.read_parquet(ARISTAS_PATH)
    a = a.join(perfil_aristas(a))
    a.to_parquet(ARISTAS_TIEMPO_PATH)
    return a


# --- Dijkstra multi-origen -------------------------------------------------------------------

def _matriz(u, v, w, n) -> sparse.csr_matrix:
    """Matriz de adyacencia con el mínimo peso entre aristas paralelas (csr suma duplicados)."""
    df = pd.DataFrame({"u": u, "v": v, "w": np.maximum(w, 1e-3)}).groupby(["u", "v"], sort=False)["w"].min()
    return sparse.csr_matrix((df.to_numpy(), (df.index.get_level_values(0), df.index.get_level_values(1))),
                             shape=(n, n))


def accesos_estaciones(estaciones: gpd.GeoDataFrame, nod: gpd.GeoDataFrame, tree: cKDTree):
    """(estación, índice de nodo, segundos de caminata recta estación↔nodo) para cada "puerta"."""
    xy = np.column_stack([estaciones.geometry.x, estaciones.geometry.y])
    filas = []
    for k, (x, y) in enumerate(xy):
        idx = set(tree.query_ball_point((x, y), RADIO_ACCESO_M)) | {int(tree.query((x, y))[1])}
        for i in idx:
            d = float(np.hypot(*(tree.data[i] - (x, y))))
            filas.append((k, i, d / V_PLANA_MS))
    return np.array(filas)


def tiempos_por_estacion(aristas: pd.DataFrame, nod: gpd.GeoDataFrame, estaciones: gpd.GeoDataFrame,
                         variantes=("pendiente", "pendiente_salida", "plana"), limite_min: float = LIMITE_MIN,
                         columnas: np.ndarray | None = None) -> dict:
    """Matrices (estación × nodo) de minutos de caminata para cada variante.

    - "pendiente": del nodo a la estación (grafo invertido), con Tobler direccional.
    - "pendiente_salida": de la estación al nodo (para medir la asimetría subida/bajada).
    - "plana": sin pendiente (simétrica).

    `columnas` (índices posicionales de nodos) recorta la salida, para usarla con miles de
    puntos candidatos sin guardar la matriz completa.
    """
    pos = pd.Series(np.arange(len(nod)), index=nod.index)
    u, v = pos[aristas["u"]].to_numpy(), pos[aristas["v"]].to_numpy()
    n, k = len(nod), len(estaciones)
    acc = accesos_estaciones(estaciones, nod, cKDTree(np.column_stack([nod.geometry.x, nod.geometry.y])))
    # Súper-origen por estación (índices n..n+k-1): solo tiene aristas salientes hacia sus puertas,
    # así que ningún camino puede atravesarlo.
    sup, puerta, t_acc = n + acc[:, 0].astype(int), acc[:, 1].astype(int), acc[:, 2]
    origenes = np.arange(n, n + k)

    def correr(src, dst, w):
        M = _matriz(np.r_[src, sup], np.r_[dst, puerta], np.r_[w, t_acc], n + k)
        d = dijkstra(M, directed=True, indices=origenes, limit=limite_min * 60)
        d = d[:, :n] if columnas is None else d[:, columnas]
        return (d / 60).astype("float32")

    argumentos = {
        "pendiente": (v, u, "t_pendiente_s"),  # invertido: nodo → estación
        "pendiente_salida": (u, v, "t_pendiente_s"),
        "plana": (u, v, "t_plana_s"),
    }
    return {var: correr(a, b, aristas[w].to_numpy()) for var, (a, b, w) in argumentos.items() if var in variantes}


def ruta(aristas: pd.DataFrame, nod: gpd.GeoDataFrame, origen: tuple, destino: tuple) -> dict:
    """Ruta más rápida a pie entre dos puntos (lon, lat): minutos y km con y sin pendiente.

    Incluye la caminata recta (plana) desde cada punto hasta su nodo más cercano.
    """
    pos = pd.Series(np.arange(len(nod)), index=nod.index)
    u, v = pos[aristas["u"]].to_numpy(), pos[aristas["v"]].to_numpy()
    tree = cKDTree(np.column_stack([nod.geometry.x, nod.geometry.y]))
    xy = gpd.GeoSeries(gpd.points_from_xy(*zip(origen, destino)), crs=CRS_WGS84).to_crs(CRS_METRIC)
    (d_o, d_d), (i_o, i_d) = tree.query(np.column_stack([xy.x, xy.y]))
    extra_min = (d_o + d_d) / V_PLANA_MS / 60
    largo = _matriz(u, v, aristas["length"].to_numpy(), len(nod))
    out = {}
    for var in ("pendiente", "plana"):
        M = _matriz(u, v, aristas[f"t_{var}_s"].to_numpy(), len(nod))
        d, pred = dijkstra(M, indices=i_o, return_predecessors=True)
        camino, j = [i_d], i_d
        while pred[j] >= 0:
            j = pred[j]
            camino.append(j)
        camino = camino[::-1]
        out[f"min_{var}"] = d[i_d] / 60 + extra_min
        out[f"km_{var}"] = sum(largo[a, b] for a, b in zip(camino[:-1], camino[1:])) / 1000
    z = nod["elevation"].to_numpy()
    out["desnivel_m"] = z[i_d] - z[i_o]
    return out


# --- Asignación a manzanos ------------------------------------------------------------------

def manzanos_centroides() -> gpd.GeoDataFrame:
    mz = pd.read_parquet(CENSO_DIR / "manzanos.parquet",
                         columns=["codigo", "municipio", "personas", "viviendas", "ficha", "lon", "lat"])
    gdf = gpd.GeoDataFrame(mz, geometry=gpd.points_from_xy(mz["lon"], mz["lat"]), crs=CRS_WGS84)
    lim = gpd.read_parquet(LIMITES_PATH).query("nivel == 'macrodistrito'")[["nombre", "geometry"]]
    gdf = gdf.sjoin(lim, how="left", predicate="within").drop(columns="index_right")
    # Manda el municipio del censo: los límites de OSM no calzan exacto con los del INE en el borde.
    gdf["zona"] = gdf.pop("nombre").where(gdf["municipio"] == "La Paz", gdf["municipio"])
    # Manzanos de La Paz fuera de los 7 macrodistritos urbanos (bordes rurales).
    gdf["zona"] = gdf["zona"].fillna("La Paz (otros)")
    return gdf.drop_duplicates("codigo").to_crs(CRS_METRIC)


def acceso_manzanos(mz: gpd.GeoDataFrame, nod: gpd.GeoDataFrame, estaciones: gpd.GeoDataFrame,
                    tiempos: dict) -> tuple[pd.DataFrame, dict]:
    """Minutos a la estación más cercana por variante (+ distancia euclidiana) para cada manzano.

    Devuelve la tabla de manzanos y las matrices (estación × manzano) para análisis por estación.
    """
    tree = cKDTree(np.column_stack([nod.geometry.x, nod.geometry.y]))
    xy = np.column_stack([mz.geometry.x, mz.geometry.y])
    d_nodo, i_nodo = tree.query(xy)
    pen = d_nodo / V_PLANA_MS / 60
    slugs = estaciones["slug"].to_numpy()

    out = mz[["codigo", "municipio", "zona", "personas", "viviendas", "ficha", "lon", "lat"]].copy()
    out["d_nodo_m"] = d_nodo.round(1)
    por_estacion = {}
    for var, T in tiempos.items():
        t = T[:, i_nodo] + pen  # estación × manzano
        por_estacion[var] = t
        out[f"t_{var}_min"] = t.min(axis=0)
        out[f"estacion_{var}"] = np.where(np.isfinite(out[f"t_{var}_min"]), slugs[t.argmin(axis=0)], None)

    exy = np.column_stack([estaciones.geometry.x, estaciones.geometry.y])
    d = np.hypot(xy[:, None, 0] - exy[None, :, 0], xy[:, None, 1] - exy[None, :, 1]).T
    por_estacion["euclidiano_m"] = d
    out["d_euclid_m"] = d.min(axis=0).round(1)
    out["estacion_euclid"] = slugs[d.argmin(axis=0)]
    # Equivalente en minutos de la distancia recta a velocidad plana (para comparar en las mismas bandas).
    out["t_euclidiano_min"] = out["d_euclid_m"] / V_PLANA_MS / 60
    return out, por_estacion


def captacion_estaciones(acc: pd.DataFrame, por_estacion: dict, estaciones: gpd.GeoDataFrame) -> pd.DataFrame:
    """Población por estación: dentro de su propia isócrona (con solapes) y exclusiva (estación más cercana)."""
    pers = acc["personas"].to_numpy()
    df = estaciones[["slug", "nombre", "municipio"]].copy().reset_index(drop=True)
    for var in ("pendiente", "plana"):
        t = por_estacion[var]
        for b in BANDAS_MIN:
            df[f"pob_{var}_{b}"] = ((t <= b) * pers).sum(axis=1)
        cerca = acc[f"estacion_{var}"]
        dentro = acc[f"t_{var}_min"] <= UMBRAL_MIN
        excl = acc[dentro].groupby(cerca[dentro])["personas"].sum()
        df[f"pob_exclusiva_{var}_{UMBRAL_MIN}"] = df["slug"].map(excl).fillna(0)
    d = por_estacion["euclidiano_m"]
    df[f"pob_buffer_{BUFFER_CLASICO_M}m"] = ((d <= BUFFER_CLASICO_M) * pers).sum(axis=1)
    return df


# --- Resúmenes ------------------------------------------------------------------------------

def cobertura(acc: pd.DataFrame, por: str | None = None, bandas=BANDAS_MIN) -> pd.DataFrame:
    """% de la población a ≤ b minutos (acumulado) por variante, opcionalmente por grupo."""
    filas = []
    grupos = [("Total", acc)] if por is None else list(acc.groupby(por))
    for g, df in grupos:
        tot = df["personas"].sum()
        for var in ESCENARIOS:
            fila = {"grupo": g, "escenario": var, "poblacion": tot}
            for b in bandas:
                fila[f"pct_{b}"] = df.loc[df[f"t_{var}_min"] <= b, "personas"].sum() / tot * 100
            filas.append(fila)
    return pd.DataFrame(filas)


def curva_cobertura(acc: pd.DataFrame, var: str, minutos=np.arange(0, 61), por: str | None = None) -> pd.DataFrame:
    """% acumulado de población por minuto de caminata (para curvas tipo CDF)."""
    grupos = [("Total", acc)] if por is None else list(acc.groupby(por))
    filas = []
    for g, df in grupos:
        t, w = df[f"t_{var}_min"].to_numpy(), df["personas"].to_numpy()
        tot = w.sum()
        filas += [{"grupo": g, "minutos": m, "pct": w[t <= m].sum() / tot * 100} for m in minutos]
    return pd.DataFrame(filas)


def por_h3(acc: pd.DataFrame, res: int = 9) -> pd.DataFrame:
    """Agregación por hexágono H3 (centroide del manzano), con tiempos ponderados por población."""
    df = acc.assign(h3=[h3.latlng_to_cell(la, lo, res) for la, lo in zip(acc["lat"], acc["lon"])])
    df = df[df["personas"] > 0]
    filas = []
    for var in ESCENARIOS:
        t = df[f"t_{var}_min"].clip(upper=LIMITE_MIN)  # inf → tope, para que la media sea finita
        df[f"tp_{var}"] = t * df["personas"]
        df[f"cub_{var}"] = (df[f"t_{var}_min"] <= UMBRAL_MIN) * df["personas"]
    g = df.groupby("h3")
    out = pd.DataFrame({
        "personas": g["personas"].sum(),
        "municipio": g["municipio"].agg(lambda s: s.mode().iat[0]),
        "zona": g["zona"].agg(lambda s: s.mode().iat[0]),
    })
    for var in ESCENARIOS:
        out[f"t_{var}_min"] = g[f"tp_{var}"].sum() / out["personas"]
        out[f"pct_cub_{var}"] = g[f"cub_{var}"].sum() / out["personas"] * 100
    out["densidad_hab_km2"] = out["personas"] / h3.average_hexagon_area(res, unit="km^2")
    return out.reset_index()


def hexagonos(ids) -> gpd.GeoSeries:
    """Polígonos (WGS84) de una lista de celdas H3."""
    return gpd.GeoSeries([shapely.Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in ids],
                         crs=CRS_WGS84)


def kpis(acc: pd.DataFrame, eq: pd.DataFrame | None = None) -> dict:
    """Cifras clave de cobertura (para el notebook 03, el sitio y el README)."""
    cob = cobertura(acc).set_index("escenario")
    mun = cobertura(acc, "municipio").set_index(["grupo", "escenario"])
    pob = acc["personas"].sum()
    no_cub = acc.loc[~(acc["t_pendiente_min"] <= UMBRAL_MIN), "personas"].sum()
    dentro = lambda var: acc.loc[acc[f"t_{var}_min"] <= UMBRAL_MIN, "personas"].sum()  # noqa: E731
    out = {
        "poblacion": int(pob),
        "umbral_min": UMBRAL_MIN,
        **{f"pct_{UMBRAL_MIN}min_{v}": round(float(cob.loc[v, f"pct_{UMBRAL_MIN}"]), 1) for v in ESCENARIOS},
        **{f"pct_{UMBRAL_MIN}min_pendiente_{m.lower().replace(' ', '_')}":
           round(float(mun.loc[(m, "pendiente"), f"pct_{UMBRAL_MIN}"]), 1) for m in ("La Paz", "El Alto")},
        **{f"pct_{UMBRAL_MIN}min_plana_{m.lower().replace(' ', '_')}":
           round(float(mun.loc[(m, "plana"), f"pct_{UMBRAL_MIN}"]), 1) for m in ("La Paz", "El Alto")},
        f"pob_no_cubierta_{UMBRAL_MIN}min": int(no_cub),
        "pct_no_cubierta": round(float(no_cub / pob * 100), 1),
        "sobreestimacion_euclid_personas": int(dentro("euclidiano") - dentro("pendiente")),
        "sobreestimacion_plana_personas": int(dentro("plana") - dentro("pendiente")),
        f"pct_buffer_{BUFFER_CLASICO_M}m": round(float(acc.loc[acc["d_euclid_m"] <= BUFFER_CLASICO_M, "personas"].sum()
                                                    / pob * 100), 1),
        "mediana_min_pendiente": round(mediana_ponderada(acc["t_pendiente_min"].clip(upper=LIMITE_MIN),
                                                          acc["personas"]), 1),
    }
    if eq is not None:
        q = eq.groupby("iv_quintil", observed=True).apply(
            lambda g: g.loc[g["t_pendiente_min"] <= UMBRAL_MIN, "personas"].sum() / g["personas"].sum() * 100,
            include_groups=False)
        vulnerables = eq["iv_quintil"].isin(q.index[-2:])
        out |= {
            f"pct_{UMBRAL_MIN}min_q1": round(float(q.iat[0]), 1),
            f"pct_{UMBRAL_MIN}min_q5": round(float(q.iat[-1]), 1),
            "pob_vulnerable_no_cubierta": int(eq.loc[vulnerables & ~(eq["t_pendiente_min"] <= UMBRAL_MIN),
                                                     "personas"].sum()),
        }
    return out


def mediana_ponderada(x: pd.Series, w: pd.Series) -> float:
    orden = np.argsort(x.to_numpy())
    cw = np.cumsum(w.to_numpy()[orden])
    return float(x.to_numpy()[orden][np.searchsorted(cw, cw[-1] / 2)])


def isocronas(T_min: np.ndarray, nod: gpd.GeoDataFrame, bandas=BANDAS_MIN, res: int = H3_ISOCRONAS) -> gpd.GeoDataFrame:
    """Polígonos de isócrona: unión de las celdas H3 cuyos nodos llegan a la estación en ≤ b min."""
    ll = nod.to_crs(CRS_WGS84)
    celda = pd.Series([h3.latlng_to_cell(y, x, res) for x, y in zip(ll.geometry.x, ll.geometry.y)])
    t_celda = pd.Series(T_min.min(axis=0)).groupby(celda).min()
    filas = []
    for b in bandas:
        celdas = t_celda.index[t_celda <= b].tolist()
        geom = shapely.geometry.shape(h3.cells_to_geo(celdas)) if celdas else shapely.Polygon()
        filas.append({"banda_min": b, "geometry": geom})
    return gpd.GeoDataFrame(filas, crs=CRS_WGS84)


def run(overwrite: bool = False) -> None:
    nod = nodos(overwrite)
    a = aristas_tiempo(overwrite)
    est = gpd.read_parquet(PROCESSED / "red" / "estaciones.parquet").to_crs(CRS_METRIC)
    tiempos = tiempos_por_estacion(a, nod, est)
    mz = manzanos_centroides()
    acc, por_est = acceso_manzanos(mz, nod, est, tiempos)
    cap = captacion_estaciones(acc, por_est, est)
    iso = pd.concat([isocronas(tiempos[v], nod).assign(escenario=v) for v in ("pendiente", "plana")],
                    ignore_index=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    acc.to_parquet(OUT_DIR / "manzanos_acceso.parquet", index=False)
    cap.to_parquet(OUT_DIR / "estaciones_captacion.parquet", index=False)
    gpd.GeoDataFrame(iso, crs=CRS_WGS84).to_parquet(OUT_DIR / "isocronas.parquet")
    por_h3(acc).to_parquet(OUT_DIR / "h3_acceso_r9.parquet", index=False)

    cob = cobertura(acc).set_index("escenario")[f"pct_{UMBRAL_MIN}"]
    log.info("Población a ≤%d min: %s", UMBRAL_MIN, {k: round(v, 1) for k, v in cob.items()})
