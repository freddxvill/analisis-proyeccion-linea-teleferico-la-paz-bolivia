"""Extrae las series de demanda del PDF "Indicadores de Gestión 2014-2025" de Mi Teleférico.

El PDF no trae tablas: son gráficos con etiquetas de datos. Se reconstruyen las
series a partir de la posición de cada etiqueta (eje x -> año/mes, grupo -> línea)
y, en el gráfico por línea, del color de la caja que la contiene.
Cada tabla se valida contra los totales impresos en el propio PDF.
"""

import logging
import re
from pathlib import Path

import pandas as pd
import pdfplumber
from pypdf import PdfReader

from teleferico.config import LINEAS, MT_INDICADORES_URL, PROCESSED, RAW
from teleferico.utils import download

log = logging.getLogger(__name__)

PDF_PATH = RAW / "mt" / "indicadores_2014_2025.pdf"
OUT_DIR = PROCESSED / "mt"

# Índices de página (base 0) y un fragmento del título para verificar que no cambió el PDF.
PAGES = {
    "anual": (4, "VIDAS TRANSPORTADAS"),
    "por_linea": (6, "POR AÑO Y POR LÍNEA"),
    "mensual_2014_2019": (7, "POR MES LA PAZ"),
    "mensual_2020_2025": (8, "POR MES LA PAZ"),
    "ranking_acumulado": (10, "RANKING DE VIDAS TRANSPORTADAS POR ESTACIÓN"),
    "ranking_2025": (11, "RANKING DE VIDAS TRANSPORTADAS POR ESTACIÓN"),
    "diario_1": (14, "PROMEDIO DIARIO"),
    "diario_2": (15, "PROMEDIO DIARIO"),
    "diario_3": (16, "PROMEDIO DIARIO"),
}
TOTAL_ACUMULADO = 672_798_073
TOTAL_2025 = 87_672_207
# Erratas del propio PDF: suma de etiquetas por línea - total anual impreso.
# En 2025 las líneas suman 87.672.307 y el total (y la serie mensual) 87.672.207.
DISCREPANCIAS_POR_LINEA = {2025: 100}

# Color de relleno de las cajas del gráfico por línea (RGB 0-1) -> línea.
COLORES_LINEA = {
    (0.957, 0.894, 0.071): "Amarilla",
    (1.000, 0.392, 0.408): "Roja",
    (0.224, 0.741, 0.400): "Verde",
    (1.000, 0.725, 0.235): "Naranja",
    (0.000, 0.290, 0.678): "Azul",
    (0.220, 0.714, 1.000): "Celeste",
    (0.482, 0.086, 0.643): "Morada",
    (0.686, 0.298, 0.059): "Café",
    (0.451, 0.451, 0.451): "Plateada",
    # La línea Blanca se dibuja como caja blanca con borde negro.
    (1.000, 1.000, 1.000): "Blanca",
    (0.000, 0.000, 0.000): "Blanca",
}
GRUPOS_DIARIO = {
    "ROJA": "Roja", "AMARILLA": "Amarilla", "VERDE": "Verde", "AZUL": "Azul",
    "NARANJA": "Naranja", "BLANCA": "Blanca", "CELESTE": "Celeste",
    "MORADA": "Morada", "CAFÉ": "Café", "PLATEADA": "Plateada",
}
# Erratas de códigos de línea en el PDF.
CODIGOS_ERRATA = {"LAN": "LNA"}

RE_ENTERO = re.compile(r"\d{1,3}(?:\.\d{3})+|\d+")
RE_PCT = re.compile(r"\d+,\d%")
RE_ANIO = re.compile(r"20(1[4-9]|2[0-5])")


def _int(texto: str) -> int:
    return int(texto.replace(".", ""))


def _centro_x(w: dict) -> float:
    return (w["x0"] + w["x1"]) / 2


def _verificar_titulo(page: pdfplumber.page.Page, fragmento: str) -> None:
    texto = page.extract_text() or ""
    if fragmento not in texto:
        raise ValueError(f"Página {page.page_number}: no se encontró el título '{fragmento}'")


def _etiquetas_rotadas(page: pdfplumber.page.Page) -> list[dict]:
    """Etiquetas verticales (de abajo hacia arriba): pdfplumber las devuelve invertidas."""
    out = []
    for w in page.extract_words():
        if w["upright"]:
            continue
        texto = w["text"][::-1]
        if RE_ENTERO.fullmatch(texto):
            out.append({**w, "text": texto})
    return sorted(out, key=lambda w: w["x0"])


