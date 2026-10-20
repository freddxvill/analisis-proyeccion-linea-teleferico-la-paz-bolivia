/* Página Propuesta: bolsones, MCLP, línea propuesta, impacto, modelo de demanda y contraste. */
(async function () {
  const [kpis, curva, haz, rend, pas, contraste, modelo, lineasDem] = await Promise.all([
    TF.datos("propuesta/kpis.json"), TF.datos("propuesta/curva_mclp.json"), TF.datos("propuesta/lineas_haz.json"),
    TF.datos("propuesta/rendimiento_lineas.json"), TF.datos("propuesta/pasajeros.json"), TF.datos("propuesta/contraste.json"),
    TF.datos("modelo/modelo_demanda.json"), TF.datos("demanda/lineas.json"),
  ]);
  const PRINCIPAL = modelo.modelo_principal;

  // --- Mapa ------------------------------------------------------------------------------
  const k = () => Number(document.getElementById("k-mclp").value);
  const verMclp = () => document.getElementById("chk-mclp").checked;
  const leyenda = () => TF.leyendaHTML(document.getElementById("leyenda-propuesta"), [
    { color: TF.tok("--o-2"), texto: "Zonas sin cobertura" },
    ...(verMclp() ? [{ color: TF.tok("--cat-3"), texto: `MCLP: ${k()} estaciones libres`, tipo: "punto" }] : []),
    { color: TF.tok("--ink-1"), texto: "Línea propuesta", tipo: "linea" },
    { color: TF.tok("--o-4"), texto: "Pampahasi (anunciada)", tipo: "punto" },
  ]);

  async function capas(m) {
    const [bol, mclp, linea, nuevas] = await Promise.all([
      TF.datos("propuesta/bolsones.geojson"), TF.datos("propuesta/mclp_estaciones.geojson"),
      TF.datos("propuesta/linea_propuesta.geojson"), TF.datos("propuesta/estaciones_propuestas.geojson"),
    ]);
    m.addSource("bolsones", { type: "geojson", data: bol });
    m.addLayer({ id: "bolsones", type: "fill", source: "bolsones", paint: { "fill-color": TF.tok("--o-2"), "fill-opacity": 0.45 } });
    await TF.capasRed(m);
    m.addSource("propuesta", { type: "geojson", data: linea });
    m.addLayer({ id: "propuesta", type: "line", source: "propuesta",
                 paint: { "line-color": TF.tok("--ink-1"), "line-width": 3.5, "line-dasharray": [2, 1.2] } });
    m.addSource("nuevas", { type: "geojson", data: nuevas });
    m.addLayer({ id: "nuevas", type: "circle", source: "nuevas",
                 paint: { "circle-radius": 6, "circle-color": TF.tok("--surface-1"), "circle-stroke-color": TF.tok("--ink-1"), "circle-stroke-width": 2.5 } });
    m.addLayer({ id: "nuevas-etiqueta", type: "symbol", source: "nuevas",
                 layout: { "text-field": ["get", "id"], "text-font": ["Noto Sans Regular"], "text-size": 12, "text-offset": [0.9, -0.9], "text-anchor": "left" },
                 paint: { "text-color": TF.tok("--ink-1"), "text-halo-color": TF.tok("--surface-1"), "text-halo-width": 1.5 } });
    m.addSource("mclp", { type: "geojson", data: mclp });
    m.addLayer({ id: "mclp", type: "circle", source: "mclp", filter: ["==", ["get", "k"], k()],
                 layout: { visibility: verMclp() ? "visible" : "none" },
                 paint: { "circle-radius": 7, "circle-color": TF.tok("--cat-3"), "circle-stroke-color": TF.tok("--surface-1"), "circle-stroke-width": 2 } });
    m.addSource("pampahasi", { type: "geojson", data: { type: "Feature", properties: { nombre: "Pampahasi" },
                                                          geometry: { type: "Point", coordinates: [contraste.lon, contraste.lat] } } });
    m.addLayer({ id: "pampahasi", type: "circle", source: "pampahasi",
                 paint: { "circle-radius": 7, "circle-color": TF.tok("--o-4"), "circle-stroke-color": TF.tok("--surface-1"), "circle-stroke-width": 2 } });
    m.addLayer({ id: "pampahasi-etiqueta", type: "symbol", source: "pampahasi",
                 layout: { "text-field": "Pampahasi", "text-font": ["Noto Sans Regular"], "text-size": 12, "text-offset": [0.9, 0], "text-anchor": "left" },
                 paint: { "text-color": TF.tok("--ink-1"), "text-halo-color": TF.tok("--surface-1"), "text-halo-width": 1.5 } });
    leyenda();
  }

  function interacciones(m) {
    TF.popup(m, "bolsones", (p) => `<div><span class="popup-valor">${TF.num(p.personas)}</span> personas no cubiertas</div>` +
      `<div class="popup-sec">hoy a ${p.t_actual >= 60 ? "≥ 60" : TF.num(p.t_actual)} min · persistencia ${TF.num(p.persistencia, 2)}</div>`);
    TF.popup(m, "nuevas", (p) => `<div class="popup-valor">Estación ${TF.escapar(p.id)}</div>` +
      `<div>${TF.miles(p.pob_pendiente_15)} personas a ≤ 15 min</div>`);
    TF.popup(m, "estaciones", (p) => `<div class="popup-valor">${TF.escapar(p.nombre)}</div><div class="popup-sec">${TF.escapar(p.lineas)}</div>`);
    const slider = document.getElementById("k-mclp");
    slider.addEventListener("input", () => {
      document.getElementById("k-valor").textContent = slider.value;
      m.setFilter("mclp", ["==", ["get", "k"], k()]);
      leyenda();
    });
    document.getElementById("chk-mclp").addEventListener("change", () => {
      m.setLayoutProperty("mclp", "visibility", verMclp() ? "visible" : "none");
      leyenda();
    });
  }
  TF.mapa("mapa-propuesta", capas, interacciones, { center: [-68.16, -16.49], zoom: 11.6 });

  // --- Curva MCLP: tres escenarios (categórica, 3 slots validados) ---------------------------
  const ESC = [["pendiente", 15, "Con pendiente, 15 min", "--cat-1"], ["plana", 15, "Sin pendiente, 15 min", "--cat-2"],
               ["pendiente", 10, "Con pendiente, 10 min", "--cat-3"]];
  const ks = [...new Set(curva.map((d) => d.k))];
  const val = (v, u, kk) => curva.find((d) => d.variante === v && d.umbral === u && d.k === kk).personas;
  TF.grafico("g-curva", () => ({
    title: { text: "Población nueva cubierta con k estaciones libres", left: 0, textStyle: { fontSize: 13, color: TF.tok("--ink-1") } },
    legend: TF.leyenda({ top: 22 }),
    grid: { left: 56, right: 64, top: 84, bottom: 40 },
    xAxis: TF.ejeCat({ data: ks, name: "k", nameLocation: "middle", nameGap: 26 }),
    yAxis: TF.ejeVal(TF.miles),
    tooltip: { trigger: "axis", axisPointer: { type: "line", lineStyle: { color: TF.tok("--axis") } },
               formatter: (ps) => `k = ${ps[0].axisValue}<br>` + ps.map((p) => TF.filaTooltip(p.color, p.seriesName, TF.miles(p.value))).join("") },
    series: ESC.map(([v, u, nombre, tok]) => ({
      ...TF.linea(), showSymbol: true, name: nombre, color: TF.tok(tok), data: ks.map((kk) => val(v, u, kk)),
      endLabel: { show: true, color: TF.tok("--ink-2"), formatter: (p) => TF.miles(p.value) },
    })),
  }), { columnas: ["k", ...ESC.map((e) => e[2])], filas: ks.map((kk) => [kk, ...ESC.map(([v, u]) => TF.num(val(v, u, kk)))]) });

  // --- Regla de parada: personas por km que agrega cada estación de la línea ------------------
  const marg = haz.map((d, i) => ({ n: d.n_estaciones,
    v: i === 0 ? d.personas / d.km : (d.personas - haz[i - 1].personas) / (d.km - haz[i - 1].km) }));
  const ref = kpis.referencia_personas_por_km_red;
  TF.grafico("g-parada", () => ({
    title: { text: "Personas nuevas por km que agrega cada estación", left: 0, textStyle: { fontSize: 13, color: TF.tok("--ink-1") } },
    grid: { left: 56, right: 96, top: 40, bottom: 40 },
    xAxis: TF.ejeCat({ data: marg.map((d) => d.n), name: "estación n.º", nameLocation: "middle", nameGap: 26 }),
    yAxis: TF.ejeVal(TF.miles),
    tooltip: { trigger: "item", formatter: (p) => `Estación ${marg[p.dataIndex].n}: <b>${TF.miles(p.value)}</b> personas nuevas por km` },
    series: [{ ...TF.barra(), data: marg.map((d) => ({ value: d.v,
      itemStyle: { color: TF.tok(d.n <= kpis.n_estaciones ? "--cat-1" : "--ink-3"), borderRadius: [4, 4, 0, 0] } })),
      markLine: { silent: true, symbol: "none", lineStyle: { color: TF.tok("--ink-2"), type: "solid", width: 1 },
                  label: { formatter: `red actual:
${TF.miles(ref)}/km`, color: TF.tok("--ink-2"), position: "end" },
                  data: [{ yAxis: ref }] } }],
  }), { columnas: ["Estaciones", "Km", "Personas nuevas", "Personas por km", "Marginal por km"],
        filas: haz.map((d, i) => [d.n_estaciones, TF.num(d.km, 1), TF.num(d.personas), TF.num(d.personas_por_km), TF.num(marg[i].v)]) });

  // --- Rendimiento por km: color oficial de cada línea; la propuesta en tinta ------------------
  const r = [...rend].sort((a, b) => a.personas_por_km - b.personas_por_km);
  const colorL = (l) => (l === "Propuesta" ? TF.tok("--ink-1") : lineasDem.color_marca[l]);
  TF.grafico("g-rendimiento", () => ({
    grid: { left: 84, right: 64, top: 16, bottom: 32 },
    xAxis: TF.ejeVal(TF.miles),
    yAxis: TF.ejeCat({ data: r.map((d) => d.linea), axisLabel: { color: TF.tok("--ink-2"),
      formatter: (v) => (v === "Propuesta" ? "{b|Propuesta}" : v), rich: { b: { fontWeight: "bold", color: TF.tok("--ink-1") } } } }),
    tooltip: { trigger: "item", formatter: (p) => { const d = r[p.dataIndex];
      return `<b>${TF.miles(d.personas_por_km)}</b> por km · ${TF.escapar(d.linea)}<br>${TF.miles(d.personas_15)} personas en ${TF.num(d.km, 1)} km` +
        (d.linea === "Propuesta" ? "<br>(solo población hoy sin acceso)" : ""); } },
    series: [{ ...TF.barra(true), data: r.map((d) => ({ value: d.personas_por_km,
      itemStyle: { color: colorL(d.linea), borderColor: d.linea === "Blanca" ? TF.tok("--ink-2") : "transparent", borderWidth: 1, borderRadius: [0, 4, 4, 0] } })),
      label: { show: true, position: "right", color: TF.tok("--ink-2"), formatter: (p) => TF.miles(p.value) } }],
  }), { columnas: ["Línea", "Km", "Personas a ≤ 15 min", "Personas por km"],
        filas: [...r].reverse().map((d) => [d.linea, TF.num(d.km, 1), TF.num(d.personas_15), TF.num(d.personas_por_km)]) });

  // --- Tablas de impacto y contraste (visibles: son el contenido, no un respaldo) -------------
  const tablaVisible = (id, columnas, filas) => {
    const cont = document.getElementById(id);
    const t = document.createElement("table");
    t.className = "table table-sm";
    const tr = t.createTHead().insertRow();
    columnas.forEach((c) => { const th = document.createElement("th"); th.textContent = c; tr.appendChild(th); });
    const tb = t.createTBody();
    filas.forEach((f) => { const fila = tb.insertRow(); f.forEach((v) => (fila.insertCell().textContent = v)); });
    cont.replaceChildren(t);
  };
  const ic = (x) => `${TF.millones(x.media)} (${TF.millones(x.p05)}-${TF.millones(x.p95)})`;
  const ext = Object.keys(pas).find((k) => k !== PRINCIPAL);
  tablaVisible("tabla-impacto", ["Indicador", "Valor"], [
    ["Estaciones nuevas · km de cable", `${kpis.n_estaciones} · ${TF.num(kpis.km_cable, 1)} km`],
    ["Personas nuevas a ≤ 15 min / ≤ 10 min", `${TF.num(kpis.personas_nuevas_15)} / ${TF.num(kpis.personas_nuevas_10)}`],
    ["…de ellas, vulnerables (Q4-Q5)", TF.num(kpis.personas_nuevas_vulnerables_15)],
    ["Personas nuevas por km", TF.num(kpis.personas_nuevas_por_km)],
    ["Cobertura a ≤ 15 min, total", `${TF.pct(kpis.pct_15_antes)} → ${TF.pct(kpis.pct_15_despues)}`],
    ["Cobertura a ≤ 15 min, El Alto", `12,9 % → ${TF.pct(kpis.pct_15_despues_el_alto)}`],
    ["Abordajes/año, modelo principal (IC 90 %)", ic(pas[PRINCIPAL].total)],
    ["Abordajes/año, modelo extendido (IC 90 %)", ic(pas[ext].total)],
  ]);
  tablaVisible("tabla-contraste", ["", "Línea Café → Pampahasi (anunciada)", "Línea propuesta"], [
    ["Estaciones nuevas", "1", String(kpis.n_estaciones)],
    ["Km de cable", TF.num(contraste.km_cable, 1), TF.num(kpis.km_cable, 1)],
    ["Personas nuevas a ≤ 15 min", TF.num(contraste.personas_nuevas_15), TF.num(kpis.personas_nuevas_15)],
    ["Personas nuevas por km", TF.num(contraste.personas_nuevas_por_km), TF.num(kpis.personas_nuevas_por_km)],
    ["Abordajes/año (modelo extendido, IC 90 %)", ic(contraste.abordajes), ic(pas[ext].total)],
  ]);

  // --- Modelo de demanda --------------------------------------------------------------------
  const comp = [...modelo.comparacion].sort((a, b) => b.loo_mae - a.loo_mae);
  TF.grafico("g-modelos", () => ({
    title: { text: "Error fuera de muestra (LOO) por modelo", left: 0, textStyle: { fontSize: 13, color: TF.tok("--ink-1") } },
    grid: { left: 250, right: 56, top: 36, bottom: 28 },
    xAxis: TF.ejeVal((v) => TF.millones(v, 0), { max: 4e6, interval: 1e6 }),
    yAxis: TF.ejeCat({ data: comp.map((d) => d.modelo), axisLabel: { color: TF.tok("--ink-2"), fontSize: 11 } }),
    tooltip: { trigger: "item", formatter: (p) => { const d = comp[p.dataIndex];
      return `<b>${TF.millones(d.loo_mae, 2)}</b> de error medio · ${TF.escapar(d.modelo)}<br>R² LOO (log): ${TF.num(d.loo_r2_log, 2)}`; } },
    series: [{ ...TF.barra(true), data: comp.map((d) => ({ value: d.loo_mae,
      itemStyle: { color: TF.tok(d.modelo === PRINCIPAL ? "--cat-1" : "--ord-1"), borderRadius: [0, 4, 4, 0] } })),
      label: { show: true, position: "right", color: TF.tok("--ink-2"), formatter: (p) => TF.millones(p.value, 2) } }],
  }), { columnas: ["Modelo", "Error medio LOO", "R² LOO (log)", "AIC"],
        filas: [...comp].reverse().map((d) => [d.modelo, TF.millones(d.loo_mae, 2), TF.num(d.loo_r2_log, 2), TF.num(d.aic, 1)]) });

  const est = modelo.estaciones;
  const serie = (v, nombre, tok) => ({
    type: "scatter", name: nombre, color: TF.tok(tok), symbolSize: 11, itemStyle: { borderColor: TF.tok("--surface-1"), borderWidth: 2 },
    data: est.filter((d) => d.cabecera_interurbana === v).map((d) => ({ value: [d.y, d.pred_loo], nombre: d.nombre })),
  });
  TF.grafico("g-loo", () => ({
    title: { text: "Observado frente a predicción LOO (escala log)", left: 0, textStyle: { fontSize: 13, color: TF.tok("--ink-1") } },
    legend: TF.leyenda({ top: 22, data: ["Cabecera El Alto ↔ La Paz", "Resto"] }),
    grid: { left: 56, right: 24, top: 64, bottom: 44 },
    xAxis: TF.ejeVal(TF.compacto, { type: "log", min: 1e5, max: 3e7, name: "abordajes observados 2025", nameLocation: "middle", nameGap: 26 }),
    yAxis: TF.ejeVal(TF.compacto, { type: "log", min: 1e5, max: 3e7 }),
    tooltip: { trigger: "item", formatter: (p) => p.seriesType === "scatter"
      ? `<b>${TF.escapar(p.data.nombre)}</b><br>observado ${TF.millones(p.value[0], 2)} · predicho ${TF.millones(p.value[1], 2)}` : "" },
    series: [serie(1, "Cabecera El Alto ↔ La Paz", "--cat-1"), serie(0, "Resto", "--cat-2"),
             { type: "line", silent: true, symbol: "none", data: [[1e5, 1e5], [3e7, 3e7]], lineStyle: { color: TF.tok("--axis"), width: 1 } }],
  }), { columnas: ["Estación", "Observado", "Predicción LOO"], filas: est.map((d) => [d.nombre, TF.num(d.y), TF.num(d.pred_loo)]) });
})();
