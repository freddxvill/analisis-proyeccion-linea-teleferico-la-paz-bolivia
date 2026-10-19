"""Exporta datos compactos (JSON) para los gráficos ECharts y mapas MapLibre del sitio."""

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from teleferico import access, demanda, equidad
from teleferico.config import CRS_METRIC, CRS_WGS84, PROCESSED, ROOT
from teleferico.viz import COLOR_LINEA, COLOR_OFICIAL, ORDEN_LINEAS, TRAZO_LINEA

log = logging.getLogger(__name__)

SITE_DATA = ROOT / "site" / "data"


def _limpiar(obj):
    """Convierte tipos numpy/pandas y NaN a JSON nativo."""
    if isinstance(obj, dict):
        return {str(k): _limpiar(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_limpiar(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        # 5 decimales: ~1 m en coordenadas; de sobra para porcentajes y tasas.
        return None if np.isnan(obj) else round(float(obj), 5)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.strftime("%Y-%m")
    return obj


def _escribir(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_limpiar(data), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("Escrito %s (%.1f KB)", path.relative_to(ROOT), path.stat().st_size / 1024)


def exportar_demanda(t: dict[str, pd.DataFrame] | None = None) -> None:
    t = t or demanda.cargar()
    out = SITE_DATA / "demanda"

    _escribir(out / "kpis.json", demanda.kpis(t))

    anual = demanda.serie_anual(t["anual"], t["mensual"])
    _escribir(out / "anual.json", anual.to_dict(orient="records"))

    _escribir(out / "mensual.json", t["mensual"].to_dict(orient="records"))

    mat = demanda.matriz_mensual(t["mensual"])
    _escribir(out / "estacionalidad.json", {
        "anios": mat.index.tolist(),
        "meses": demanda.MESES,
        # [indice_mes, indice_anio, pasajeros] (formato heatmap de ECharts)
        "celdas": [[m - 1, i, v] for i, (_, fila) in enumerate(mat.iterrows())
                   for m, v in fila.items() if pd.notna(v)],
        "indice_estacional": demanda.indice_estacional(t["mensual"]).round(3).tolist(),
        "anios_indice": demanda.ANIOS_ESTACIONALIDAD,
    })

    resumen = demanda.resumen_lineas(t)
    pl = t["por_linea"].pivot(index="anio", columns="linea", values="pasajeros")
    indice = demanda.indice_por_linea(t["por_linea"])
    _escribir(out / "lineas.json", {
        "orden": ORDEN_LINEAS,
        "color_oficial": COLOR_OFICIAL,
        "color_marca": COLOR_LINEA,
        "color_trazo": TRAZO_LINEA,
        "resumen_2025": resumen.reset_index().to_dict(orient="records"),
        "anios": pl.index.tolist(),
        "series": {l: pl[l].tolist() for l in ORDEN_LINEAS},
        "indice_2019": {l: indice[l].loc[2019:].tolist() for l in indice.columns},
        "anios_indice": indice.loc[2019:].index.tolist(),
    })

    est = demanda.estaciones_fisicas(t)
    conc = demanda.curva_concentracion(est["pasajeros_est"])
    _escribir(out / "estaciones.json", {
        "estaciones_2025": est.to_dict(orient="records"),
        "concentracion": conc.to_dict(orient="records"),
    })



def _geojson(gdf: gpd.GeoDataFrame) -> dict:
    return json.loads(gdf.to_crs(CRS_WGS84).to_json(drop_id=True))


def exportar_accesibilidad(acc: pd.DataFrame | None = None, eq: pd.DataFrame | None = None) -> None:
    acc = acc if acc is not None else pd.read_parquet(access.OUT_DIR / "manzanos_acceso.parquet")
    eq = eq if eq is not None else equidad.indicadores(acc)
    out = SITE_DATA / "accesibilidad"

    _escribir(out / "kpis.json", access.kpis(acc, eq))

    cob = pd.concat([access.cobertura(acc), access.cobertura(acc, "municipio"), access.cobertura(acc, "zona")])
    _escribir(out / "cobertura.json", cob.to_dict(orient="records"))

    curvas = {var: {g: c["pct"].round(2).tolist() for g, c in
                    pd.concat([access.curva_cobertura(acc, var), access.curva_cobertura(acc, var, por="municipio")])
                    .groupby("grupo")}
              for var in access.ESCENARIOS}
    _escribir(out / "curvas.json", {"minutos": list(range(61)), "curvas": curvas})

    # Hexágonos: tiempos, cobertura y lente de equidad (IV y brecha), para el mapa MapLibre.
    hx = pd.read_parquet(access.OUT_DIR / "h3_acceso_r9.parquet").merge(equidad.por_h3(eq), on="h3", how="left")
    cols = ["h3", "personas", "zona", "densidad_hab_km2", "t_pendiente_min", "t_plana_min", "t_euclidiano_min",
            "pct_cub_pendiente", "iv", "brecha"]
    hx = gpd.GeoDataFrame(hx[cols].round({"personas": 0, "densidad_hab_km2": 0, "t_pendiente_min": 1,
                                          "t_plana_min": 1, "t_euclidiano_min": 1, "pct_cub_pendiente": 1,
                                          "iv": 3, "brecha": 3}),
                          geometry=access.hexagonos(hx["h3"]).values, crs=CRS_WGS84)
    _escribir(out / "hexagonos.geojson", _geojson(hx))

    iso = gpd.read_parquet(access.OUT_DIR / "isocronas.parquet").to_crs(CRS_METRIC)
    iso["geometry"] = iso.geometry.simplify(15)
    _escribir(out / "isocronas.geojson", _geojson(iso))

    t = demanda.cargar()
    cap = pd.read_parquet(access.OUT_DIR / "estaciones_captacion.parquet").merge(
        demanda.estaciones_fisicas(t)[["slug", "pasajeros_est", "lineas", "stop_lat", "stop_lon"]], on="slug")
    _escribir(out / "estaciones.json", cap.to_dict(orient="records"))

    q = equidad.cobertura_por_quintil(eq).reset_index().assign(municipio="Total")
    qm = equidad.cobertura_por_quintil(eq, por="municipio").reset_index()
    _escribir(out / "equidad.json", {
        "por_quintil": pd.concat([q, qm]).astype({"iv_quintil": str}).to_dict(orient="records"),
        "correlacion_spearman_tiempo": equidad.correlaciones(eq).to_dict(),
        "indicadores": {k: v[0] for k, v in equidad.INDICADORES.items()},
    })


if __name__ == "__main__":
    from teleferico.utils import setup_logging

    setup_logging()
    exportar_demanda()
    exportar_accesibilidad()
