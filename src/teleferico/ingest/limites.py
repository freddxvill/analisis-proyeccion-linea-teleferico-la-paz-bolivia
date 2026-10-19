"""Límites administrativos desde OpenStreetMap (vía Nominatim, por id de relación).

- Municipios (admin_level=8): La Paz y El Alto.
- Macrodistritos urbanos de La Paz (admin_level=9): los 7 de la mancha urbana.
  Hampaturi y Zongo (rurales) no están en OSM y casi no tienen manzanos en el área de estudio.
- Distritos de El Alto: OSM solo tiene 3 de 14 (verificado con Overpass el 2026-10-19), así que no
  se usan; en El Alto la agregación submunicipal se hace con hexágonos H3.
"""

import logging

import geopandas as gpd
import osmnx as ox

from teleferico.config import CRS_WGS84, INTERIM, PROCESSED

log = logging.getLogger(__name__)

LIMITES_PATH = PROCESSED / "limites.parquet"

MUNICIPIOS_OSM = {"R4499870": "La Paz", "R4499832": "El Alto"}
MACRODISTRITOS_OSM = {
    "R10012645": "Centro",
    "R10012644": "Cotahuma",
    "R10012647": "Max Paredes",
    "R10012646": "Periférica",
    "R10012643": "San Antonio",
    "R10012642": "Sur",
    "R10012641": "Mallasa",
}


def run(overwrite: bool = False) -> gpd.GeoDataFrame:
    if LIMITES_PATH.exists() and not overwrite:
        log.info("En caché: %s", LIMITES_PATH.name)
        return gpd.read_parquet(LIMITES_PATH)
    ox.settings.cache_folder = str(INTERIM / "osm" / "cache")
    ids = {**MUNICIPIOS_OSM, **MACRODISTRITOS_OSM}
    gdf = ox.geocode_to_gdf(list(ids), by_osmid=True)
    gdf = gpd.GeoDataFrame({
        "osm_id": list(ids),
        "nombre": list(ids.values()),
        "nivel": ["municipio"] * len(MUNICIPIOS_OSM) + ["macrodistrito"] * len(MACRODISTRITOS_OSM),
        "municipio": ["La Paz", "El Alto"] + ["La Paz"] * len(MACRODISTRITOS_OSM),
    }, geometry=gdf.geometry.values, crs=CRS_WGS84)
    LIMITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(LIMITES_PATH)
    log.info("Límites: %d municipios, %d macrodistritos", len(MUNICIPIOS_OSM), len(MACRODISTRITOS_OSM))
    return gdf
