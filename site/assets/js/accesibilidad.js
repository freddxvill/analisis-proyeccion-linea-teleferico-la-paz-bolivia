/* Página Accesibilidad: mapa de tiempos, hipótesis 1, curvas, zonas, equidad y captación. */
(async function () {
  const ESC = { euclidiano: "Línea recta", plana: "Red sin pendiente", pendiente: "Red con pendiente" };
  const TOK_ESC = { euclidiano: "--ord-1", plana: "--ord-2", pendiente: "--ord-3" };

  // --- Mapa ------------------------------------------------------------------------------
  let variable = "t_pendiente_min";
  const BRECHA = [
    { desde: 0, texto: "< 0,2", tok: "--o-1" }, { desde: 0.2, texto: "0,2-0,4", tok: "--o-2" },
    { desde: 0.4, texto: "0,4-0,6", tok: "--o-3" }, { desde: 0.6, texto: "≥ 0,6", tok: "--o-4" },
  ];
  const colorBrecha = () => ["case", ["==", ["get", "brecha"], null], TF.tok("--grid"),
    ["step", ["get", "brecha"], TF.tok(BRECHA[0].tok), ...BRECHA.slice(1).flatMap((b) => [b.desde, TF.tok(b.tok)])]];
  const color = () => (variable === "brecha" ? colorBrecha() : TF.colorTiempo(variable));
  const leyenda = () => {
    const items = variable === "brecha"
      ? [...BRECHA.map((b) => ({ color: TF.tok(b.tok), texto: b.texto })), { color: TF.tok("--grid"), texto: "sin dato censal" }]
      : TF.BANDAS.map((b) => ({ color: TF.tok(b.tok), texto: b.texto }));
    if (document.getElementById("chk-isocrona").checked) items.push({ color: TF.tok("--ink-1"), texto: "Isócrona 15 min", tipo: "linea" });
    TF.leyendaHTML(document.getElementById("leyenda-acceso"), items);
  };

  async function capas(m) {
    const [hex, iso] = await Promise.all([TF.datos("accesibilidad/hexagonos.geojson"), TF.datos("accesibilidad/isocronas.geojson")]);
    m.addSource("hex", { type: "geojson", data: hex });
    m.addLayer({ id: "hex", type: "fill", source: "hex", paint: { "fill-color": color(), "fill-opacity": 0.72 } });
    m.addSource("iso", { type: "geojson", data: iso });
    m.addLayer({ id: "iso", type: "line", source: "iso",
                 filter: ["all", ["==", ["get", "banda_min"], 15], ["==", ["get", "escenario"], "pendiente"]],
                 layout: { visibility: document.getElementById("chk-isocrona").checked ? "visible" : "none" },
                 paint: { "line-color": TF.tok("--ink-1"), "line-width": 1.5 } });
    await TF.capasRed(m);
    leyenda();
  }

  const fmtMin = (v) => (v >= 60 ? "≥ 60" : TF.num(v));
  function interacciones(m) {
    TF.popup(m, "hex", (p) =>
      `<div class="popup-sec">${TF.escapar(p.zona)} · ${TF.num(p.personas)} personas</div>` +
      `<div><span class="popup-valor">${fmtMin(p.t_pendiente_min)} min</span> con pendiente</div>` +
      `<div class="popup-sec">${fmtMin(p.t_plana_min)} min sin pendiente · ${fmtMin(p.t_euclidiano_min)} min en línea recta</div>` +
      (p.brecha == null || p.brecha === "null" ? "" : `<div class="popup-sec">Vulnerabilidad ${TF.num(p.iv, 2)} · brecha ${TF.num(p.brecha, 2)}</div>`));
    TF.popup(m, "estaciones", (p) => `<div class="popup-valor">${TF.escapar(p.nombre)}</div><div class="popup-sec">${TF.escapar(p.lineas)}</div>`);
    TF.segmentado("sel-variable", (v) => { variable = v; m.setPaintProperty("hex", "fill-color", color()); leyenda(); });
    document.getElementById("chk-isocrona").addEventListener("change", (e) => {
      m.setLayoutProperty("iso", "visibility", e.target.checked ? "visible" : "none");
      leyenda();
    });
  }
  TF.mapa("mapa-acceso", capas, interacciones);
  const [cob, curvas, eq, cap, dem] = await Promise.all([
    TF.datos("accesibilidad/cobertura.json"), TF.datos("accesibilidad/curvas.json"), TF.datos("accesibilidad/equidad.json"),
    TF.datos("accesibilidad/estaciones.json"), TF.datos("demanda/estaciones.json"),
  ]);

  // --- Hipótesis 1: barras agrupadas, rampa ordinal azul (más realista = más oscuro) ----------
  const grupos = ["Total", "La Paz", "El Alto"];
  const pct15 = (g, e) => cob.find((d) => d.grupo === g && d.escenario === e).pct_15;
  TF.grafico("g-h1", () => ({
    legend: TF.leyenda({ data: Object.values(ESC) }),
    grid: { left: 64, right: 56, top: 40, bottom: 28 },
    xAxis: TF.ejeVal((v) => `${v} %`, { max: 80 }),
    yAxis: TF.ejeCat({ data: grupos, inverse: true }),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: TF.tok("--grid"), opacity: 0.4 } },
               formatter: (ps) => `${ps[0].axisValue}<br>` + ps.map((p) => TF.filaTooltip(p.color, p.seriesName, TF.pct(p.value))).join("") },
    series: Object.entries(ESC).map(([e, nombre]) => ({
      ...TF.barra(true), name: nombre, color: TF.tok(TOK_ESC[e]), barGap: "15%",
      data: grupos.map((g) => pct15(g, e)),
      label: { show: true, position: "right", color: TF.tok("--ink-2"), formatter: (p) => TF.pct(p.value) },
    })),
  }), { columnas: ["Grupo", "Método", "≤ 5 min", "≤ 10 min", "≤ 15 min", "≤ 20 min"],
        filas: cob.filter((d) => grupos.includes(d.grupo)).map((d) => [d.grupo, ESC[d.escenario], ...[5, 10, 15, 20].map((b) => TF.pct(d[`pct_${b}`]))]) });

  // --- Curvas acumuladas: small multiples por municipio --------------------------------------
  for (const [id, mun] of [["g-curva-lp", "La Paz"], ["g-curva-ea", "El Alto"]]) {
    TF.grafico(id, () => ({
      title: { text: mun, left: 0, textStyle: { fontSize: 13, color: TF.tok("--ink-1") } },
      legend: TF.leyenda({ top: 22, data: Object.values(ESC) }),
      grid: { left: 48, right: 16, top: 60, bottom: 40 },
      xAxis: TF.ejeVal((v) => v, { min: 0, max: 60, interval: 15, name: "minutos a pie", nameLocation: "middle", nameGap: 26 }),
      yAxis: TF.ejeVal((v) => `${v} %`, { min: 0, max: 100 }),
      tooltip: { trigger: "axis", axisPointer: { type: "line", lineStyle: { color: TF.tok("--axis") } },
                 formatter: (ps) => `≤ ${ps[0].value[0]} min<br>` + ps.map((p) => TF.filaTooltip(p.color, p.seriesName, TF.pct(p.value[1]))).join("") },
      series: Object.entries(ESC).map(([e, nombre]) => ({
        ...TF.linea(), name: nombre, color: TF.tok(TOK_ESC[e]),
        data: curvas.curvas[e][mun].map((v, i) => [curvas.minutos[i], v]),
        markLine: e === "pendiente" ? { silent: true, symbol: "none", lineStyle: { color: TF.tok("--axis"), type: "solid" },
                                        label: { formatter: "15 min", color: TF.tok("--ink-3") }, data: [{ xAxis: 15 }] } : undefined,
      })),
    }), { columnas: ["Minutos", ...Object.values(ESC)],
          filas: [5, 10, 15, 20, 30, 45, 60].map((m) => [m, ...Object.keys(ESC).map((e) => TF.pct(curvas.curvas[e][mun][m]))]) });
  }

  // --- Zonas: sin y con pendiente ----------------------------------------------------------
  const zonas = [...new Set(cob.filter((d) => d.poblacion > 15000 && !["Total", "La Paz"].includes(d.grupo)).map((d) => d.grupo))]
    .filter((g) => cob.some((d) => d.grupo === g && d.escenario === "pendiente"))
    .sort((a, b) => pct15(a, "pendiente") - pct15(b, "pendiente"));
  TF.grafico("g-zonas", () => ({
    legend: TF.leyenda({ data: [ESC.plana, ESC.pendiente] }),
    grid: { left: 96, right: 56, top: 36, bottom: 28 },
    xAxis: TF.ejeVal((v) => `${v} %`, { max: 100 }),
    yAxis: TF.ejeCat({ data: zonas }),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: TF.tok("--grid"), opacity: 0.4 } },
               formatter: (ps) => `${TF.escapar(ps[0].axisValue)}<br>` + ps.map((p) => TF.filaTooltip(p.color, p.seriesName, TF.pct(p.value))).join("") },
    series: ["plana", "pendiente"].map((e) => ({
      ...TF.barra(true), name: ESC[e], color: TF.tok(TOK_ESC[e]), barGap: "15%",
      data: zonas.map((z) => pct15(z, e)),
      label: { show: e === "pendiente", position: "right", color: TF.tok("--ink-2"), formatter: (p) => TF.pct(p.value, 0) },
    })),
  }), { columnas: ["Zona", "Población", "≤ 15 min sin pendiente", "≤ 15 min con pendiente"],
        filas: [...zonas].reverse().map((z) => [z, TF.num(cob.find((d) => d.grupo === z).poblacion), TF.pct(pct15(z, "plana")), TF.pct(pct15(z, "pendiente"))]) });

  // --- Equidad: cobertura por quintil y municipio ---------------------------------------------
  const Q = ["Q1 (menos vulnerable)", "Q2", "Q3", "Q4", "Q5 (más vulnerable)"];
  const q = (mun, quintil) => eq.por_quintil.find((d) => d.municipio === mun && d.iv_quintil === quintil);
  TF.grafico("g-equidad", () => ({
    legend: TF.leyenda({ data: ["El Alto", "La Paz"] }),
    grid: { left: 48, right: 16, top: 40, bottom: 48 },
    xAxis: TF.ejeCat({ data: Q.map((x) => x.replace(" (", "\n(")) }),
    yAxis: TF.ejeVal((v) => `${v} %`, { max: 60 }),
    tooltip: { trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: TF.tok("--grid"), opacity: 0.4 } },
               formatter: (ps) => `${TF.escapar(Q[ps[0].dataIndex])}<br>` + ps.map((p) => TF.filaTooltip(p.color, p.seriesName, TF.pct(p.value))).join("") },
    series: [["El Alto", "--cat-1"], ["La Paz", "--cat-2"]].map(([mun, tok]) => ({
      ...TF.barra(), name: mun, color: TF.tok(tok), barGap: "15%",
      data: Q.map((x) => q(mun, x).pct_cubierta_15min),
      label: { show: true, position: "top", color: TF.tok("--ink-2"), formatter: (p) => TF.num(p.value, 0) },
    })),
  }), { columnas: ["Quintil", "Municipio", "Población", "% a ≤ 15 min", "Tiempo medio (min)"],
        filas: eq.por_quintil.map((d) => [d.iv_quintil, d.municipio, TF.num(d.poblacion), TF.pct(d.pct_cubierta_15min), TF.num(d.t_medio_min, 1)]) });

  // --- Captación frente a demanda: dispersión con eje y logarítmico ---------------------------
  const pas = Object.fromEntries(dem.estaciones_2025.map((d) => [d.slug, d]));
  const puntos = (mun) => cap.filter((d) => d.municipio === mun).map((d) => ({ value: [d.pob_pendiente_15, pas[d.slug].pasajeros_est], nombre: d.nombre }));
  TF.grafico("g-captacion", () => ({
    legend: TF.leyenda({ data: ["El Alto", "La Paz"] }),
    grid: { left: 64, right: 24, top: 40, bottom: 44 },
    xAxis: TF.ejeVal(TF.miles, { name: "Población a ≤ 15 min a pie (con pendiente)", nameLocation: "middle", nameGap: 28 }),
    yAxis: TF.ejeVal((v) => TF.compacto(v), { type: "log", min: 1e5, max: 2e7 }),
    tooltip: { trigger: "item", formatter: (p) => `<b>${TF.escapar(p.data.nombre)}</b><br>${TF.millones(p.value[1])} abordajes · ${TF.miles(p.value[0])} vecinos a pie` },
    series: [["El Alto", "--cat-1"], ["La Paz", "--cat-2"]].map(([mun, tok]) => ({
      type: "scatter", name: mun, color: TF.tok(tok), symbolSize: 11, data: puntos(mun),
      itemStyle: { borderColor: TF.tok("--surface-1"), borderWidth: 2 },
      label: { show: true, position: "right", fontSize: 10, color: TF.tok("--ink-3"),
               formatter: (p) => (p.value[1] > 6e6 ? p.data.nombre : "") },
    })),
  }), { columnas: ["Estación", "Municipio", "Población a ≤ 15 min", "Abordajes 2025"],
        filas: cap.map((d) => [d.nombre, d.municipio, TF.num(d.pob_pendiente_15), TF.num(pas[d.slug].pasajeros_est)]) });
})();
