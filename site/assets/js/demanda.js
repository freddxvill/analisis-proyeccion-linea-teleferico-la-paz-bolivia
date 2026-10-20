/* Página Demanda: series del PDF de indicadores de Mi Teleférico. */
(async function () {
  const [anual, mensual, estac, lineas, estaciones] = await Promise.all([
    TF.datos("demanda/anual.json"), TF.datos("demanda/mensual.json"), TF.datos("demanda/estacionalidad.json"),
    TF.datos("demanda/lineas.json"), TF.datos("demanda/estaciones.json"),
  ]);
  const ANOTADOS = new Set([2019, 2020, 2025]);

  // --- Anual: una serie, 2020 en gris (emphasis), etiquetas solo en los años que cuentan la historia.
  TF.grafico("g-anual", () => ({
    grid: { left: 56, right: 16, top: 24, bottom: 32 },
    xAxis: TF.ejeCat({ data: anual.map((d) => d.anio) }),
    yAxis: TF.ejeVal((v) => TF.millones(v, 0)),
    tooltip: { trigger: "item", formatter: (p) => {
      const d = anual[p.dataIndex];
      return `<b>${TF.millones(d.pasajeros)}</b> pasajeros en ${d.anio}` +
        (d.var_pct == null ? "" : `<br><span style="color:${TF.tok("--ink-2")}">${d.var_pct > 0 ? "+" : ""}${TF.pct(d.var_pct)} interanual</span>`);
    } },
    series: [{
      ...TF.barra(),
      data: anual.map((d) => ({
        value: d.pasajeros,
        itemStyle: { color: TF.tok(d.anio === 2020 ? "--ink-3" : "--cat-1"), borderRadius: [4, 4, 0, 0] },
        label: { show: ANOTADOS.has(d.anio), position: "top", color: TF.tok("--ink-2"), formatter: () => TF.millones(d.pasajeros) },
      })),
    }],
  }), { columnas: ["Año", "Pasajeros", "Variación", "Promedio diario"],
        filas: anual.map((d) => [d.anio, TF.num(d.pasajeros), d.var_pct == null ? "—" : TF.pct(d.var_pct), TF.num(d.promedio_diario)]) });

  // --- Mensual: línea con crosshair; la cuarentena como banda.
  TF.grafico("g-mensual", () => ({
    grid: { left: 56, right: 16, top: 24, bottom: 32 },
    xAxis: TF.ejeCat({ data: mensual.map((d) => d.mes), boundaryGap: false,
                       axisLabel: { color: TF.tok("--ink-3"), interval: (i, v) => v.endsWith("-01"), formatter: (v) => v.slice(0, 4) } }),
    yAxis: TF.ejeVal((v) => TF.millones(v, 0)),
    tooltip: { trigger: "axis", axisPointer: { type: "line", lineStyle: { color: TF.tok("--axis") } },
               formatter: (ps) => `${ps[0].axisValue}<br>` + TF.filaTooltip(TF.tok("--cat-1"), "pasajeros", TF.millones(ps[0].value, 2)) },
    series: [{
      ...TF.linea(), data: mensual.map((d) => d.pasajeros), color: TF.tok("--cat-1"),
      markArea: { silent: true, itemStyle: { color: TF.tok("--grid") },
                  label: { color: TF.tok("--ink-2"), position: "insideTop", fontSize: 11 },
                  data: [[{ name: "Cuarentena", xAxis: "2020-03" }, { xAxis: "2020-06" }]] },
    }],
  }), { columnas: ["Mes", "Pasajeros"], filas: mensual.map((d) => [d.mes, TF.num(d.pasajeros)]) });

  // --- Estacionalidad: mapa de calor mes × año, secuencial azul de un matiz.
  const valores = estac.celdas.map((c) => c[2]);
  TF.grafico("g-estacionalidad", () => ({
    grid: { left: 48, right: 16, top: 16, bottom: 64 },
    xAxis: TF.ejeCat({ data: estac.meses, splitArea: { show: false } }),
    yAxis: TF.ejeCat({ data: estac.anios, inverse: true, axisLine: { show: false } }),
    visualMap: { min: 0, max: Math.max(...valores), orient: "horizontal", left: "center", bottom: 4, itemHeight: 220,
                 calculable: false, inRange: { color: [TF.tok("--seq-bajo"), TF.tok("--seq-alto")] },
                 textStyle: { color: TF.tok("--ink-3") }, formatter: (v) => TF.millones(v, 0) },
    tooltip: { trigger: "item", formatter: (p) => `<b>${TF.millones(p.value[2], 2)}</b> pasajeros<br>${estac.meses[p.value[0]]} ${estac.anios[p.value[1]]}` },
    series: [{ type: "heatmap", data: estac.celdas, itemStyle: { borderColor: TF.tok("--surface-1"), borderWidth: 2 } }],
  }), { columnas: ["Mes", "Índice estacional (1 = mes típico, 2022-2025)"],
        filas: estac.meses.map((m, i) => [m, TF.num(estac.indice_estacional[i], 2)]) });

  // --- Líneas: color oficial (identidad), ordenadas por pasajeros.
  const res = [...lineas.resumen_2025].sort((a, b) => a.pasajeros - b.pasajeros);
  const colorLinea = (l) => lineas.color_marca[l];
  const bordeLinea = (l) => (l === "Blanca" ? TF.tok("--ink-2") : "transparent");
  TF.grafico("g-lineas", () => ({
    title: { text: "Pasajeros 2025 por línea", left: 0, textStyle: { fontSize: 13, color: TF.tok("--ink-1") } },
    grid: { left: 70, right: 96, top: 36, bottom: 24 },
    xAxis: TF.ejeVal((v) => TF.millones(v, 0)),
    yAxis: TF.ejeCat({ data: res.map((d) => d.linea) }),
    tooltip: { trigger: "item", formatter: (p) => { const d = res[p.dataIndex];
      return `<b>${TF.millones(d.pasajeros)}</b> · ${TF.escapar(d.linea)}<br>${TF.pct(d.participacion_pct)} de los pasajeros con el ${TF.pct(d.km_pct)} de los km`; } },
    series: [{ ...TF.barra(true), data: res.map((d) => ({ value: d.pasajeros,
      itemStyle: { color: colorLinea(d.linea), borderColor: bordeLinea(d.linea), borderWidth: 1, borderRadius: [0, 4, 4, 0] } })),
      label: { show: true, position: "right", color: TF.tok("--ink-2"), formatter: (p) => `${TF.pct(res[p.dataIndex].participacion_pct, 0)} · ${TF.pct(res[p.dataIndex].km_pct, 0)} km` } }],
  }), { columnas: ["Línea", "Pasajeros 2025", "% pasajeros", "Km", "% km", "Pasajeros por km"],
        filas: [...res].reverse().map((d) => [d.linea, TF.num(d.pasajeros), TF.pct(d.participacion_pct), TF.num(d.km, 1), TF.pct(d.km_pct), TF.num(d.pasajeros_por_km)]) });

  const idx = Object.entries(lineas.indice_2019).map(([l, v]) => ({ linea: l, valor: v[v.length - 1] })).sort((a, b) => a.valor - b.valor);
  TF.grafico("g-recuperacion", () => ({
    title: { text: "Pasajeros 2025 como % de 2019", left: 0, textStyle: { fontSize: 13, color: TF.tok("--ink-1") } },
    grid: { left: 70, right: 48, top: 36, bottom: 24 },
    xAxis: TF.ejeVal((v) => `${v}`, { max: 160 }),
    yAxis: TF.ejeCat({ data: idx.map((d) => d.linea) }),
    tooltip: { trigger: "item", formatter: (p) => `<b>${TF.pct(idx[p.dataIndex].valor, 0)}</b> de 2019 · ${TF.escapar(idx[p.dataIndex].linea)}` },
    series: [{ ...TF.barra(true), data: idx.map((d) => ({ value: d.valor,
      itemStyle: { color: colorLinea(d.linea), borderColor: bordeLinea(d.linea), borderWidth: 1, borderRadius: [0, 4, 4, 0] } })),
      label: { show: true, position: "right", color: TF.tok("--ink-2"), formatter: (p) => TF.num(p.value) },
      markLine: { silent: true, symbol: "none", lineStyle: { color: TF.tok("--ink-2"), type: "solid", width: 1 },
                  label: { formatter: "2019 = 100", color: TF.tok("--ink-2") }, data: [{ xAxis: 100 }] } }],
  }), { columnas: ["Línea", "2025 como % de 2019"], filas: [...idx].reverse().map((d) => [d.linea, TF.pct(d.valor, 0)]) });

  // --- Estaciones: color por municipio (2 series categóricas) con leyenda.
  const est = [...estaciones.estaciones_2025].sort((a, b) => a.pasajeros_est - b.pasajeros_est);
  const serieMun = (mun, tok) => ({
    ...TF.barra(true), name: mun, stack: "m", color: TF.tok(tok),
    data: est.map((d) => (d.municipio === mun ? d.pasajeros_est : null)),
  });
  TF.grafico("g-estaciones", () => ({
    legend: TF.leyenda({ data: ["El Alto", "La Paz"] }),
    grid: { left: 150, right: 56, top: 32, bottom: 24 },
    xAxis: TF.ejeVal((v) => TF.millones(v, 0)),
    yAxis: TF.ejeCat({ data: est.map((d) => d.nombre), axisLabel: { color: TF.tok("--ink-2"), fontSize: 11 } }),
    tooltip: { trigger: "item", formatter: (p) => { const d = est[p.dataIndex];
      return `<b>${TF.millones(d.pasajeros_est)}</b> · ${TF.escapar(d.nombre)}<br>${TF.escapar(d.lineas)} · ${TF.pct(d.pct)} del total`; } },
    series: [serieMun("El Alto", "--cat-1"), serieMun("La Paz", "--cat-2")],
  }), { columnas: ["Estación", "Municipio", "Líneas", "Abordajes 2025 (estim.)", "% del total"],
        filas: [...est].reverse().map((d) => [d.nombre, d.municipio, d.lineas, TF.num(d.pasajeros_est), TF.pct(d.pct)]) });

  const conc = estaciones.concentracion;
  TF.grafico("g-concentracion", () => ({
    title: { text: "Curva de concentración: % de abordajes acumulado", left: 0, textStyle: { fontSize: 13, color: TF.tok("--ink-1") } },
    grid: { left: 48, right: 24, top: 36, bottom: 40 },
    xAxis: TF.ejeVal((v) => `${v} %`, { min: 0, max: 100, name: "% de estaciones (de mayor a menor)", nameLocation: "middle", nameGap: 26 }),
    yAxis: TF.ejeVal((v) => `${v} %`, { min: 0, max: 100 }),
    tooltip: { trigger: "axis", axisPointer: { type: "line", lineStyle: { color: TF.tok("--axis") } },
               formatter: (ps) => { const p = ps.find((x) => x.seriesIndex === 0); return p ? `${TF.pct(p.value[0], 0)} de las estaciones<br><b>${TF.pct(p.value[1], 0)}</b> de los abordajes` : ""; } },
    series: [
      { ...TF.linea(), showSymbol: true, color: TF.tok("--cat-1"), data: [[0, 0], ...conc.map((d) => [d.pct_estaciones, d.pct_demanda])] },
      { type: "line", silent: true, symbol: "none", data: [[0, 0], [100, 100]], lineStyle: { color: TF.tok("--axis"), width: 1 } },
    ],
  }), { columnas: ["% de estaciones", "% de abordajes"], filas: conc.map((d) => [TF.pct(d.pct_estaciones), TF.pct(d.pct_demanda)]) });
})();
