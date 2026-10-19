"""Censo 2024 por manzano (repackaging de lab-tecnosocial/censosbo) para La Paz y El Alto.

Salidas:
- manzanos con población, viviendas y densidad;
- ficha de 194 indicadores por manzano (solo los que el INE libera, ~92 % de la población);
- población agregada en hexágonos H3;
- polígono del área de estudio (mancha urbana + margen), usado para descargar OSM y el DEM.
"""

import logging

import geopandas as gpd
import h3
import pandas as pd
import shapely
from shapely.geometry import Polygon

from teleferico.config import (
    CENSO_FILES, CENSO_RELEASE_URL, CRS_METRIC, CRS_WGS84, H3_RES, IDEP, IPROV,
    MUNICIPIOS, PROCESSED, RAW, STUDY_AREA_BUFFER_M,
)
from teleferico.utils import download

log = logging.getLogger(__name__)

RAW_DIR = RAW / "censo"
OUT_DIR = PROCESSED / "censo"
AREA_ESTUDIO_PATH = PROCESSED / "area_estudio.parquet"

# Manzanos más grandes que esto reparten su población entre los hexágonos que cubren
# en vez de asignarla entera al hexágono de su centroide.
UMBRAL_REPARTO_M2 = 200_000


def descargar(overwrite: bool = False) -> None:
    for archivo in CENSO_FILES.values():
        download(f"{CENSO_RELEASE_URL}/{archivo}", RAW_DIR / archivo, overwrite=overwrite)


def _filtro_area(df: pd.DataFrame) -> pd.Series:
    return (df["idep"] == IDEP) & (df["iprov"] == IPROV) & df["imun"].isin(list(MUNICIPIOS))


def manzanos() -> gpd.GeoDataFrame:
    geo = pd.read_parquet(RAW_DIR / CENSO_FILES["geo_manzano"])
    geo = geo[_filtro_area(geo)]
    gdf = gpd.GeoDataFrame(
        geo[["codigo", "imun"]],
        geometry=shapely.from_wkb(geo["geometria"]),
        crs=CRS_WGS84,
    )

    uni = pd.read_parquet(RAW_DIR / CENSO_FILES["unidad"])
    uni = uni[_filtro_area(uni)]
    rurales = uni[~uni["codigo"].isin(gdf["codigo"])]
    log.info(
        "Unidades sin polígono de manzano (comunidades rurales, fuera de la mancha urbana): "
        "%d con %d personas", len(rurales), rurales["personas"].sum(),
    )

    gdf = gdf.merge(uni[["codigo", "personas", "viviendas", "ficha"]], on="codigo", how="left")
    assert gdf["personas"].notna().all()
    gdf["municipio"] = gdf.pop("imun").map(MUNICIPIOS)
    gdf["area_m2"] = gdf.to_crs(CRS_METRIC).area.round(1)
    gdf["densidad_hab_km2"] = (gdf["personas"] / gdf["area_m2"] * 1e6).round(1)
    cent = gdf.to_crs(CRS_METRIC).centroid.to_crs(CRS_WGS84)
    gdf["lon"], gdf["lat"] = cent.x.round(6), cent.y.round(6)
    return gdf[["codigo", "municipio", "personas", "viviendas", "ficha", "area_m2",
                "densidad_hab_km2", "lon", "lat", "geometry"]]


def ficha(codigos: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    f = pd.read_parquet(RAW_DIR / CENSO_FILES["ficha"])
    f = f[f["codigo"].isin(codigos)].drop(columns=["area", "idep", "iprov", "imun"])
    dic = pd.read_parquet(RAW_DIR / CENSO_FILES["diccionario"])
    dic = dic[dic["tabla"] == "ficha"].reset_index(drop=True)
    return f.reset_index(drop=True), dic


def _celdas_h3(fila) -> list[str]:
    if fila.area_m2 <= UMBRAL_REPARTO_M2:
        return [h3.latlng_to_cell(fila.lat, fila.lon, H3_RES)]
    celdas = h3.geo_to_cells(fila.geometry, H3_RES)
    return list(celdas) or [h3.latlng_to_cell(fila.lat, fila.lon, H3_RES)]


def poblacion_h3(mz: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    df = mz[["codigo", "municipio", "personas", "viviendas", "area_m2", "lat", "lon", "geometry"]].copy()
    df["h3"] = [_celdas_h3(f) for f in df.itertuples()]
    df["peso"] = 1 / df["h3"].str.len()
    df = df.explode("h3")
    df["personas"] = df["personas"] * df["peso"]
    df["viviendas"] = df["viviendas"] * df["peso"]

    agg = df.groupby("h3").agg(
        personas=("personas", "sum"),
        viviendas=("viviendas", "sum"),
        n_manzanos=("codigo", "nunique"),
        municipio=("municipio", lambda s: s.mode().iat[0]),
    ).reset_index()
    diff = agg["personas"].sum() - mz["personas"].sum()
    assert abs(diff) < 1, f"El reparto H3 no conserva la población (diferencia {diff:.2f})"
    agg["personas"] = agg["personas"].round(1)
    agg["viviendas"] = agg["viviendas"].round(1)
    agg["geometry"] = [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in agg["h3"]]
    gdf = gpd.GeoDataFrame(agg, crs=CRS_WGS84)
    gdf["densidad_hab_km2"] = (gdf["personas"] / gdf.to_crs(CRS_METRIC).area * 1e6).round(1)
    return gdf


def area_estudio(mz: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Mancha urbana (manzanos unidos) + margen de STUDY_AREA_BUFFER_M."""
    m = mz.to_crs(CRS_METRIC)
    mancha = shapely.union_all(m.geometry.buffer(50).values)
    area = mancha.buffer(STUDY_AREA_BUFFER_M).simplify(25)
    # Se conservan solo los polígonos que contienen población relevante (descarta islas mínimas).
    return gpd.GeoDataFrame({"nombre": ["La Paz - El Alto"]}, geometry=[area], crs=CRS_METRIC).to_crs(CRS_WGS84)


def run(overwrite: bool = False) -> None:
    descargar(overwrite)
    mz = manzanos()
    fi, dic = ficha(mz["codigo"])
    hexes = poblacion_h3(mz)
    area = area_estudio(mz)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mz.to_parquet(OUT_DIR / "manzanos.parquet")
    fi.to_parquet(OUT_DIR / "ficha_manzanos.parquet", index=False)
    dic.to_parquet(OUT_DIR / "diccionario_ficha.parquet", index=False)
    hexes.to_parquet(OUT_DIR / f"poblacion_h3_r{H3_RES}.parquet")
    area.to_parquet(AREA_ESTUDIO_PATH)

    por_mun = mz.groupby("municipio")["personas"].sum().to_dict()
    cubierta = mz.loc[mz["ficha"], "personas"].sum() / mz["personas"].sum()
    log.info(
        "Censo: %d manzanos, población %s, ficha disponible para %.1f%% de la población, "
        "%d hexágonos H3 r%d, área de estudio %.0f km²",
        len(mz), por_mun, cubierta * 100, len(hexes), H3_RES,
        area.to_crs(CRS_METRIC).area.iat[0] / 1e6,
    )
