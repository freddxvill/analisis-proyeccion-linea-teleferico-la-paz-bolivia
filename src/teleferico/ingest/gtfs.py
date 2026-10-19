"""Estaciones, andenes y trazados de Mi Teleférico desde el GTFS comunitario (Datos Bolivia).

Además une la demanda por estación del PDF de indicadores (nombre + código de línea)
con las estaciones físicas del GTFS mediante una tabla de mapeo manual.
"""

import io
import logging
import zipfile

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

from teleferico.config import CRS_WGS84, GTFS_URL, LINEAS, PROCESSED, RAW
from teleferico.utils import download

log = logging.getLogger(__name__)

GTFS_PATH = RAW / "gtfs" / "mi-teleferico.zip"
OUT_DIR = PROCESSED / "red"

# Segmento de línea en el stop_id del GTFS -> nombre de la línea.
LINEA_GTFS = {
    "roja": "Roja", "amarilla": "Amarilla", "verde": "Verde", "azul": "Azul",
    "naranja": "Naranja", "blanca": "Blanca", "celeste": "Celeste",
    "morada_1": "Morada", "morada_2": "Morada", "cafe": "Café", "plateada": "Plateada",
}

# Nombre de estación en el PDF -> slug de la estación en el GTFS.
# El PDF usa nombres de zona; el GTFS usa el nombre oficial (castellano).
ESTACION_PDF_A_GTFS = {
    "San José": "san_jose",
    "6 de Marzo": "6_de_marzo",
    "Mirador": "mirador",
    "Libertador": "libertador",
    "16 de Julio": "16_de_julio",
    "Faro Murillo": "faro_murillo",
    "Central": "estacion_central",
    "Rio Seco": "rio_seco",
    "Villarroel": "villarroel",  # Héroes de la Revolución
    "Sopocachi": "sopocachi",
    "Irpavi": "irpavi",
    "Plaza Libertad": "plaza_libertad",
    "Cementerio": "cementerio",
    "Prado": "prado",
    "UPEA": "upea",
    "Buenos Aires": "buenos_aires",
    "Triangular": "triangular",  # Próceres de la Independencia
    "San Jorge": "del_poeta",  # Del Poeta (zona San Jorge)
    "Plaza La Paz": "plaza_la_paz",
    "Armentia": "armentia",
    "Alto Obrajes": "alto_obrajes",
    "Busch": "busch",  # Defensores del Chaco
    "Periférica": "periferica",
    "Villas": "las_villas",
    "17 de Obrajes": "obrajes",
    "Cancha Zapata": "teatro_al_aire_libre",  # Teatro al Aire Libre (Cancha Zapata)
}


def _leer(z: zipfile.ZipFile, nombre: str) -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(z.read(f"{nombre}.txt")), dtype=str)


def cargar(path=GTFS_PATH) -> dict[str, pd.DataFrame]:
    with zipfile.ZipFile(path) as z:
        return {n: _leer(z, n) for n in ("stops", "routes", "trips", "shapes", "frequencies")}


def estaciones_y_andenes(gtfs: dict[str, pd.DataFrame]) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    stops = gtfs["stops"].copy()
    stops[["stop_lat", "stop_lon"]] = stops[["stop_lat", "stop_lon"]].astype(float)
    stops["slug"] = stops["stop_id"].str.split("/").str[1]

    andenes = stops[stops["location_type"] == "0"].copy()
    andenes["linea"] = andenes["stop_id"].str.split("/").str[3].map(LINEA_GTFS)
    assert andenes["linea"].notna().all(), andenes[andenes["linea"].isna()]

    est = stops[stops["location_type"] == "1"].copy()
    # stop_name = "<nombre aymara> - <nombre castellano>"
    partes = est["stop_name"].str.split(" - ", n=1)
    est["nombre_aymara"] = partes.str[0]
    est["nombre"] = partes.str[1]
    lineas = andenes.groupby("slug")["linea"].agg(lambda s: sorted(set(s)))
    est["lineas"] = est["slug"].map(lineas)
    est["n_lineas"] = est["lineas"].str.len()
    est["transbordo"] = est["n_lineas"] > 1
    # stop_desc empieza con "El Alto, ..." para las estaciones de El Alto; el resto está en La Paz.
    est["municipio"] = est["stop_desc"].str.startswith("El Alto").map({True: "El Alto", False: "La Paz"})
    est = est[["slug", "stop_id", "nombre", "nombre_aymara", "municipio", "lineas", "n_lineas",
               "transbordo", "stop_desc", "stop_lat", "stop_lon"]]

    to_gdf = lambda df: gpd.GeoDataFrame(  # noqa: E731
        df, geometry=gpd.points_from_xy(df["stop_lon"], df["stop_lat"]), crs=CRS_WGS84
    )
    andenes = andenes[["stop_id", "slug", "linea", "stop_name", "stop_lat", "stop_lon"]]
    return to_gdf(est.reset_index(drop=True)), to_gdf(andenes.reset_index(drop=True))


