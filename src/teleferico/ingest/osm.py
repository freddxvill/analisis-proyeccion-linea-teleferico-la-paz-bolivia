"""Red peatonal de La Paz y El Alto desde OpenStreetMap (OSMnx).

Se descarga sobre el área de estudio (mancha urbana + margen) que genera `censo.py`.
El grafo crudo queda en data/interim (pesado, no versionado) y un resumen en processed.
"""

import json
import logging

import geopandas as gpd
import osmnx as ox

from teleferico.config import INTERIM, PROCESSED
from teleferico.ingest.censo import AREA_ESTUDIO_PATH

log = logging.getLogger(__name__)

GRAFO_PATH = INTERIM / "osm" / "red_peatonal.graphml"
RESUMEN_PATH = PROCESSED / "red" / "resumen_red_peatonal.json"

# Servidores Overpass a probar en orden (el público suele saturarse).
OVERPASS_URLS = [
    "https://overpass-api.de/api",
    "https://overpass.private.coffee/api",
    "https://overpass.kumi.systems/api",
]


def descargar_red(overwrite: bool = False):
    if GRAFO_PATH.exists() and not overwrite:
        log.info("En caché: %s", GRAFO_PATH.name)
        return ox.load_graphml(GRAFO_PATH)
    area = gpd.read_parquet(AREA_ESTUDIO_PATH).geometry.iat[0]
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(INTERIM / "osm" / "cache")
    ox.settings.requests_timeout = 600
    G = None
    for url in OVERPASS_URLS:
        ox.settings.overpass_url = url
        log.info("Descargando red peatonal de OSM desde %s (puede tardar varios minutos)...", url)
        try:
            G = ox.graph_from_polygon(area, network_type="walk", simplify=True, retain_all=False)
            break
        except Exception as e:  # servidor saturado o caído: se prueba el siguiente
            log.warning("Falló %s: %s", url, str(e).splitlines()[0][:200])
    if G is None:
        raise RuntimeError("No se pudo descargar la red peatonal de ningún servidor Overpass")
    GRAFO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(G, GRAFO_PATH)
    return G


def resumen(G) -> dict:
    nodes, edges = ox.graph_to_gdfs(G)
    return {
        "nodos": len(nodes),
        "aristas": len(edges),
        "longitud_km": round(float(edges["length"].sum()) / 1000 / 2, 1),  # aristas en ambos sentidos
        "highway": edges["highway"].astype(str).value_counts().head(12).to_dict(),
    }


def run(overwrite: bool = False):
    G = descargar_red(overwrite)
    r = resumen(G)
    RESUMEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESUMEN_PATH.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Red peatonal: %d nodos, %d aristas, ~%.0f km", r["nodos"], r["aristas"], r["longitud_km"])
    return G
