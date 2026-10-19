"""Rutas, URLs de fuentes y constantes compartidas por todo el proyecto."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"

# --- Fuentes (ver docs/plan.md §4) ---
MT_INDICADORES_URL = (
    "https://adminweb.miteleferico.bo/uploads/"
    "INDICADORTES_DIC_2025_final_comprimido_934425e7d3.pdf"
)
GTFS_URL = "https://datosbolivia.github.io/gtfs/mi-teleferico.zip"
CENSO_RELEASE_URL = (
    "https://github.com/lab-tecnosocial/censosbo/releases/download/data-fichas-v1.0.0"
)
CENSO_FILES = {
    "geo_manzano": "geo_manzano_dep02.parquet",  # polígonos de manzanos, depto. La Paz
    "unidad": "unidad.parquet",  # personas y viviendas por unidad censal (todo el país)
    "ficha": "ficha.parquet",  # 194 indicadores por unidad censal (todo el país)
    "diccionario": "diccionario_fichas_v1.parquet",
}
# Teselas COG de Copernicus GLO-30 en AWS Open Data (sin credenciales).
DEM_TILE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
)

# --- Área de estudio ---
# Códigos INE: departamento 02 (La Paz), provincia 01 (Murillo).
MUNICIPIOS = {"01": "La Paz", "05": "El Alto"}
IDEP, IPROV = "02", "01"

# CRS métrico para distancias/áreas: WGS 84 / UTM zona 19S.
CRS_METRIC = "EPSG:32719"
CRS_WGS84 = "EPSG:4326"

H3_RES = 9
# Margen alrededor de la mancha urbana al construir el grafo peatonal.
STUDY_AREA_BUFFER_M = 1000

# Líneas del teleférico: código del PDF -> nombre y color oficial (GTFS).
LINEAS = {
    "LRO": "Roja",
    "LAM": "Amarilla",
    "LVE": "Verde",
    "LAZ": "Azul",
    "LNA": "Naranja",
    "LBL": "Blanca",
    "LCE": "Celeste",
    "LMO": "Morada",
    "LCA": "Café",
    "LPL": "Plateada",
}
