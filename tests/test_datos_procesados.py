"""Chequeos de integridad sobre data/processed (correr después del pipeline)."""

import json

import geopandas as gpd
import pandas as pd
import pytest

from teleferico.config import LINEAS, PROCESSED

MT = PROCESSED / "mt"
RED = PROCESSED / "red"
CENSO = PROCESSED / "censo"


def _requiere(path):
    if not path.exists():
        pytest.skip(f"Falta {path}; correr el pipeline primero")


def test_totales_anuales_del_pdf():
    _requiere(MT / "anual_total.parquet")
    anual = pd.read_parquet(MT / "anual_total.parquet").set_index("anio")["pasajeros"]
    assert anual.sum() == 672_798_073
    assert anual[2024] == 78_340_151
    assert anual[2025] == 87_672_207


def test_mensual_cuadra_con_anual():
    _requiere(MT / "mensual.parquet")
    anual = pd.read_parquet(MT / "anual_total.parquet").set_index("anio")["pasajeros"]
    mens = pd.read_parquet(MT / "mensual.parquet")
    por_anio = mens.groupby(mens["mes"].dt.year)["pasajeros"].sum()
    pd.testing.assert_series_equal(por_anio, anual, check_names=False, check_index_type=False)


def test_por_linea_cubre_las_10_lineas():
    _requiere(MT / "anual_por_linea.parquet")
    df = pd.read_parquet(MT / "anual_por_linea.parquet")
    assert set(df["linea"]) == set(LINEAS.values())
    assert df.loc[(df["anio"] == 2024) & (df["linea"] == "Morada"), "pasajeros"].item() == 21_126_549


def test_demanda_estaciones_unida_al_gtfs():
    _requiere(RED / "demanda_estaciones.parquet")
    dem = pd.read_parquet(RED / "demanda_estaciones.parquet")
    est = gpd.read_parquet(RED / "estaciones.parquet")
    assert len(est) == 26
    assert dem.groupby("periodo").size().eq(36).all()
    assert set(dem["slug"]) == set(est["slug"])


def test_censo_poblacion():
    _requiere(CENSO / "manzanos.parquet")
    mz = gpd.read_parquet(CENSO / "manzanos.parquet")
    pob = mz.groupby("municipio")["personas"].sum()
    assert pob["El Alto"] == 885_210
    assert pob["La Paz"] == 750_225
    h3 = gpd.read_parquet(CENSO / "poblacion_h3_r9.parquet")
    assert abs(h3["personas"].sum() - pob.sum()) < 5


def test_red_peatonal_y_pendiente():
    _requiere(RED / "resumen_pendiente.json")
    r = json.loads((RED / "resumen_pendiente.json").read_text(encoding="utf-8"))
    assert r["nodos_sin_elevacion"] == 0
    assert 2900 < r["elevacion_min_m"] < r["elevacion_max_m"] < 4800


ACC = PROCESSED / "accesibilidad"


def test_tobler():
    from teleferico.access import V_PLANA_KMH, tobler_kmh

    assert tobler_kmh(-0.05) == pytest.approx(6.0)
    assert V_PLANA_KMH == pytest.approx(5.04, abs=0.01)
    # Direccional: subir una pendiente fuerte es más lento que bajarla.
    assert tobler_kmh(0.15) < tobler_kmh(-0.15) < V_PLANA_KMH


def test_accesibilidad_manzanos():
    _requiere(ACC / "manzanos_acceso.parquet")
    from teleferico.access import BANDAS_MIN, cobertura

    acc = pd.read_parquet(ACC / "manzanos_acceso.parquet")
    assert acc["codigo"].is_unique
    assert acc["personas"].sum() == 885_210 + 750_225
    cob = cobertura(acc)
    pct = cob[[f"pct_{b}" for b in BANDAS_MIN]].to_numpy()
    assert (pct[:, 1:] >= pct[:, :-1]).all(), "las bandas acumuladas deben ser crecientes"
    # Hipótesis 1: la línea recta sobreestima y la pendiente reduce la cobertura.
    p15 = cob.set_index("escenario")["pct_15"]
    assert p15["pendiente"] < p15["plana"] < p15["euclidiano"]


def test_captacion_estaciones():
    _requiere(ACC / "estaciones_captacion.parquet")
    cap = pd.read_parquet(ACC / "estaciones_captacion.parquet")
    assert len(cap) == 26
    assert (cap["pob_pendiente_20"] >= cap["pob_pendiente_15"]).all()
    assert (cap["pob_pendiente_15"] >= cap["pob_exclusiva_pendiente_15"]).all()


MODELO = PROCESSED / "modelo_demanda"
PROPUESTA = PROCESSED / "propuesta"


def test_modelo_demanda():
    _requiere(MODELO / "comparacion_modelos.parquet")
    comp = pd.read_parquet(MODELO / "comparacion_modelos.parquet").set_index("modelo")
    # Algún modelo con variables debe superar al nulo fuera de muestra.
    assert comp["loo_mae"].min() < comp.loc["Nulo", "loo_mae"]
    var = pd.read_parquet(MODELO / "estaciones_variables.parquet")
    assert len(var) == 26 and var["y"].gt(0).all()


def test_simulacion_nb():
    from teleferico import demand_model as dm

    _requiere(MODELO / "estaciones_variables.parquet")
    df = dm.variables()
    res = dm.ajustar(dm.MODELOS[dm.PRINCIPAL], df)
    sim = dm.simular(res, dm.transformar(pd.DataFrame({"cabecera_interurbana": [0, 1]})), n=4000)
    medias = sim.mean(axis=0)
    # La media simulada se parece a la predicción puntual y la cabecera interurbana capta más.
    assert medias[1] > medias[0]
    assert abs(medias[0] / res.predict(pd.DataFrame({"cabecera_interurbana": [0]})).iat[0] - 1) < 0.15


def test_propuesta():
    _requiere(PROPUESTA / "resumen_propuesta.json")
    r = json.loads((PROPUESTA / "resumen_propuesta.json").read_text(encoding="utf-8"))
    assert r["personas_nuevas_15"] > 0
    assert r["pct_15_despues"] > r["pct_15_antes"]
    curva = pd.read_parquet(PROPUESTA / "curva_mclp.parquet")
    for _, g in curva.groupby(["variante", "umbral"]):
        assert g.sort_values("k")["personas"].is_monotonic_increasing
    est = gpd.read_parquet(PROPUESTA / "estaciones_propuestas.parquet")
    assert len(est) == r["n_estaciones"]