def _etiquetas_anios(page: pdfplumber.page.Page, min_top: float) -> dict[int, float]:
    """Etiquetas de año del eje x -> centro horizontal."""
    return {
        int(w["text"]): _centro_x(w)
        for w in page.extract_words()
        if w["upright"] and w["top"] > min_top and RE_ANIO.fullmatch(w["text"])
    }


def anual_total(pdf: pdfplumber.PDF) -> pd.DataFrame:
    page = pdf.pages[PAGES["anual"][0]]
    anios = _etiquetas_anios(page, min_top=600)
    filas = []
    for w in page.extract_words():
        if not (w["upright"] and "." in w["text"] and RE_ENTERO.fullmatch(w["text"])):
            continue
        valor = _int(w["text"])
        if valor == TOTAL_ACUMULADO:
            continue
        anio = min(anios, key=lambda a: abs(anios[a] - _centro_x(w)))
        filas.append({"anio": anio, "pasajeros": valor})
    df = pd.DataFrame(filas).sort_values("anio").reset_index(drop=True)
    assert df["anio"].is_unique and len(df) == 12, df
    assert df["pasajeros"].sum() == TOTAL_ACUMULADO
    return df


def _color_linea(color) -> str | None:
    if not isinstance(color, (tuple, list)) or len(color) != 3:
        return None
    ref = min(COLORES_LINEA, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, color)))
    if sum((a - b) ** 2 for a, b in zip(ref, color)) > 0.01:
        return None
    return COLORES_LINEA[ref]


def anual_por_linea(pdf: pdfplumber.PDF) -> pd.DataFrame:
    page = pdf.pages[PAGES["por_linea"][0]]
    anios = _etiquetas_anios(page, min_top=650)
    rects = [r for r in page.rects if _color_linea(r.get("non_stroking_color"))]
    filas = []
    for w in page.extract_words():
        if not (w["upright"] and "." in w["text"] and RE_ENTERO.fullmatch(w["text"])):
            continue
        cx, cy = _centro_x(w), (w["top"] + w["bottom"]) / 2
        cajas = [r for r in rects if r["x0"] <= cx <= r["x1"] and r["top"] <= cy <= r["bottom"]]
        if not cajas:
            raise ValueError(f"Etiqueta sin caja de color: {w['text']}")
        caja = min(cajas, key=lambda r: r["width"] * r["height"])
        anio = min(anios, key=lambda a: abs(anios[a] - cx))
        filas.append({
            "anio": anio,
            "linea": _color_linea(caja["non_stroking_color"]),
            "pasajeros": _int(w["text"]),
        })
    df = pd.DataFrame(filas).sort_values(["linea", "anio"]).reset_index(drop=True)
    dup = df.duplicated(["anio", "linea"])
    assert not dup.any(), df[dup]
    return df


def mensual(pdf: pdfplumber.PDF) -> pd.DataFrame:
    """Serie mensual: mayo 2014 - diciembre 2025 (las barras están en orden cronológico)."""
    etiquetas = (
        _etiquetas_rotadas(pdf.pages[PAGES["mensual_2014_2019"][0]])
        + _etiquetas_rotadas(pdf.pages[PAGES["mensual_2020_2025"][0]])
    )
    meses = pd.period_range("2014-05", "2025-12", freq="M")
    assert len(etiquetas) == len(meses), (len(etiquetas), len(meses))
    return pd.DataFrame({
        "mes": meses.to_timestamp(),
        "pasajeros": [_int(w["text"]) for w in etiquetas],
    })


def _nombres_estaciones(reader: PdfReader, idx: int) -> list[tuple[str, str]]:
    texto = reader.pages[idx].extract_text()
    codigos = "|".join(list(LINEAS) + list(CODIGOS_ERRATA))
    # La línea de texto con las etiquetas del eje es la que más códigos contiene.
    linea_eje = max(texto.splitlines(), key=lambda s: len(re.findall(codigos, s)))
    pares = re.findall(rf"(.+?)\s+({codigos})(?=\s|[A-Z0-9ÁÉÍÓÚ]|$)", linea_eje)
    return [(nombre.strip(), CODIGOS_ERRATA.get(cod, cod)) for nombre, cod in pares]


