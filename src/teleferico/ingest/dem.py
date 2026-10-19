"""Elevación (Copernicus GLO-30) y pendiente de cada arista de la red peatonal.

Nota: Copernicus GLO-30 es un modelo de superficie (DSM): en zonas muy edificadas
puede sobreestimar la cota del terreno. Se documenta como limitación.
"""

import json
import logging
import math

import geopandas as gpd
import osmnx as ox
import rasterio
from rasterio.mask import mask
from rasterio.merge import merge

from teleferico.config import CRS_METRIC, CRS_WGS84, DEM_TILE_URL, INTERIM, PROCESSED, RAW
from teleferico.ingest.censo import AREA_ESTUDIO_PATH
from teleferico.ingest.osm import descargar_red
from teleferico.utils import download

log = logging.getLogger(__name__)

RAW_DIR = RAW / "dem"
DEM_PATH = INTERIM / "dem" / "dem_area_estudio.tif"
GRAFO_ELEV_PATH = INTERIM / "osm" / "red_peatonal_elev.graphml"
ARISTAS_PATH = INTERIM / "osm" / "aristas_pendiente.parquet"
RESUMEN_PATH = PROCESSED / "red" / "resumen_pendiente.json"
NODATA = -9999.0
MARGEN_RECORTE_M = 300


def _nombre_tesela(lat_sw: int, lon_sw: int) -> str:
    ns = f"{'N' if lat_sw >= 0 else 'S'}{abs(lat_sw):02d}_00"
    ew = f"{'E' if lon_sw >= 0 else 'W'}{abs(lon_sw):03d}_00"
    return f"Copernicus_DSM_COG_10_{ns}_{ew}_DEM"


def teselas(bounds) -> list[str]:
    minx, miny, maxx, maxy = bounds
    return [
        _nombre_tesela(lat, lon)
        for lat in range(math.floor(miny), math.floor(maxy) + 1)
        for lon in range(math.floor(minx), math.floor(maxx) + 1)
    ]


def preparar_dem(overwrite: bool = False):
    if DEM_PATH.exists() and not overwrite:
        log.info("En caché: %s", DEM_PATH.name)
        return DEM_PATH
    # Margen extra para que los nodos del borde de la red no caigan en píxeles sin dato.
    area = gpd.read_parquet(AREA_ESTUDIO_PATH).to_crs(CRS_METRIC).buffer(MARGEN_RECORTE_M).to_crs(CRS_WGS84)
    rutas = [
        download(DEM_TILE_URL.format(name=n), RAW_DIR / f"{n}.tif", overwrite=overwrite)
        for n in teselas(area.total_bounds)
    ]
    srcs = [rasterio.open(r) for r in rutas]
    try:
        mosaico, transform = merge(srcs)
        meta = srcs[0].meta | {"height": mosaico.shape[1], "width": mosaico.shape[2], "transform": transform}
    finally:
        for s in srcs:
            s.close()

    DEM_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEM_PATH.with_suffix(".mosaico.tif")
    with rasterio.open(tmp, "w", **meta) as dst:
        dst.write(mosaico)
    with rasterio.open(tmp) as src:
        recorte, transform = mask(src, area.to_crs(src.crs), crop=True, all_touched=True, nodata=NODATA)
        meta = src.meta | {"height": recorte.shape[1], "width": recorte.shape[2],
                           "transform": transform, "nodata": NODATA, "compress": "deflate"}
    with rasterio.open(DEM_PATH, "w", **meta) as dst:
        dst.write(recorte)
    tmp.unlink()
    return DEM_PATH


def red_con_pendiente(overwrite: bool = False):
    if GRAFO_ELEV_PATH.exists() and not overwrite:
        log.info("En caché: %s", GRAFO_ELEV_PATH.name)
        return ox.load_graphml(GRAFO_ELEV_PATH)
    G = descargar_red()
    G = ox.elevation.add_node_elevations_raster(G, str(preparar_dem(overwrite)), cpus=1)
    sin_elev = [n for n, z in G.nodes(data="elevation") if z is None or math.isnan(z) or z == NODATA]
    if sin_elev:  # se valida antes de guardar para no dejar un grafo inválido en caché
        raise ValueError(f"{len(sin_elev)} nodos sin elevación (¿recorte del DEM muy ajustado?)")
    # grade = (elev_destino - elev_origen) / longitud: con signo, por sentido de la arista.
    G = ox.elevation.add_edge_grades(G, add_absolute=True)
    ox.save_graphml(G, GRAFO_ELEV_PATH)
    return G


def run(overwrite: bool = False):
    G = red_con_pendiente(overwrite)
    nodes, edges = ox.graph_to_gdfs(G)
    sin_elev = nodes["elevation"].isna().sum()
    assert sin_elev == 0, f"{sin_elev} nodos sin elevación"

    aristas = edges.reset_index()[["u", "v", "key", "length", "grade", "grade_abs", "highway", "geometry"]]
    aristas["highway"] = aristas["highway"].astype(str)
    ARISTAS_PATH.parent.mkdir(parents=True, exist_ok=True)
    aristas.to_parquet(ARISTAS_PATH)

    # Pendiente ponderada por longitud (las aristas cortas no deben pesar igual que las largas).
    w = aristas["length"]
    resumen = {
        "nodos": len(nodes),
        "nodos_sin_elevacion": int(sin_elev),
        "elevacion_min_m": round(float(nodes["elevation"].min()), 1),
        "elevacion_max_m": round(float(nodes["elevation"].max()), 1),
        "pendiente_abs_media_pct": round(float((aristas["grade_abs"] * w).sum() / w.sum() * 100), 2),
        "pendiente_abs_p90_pct": round(float(aristas["grade_abs"].quantile(0.9) * 100), 2),
        "km_con_pendiente_mayor_10pct": round(float(w[aristas["grade_abs"] > 0.10].sum() / 2000), 1),
        "km_totales": round(float(w.sum() / 2000), 1),
    }
    RESUMEN_PATH.write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(
        "DEM: elevación %.0f-%.0f m; pendiente media |s| = %.1f%%; %.0f de %.0f km con |s| > 10%%",
        resumen["elevacion_min_m"], resumen["elevacion_max_m"], resumen["pendiente_abs_media_pct"],
        resumen["km_con_pendiente_mayor_10pct"], resumen["km_totales"],
    )
    return G