def trazados(gtfs: dict[str, pd.DataFrame]) -> gpd.GeoDataFrame:
    """Un trazado por ruta (se toma la primera dirección de cada ruta)."""
    shapes = gtfs["shapes"].copy()
    shapes[["shape_pt_lat", "shape_pt_lon"]] = shapes[["shape_pt_lat", "shape_pt_lon"]].astype(float)
    shapes["shape_pt_sequence"] = shapes["shape_pt_sequence"].astype(int)
    trips = gtfs["trips"].sort_values(["route_id", "direction_id"]).drop_duplicates("route_id")
    routes = gtfs["routes"].merge(trips[["route_id", "shape_id"]], on="route_id")
    filas = []
    for r in routes.itertuples():
        pts = shapes[shapes["shape_id"] == r.shape_id].sort_values("shape_pt_sequence")
        filas.append({
            "route_id": r.route_id,
            "ruta": r.route_short_name,
            "linea": r.route_short_name.split()[0],
            "nombre": r.route_long_name,
            "color": f"#{r.route_color}",
            "geometry": LineString(zip(pts["shape_pt_lon"], pts["shape_pt_lat"])),
        })
    gdf = gpd.GeoDataFrame(filas, crs=CRS_WGS84)
    gdf["longitud_m"] = gdf.to_crs("EPSG:32719").length.round(1)
    return gdf


def demanda_por_estacion(estaciones: gpd.GeoDataFrame, andenes: gpd.GeoDataFrame) -> pd.DataFrame:
    """Une los rankings del PDF (estación + línea) con las estaciones del GTFS."""
    mt = PROCESSED / "mt"
    tablas = []
    for periodo, archivo in (("2025", "ranking_estaciones_2025"), ("2014_2025", "ranking_estaciones_acumulado")):
        df = pd.read_parquet(mt / f"{archivo}.parquet")
        df["slug"] = df["estacion"].map(ESTACION_PDF_A_GTFS)
        sin_mapeo = df[df["slug"].isna()]
        assert sin_mapeo.empty, f"Estaciones del PDF sin mapeo GTFS:\n{sin_mapeo}"
        df["periodo"] = periodo
        tablas.append(df)
    dem = pd.concat(tablas, ignore_index=True)

    # Cada par (estación, línea) del PDF debe existir como andén en el GTFS y viceversa.
    pares_gtfs = set(map(tuple, andenes[["slug", "linea"]].drop_duplicates().to_numpy()))
    for periodo, g in dem.groupby("periodo"):
        pares_pdf = set(zip(g["slug"], g["linea"]))
        assert pares_pdf == pares_gtfs, (
            f"{periodo}: solo PDF={pares_pdf - pares_gtfs}, solo GTFS={pares_gtfs - pares_pdf}"
        )
    return dem.merge(estaciones[["slug", "nombre"]], on="slug").rename(
        columns={"estacion": "estacion_pdf", "nombre": "estacion_gtfs"}
    )


def run(overwrite: bool = False) -> None:
    download(GTFS_URL, GTFS_PATH, overwrite=overwrite)
    gtfs = cargar()
    est, andenes = estaciones_y_andenes(gtfs)
    lineas = trazados(gtfs)
    dem = demanda_por_estacion(est, andenes)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    est.to_parquet(OUT_DIR / "estaciones.parquet")
    andenes.to_parquet(OUT_DIR / "andenes.parquet")
    lineas.to_parquet(OUT_DIR / "lineas.parquet")
    dem.to_parquet(OUT_DIR / "demanda_estaciones.parquet", index=False)
    dem.to_csv(OUT_DIR / "demanda_estaciones.csv", index=False)
    log.info(
        "GTFS: %d estaciones, %d andenes, %d rutas (%.1f km), %d filas de demanda",
        len(est), len(andenes), len(lineas), lineas["longitud_m"].sum() / 1000, len(dem),
    )
    assert set(lineas["linea"]) == set(LINEAS.values())