def ranking_estaciones(pdf: pdfplumber.PDF, reader: PdfReader, clave: str, total: int) -> pd.DataFrame:
    idx = PAGES[clave][0]
    page = pdf.pages[idx]
    pcts = sorted(
        (w for w in page.extract_words() if RE_PCT.fullmatch(w["text"])),
        key=lambda w: w["x0"],
    )
    nombres = _nombres_estaciones(reader, idx)
    assert len(pcts) == len(nombres), (len(pcts), len(nombres))
    df = pd.DataFrame({
        "rank": range(1, len(nombres) + 1),
        "estacion": [n for n, _ in nombres],
        "codigo_linea": [c for _, c in nombres],
        "pct": [float(w["text"].rstrip("%").replace(",", ".")) for w in pcts],
    })
    df["linea"] = df["codigo_linea"].map(LINEAS)
    # El PDF solo publica porcentajes con un decimal: el absoluto es una estimación (±0,05 pp).
    df["pasajeros_est"] = (df["pct"] / 100 * total).round().astype(int)
    assert abs(df["pct"].sum() - 100) < 1.5, df["pct"].sum()
    assert df["pct"].is_monotonic_decreasing
    return df


def promedio_diario(pdf: pdfplumber.PDF) -> pd.DataFrame:
    filas = []
    for clave in ("diario_1", "diario_2", "diario_3"):
        page = pdf.pages[PAGES[clave][0]]
        grupos = {
            GRUPOS_DIARIO[w["text"]]: _centro_x(w)
            for w in page.extract_words()
            if w["upright"] and w["top"] > 600 and w["text"] in GRUPOS_DIARIO
        }
        por_grupo: dict[str, list[int]] = {g: [] for g in grupos}
        for w in _etiquetas_rotadas(page):
            g = min(grupos, key=lambda g: abs(grupos[g] - _centro_x(w)))
            por_grupo[g].append(_int(w["text"]))
        # Las barras de cada grupo terminan en 2025 y son años consecutivos.
        for linea, valores in por_grupo.items():
            for anio, v in zip(range(2026 - len(valores), 2026), valores):
                filas.append({"anio": anio, "linea": linea, "promedio_diario": v})
    return pd.DataFrame(filas).sort_values(["linea", "anio"]).reset_index(drop=True)


def validar(t: dict[str, pd.DataFrame]) -> None:
    anual = t["anual_total"].set_index("anio")["pasajeros"]

    # 1. La suma por línea cuadra con el total anual (2015-2025), salvo erratas conocidas.
    por_linea = t["anual_por_linea"].groupby("anio")["pasajeros"].sum()
    diff = por_linea - anual.loc[por_linea.index]
    esperado = pd.Series(DISCREPANCIAS_POR_LINEA).reindex(diff.index, fill_value=0)
    assert (diff == esperado).all(), f"Suma por línea != total anual:\n{diff[diff != 0]}"
    for anio, d in DISCREPANCIAS_POR_LINEA.items():
        log.warning("%d: la suma por línea excede al total impreso en %d (errata del PDF)", anio, d)

    # 2. La suma mensual cuadra con el total anual.
    mens = t["mensual"].groupby(t["mensual"]["mes"].dt.year)["pasajeros"].sum()
    diff = (mens - anual).abs()
    assert (diff == 0).all(), f"Suma mensual != total anual:\n{diff[diff > 0]}"

    # 3. Los años con promedio diario coinciden con los años con datos por línea.
    a = t["anual_por_linea"].groupby("linea")["anio"].min()
    b = t["promedio_diario"].query("anio >= 2015").groupby("linea")["anio"].min()
    assert (a == b.loc[a.index]).all(), pd.concat([a, b], axis=1)
    log.info("Validaciones del PDF OK")


def extraer(pdf_path: Path = PDF_PATH) -> dict[str, pd.DataFrame]:
    with pdfplumber.open(pdf_path) as pdf:
        for idx, fragmento in PAGES.values():
            _verificar_titulo(pdf.pages[idx], fragmento)
        reader = PdfReader(pdf_path)
        tablas = {
            "anual_total": anual_total(pdf),
            "anual_por_linea": anual_por_linea(pdf),
            "mensual": mensual(pdf),
            "ranking_estaciones_acumulado": ranking_estaciones(
                pdf, reader, "ranking_acumulado", TOTAL_ACUMULADO
            ),
            "ranking_estaciones_2025": ranking_estaciones(pdf, reader, "ranking_2025", TOTAL_2025),
            "promedio_diario": promedio_diario(pdf),
        }
    validar(tablas)
    return tablas


def run(overwrite: bool = False) -> dict[str, pd.DataFrame]:
    download(MT_INDICADORES_URL, PDF_PATH, overwrite=overwrite)
    tablas = extraer(PDF_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for nombre, df in tablas.items():
        df.to_parquet(OUT_DIR / f"{nombre}.parquet", index=False)
        df.to_csv(OUT_DIR / f"{nombre}.csv", index=False)
        log.info("%s: %d filas", nombre, len(df))
    return tablas
