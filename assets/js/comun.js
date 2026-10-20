/* Utilidades compartidas por las páginas del sitio:
   - tokens de color por rol (leídos de site.css, cambian con el modo claro/oscuro),
   - formato numérico en español,
   - carga de datos JSON,
   - gráficos ECharts que se repintan al cambiar de tema, con vista de tabla,
   - mapas MapLibre (mapa base OpenFreeMap) con la red actual del teleférico. */
(function () {
  const TF = (window.TF = {});

  // --- Datos ---------------------------------------------------------------------------
  const base = document.querySelector('meta[name="quarto:offset"]')?.content || "./";
  const cache = {};
  TF.datos = (ruta) =>
    (cache[ruta] ??= fetch(`${base}data/${ruta}`).then((r) => {
      if (!r.ok) throw new Error(`No se pudo cargar ${ruta}`);
      return r.json();
    }));

  // --- Formato (punto de miles, coma decimal) ---------------------------------------------
  TF.num = (x, d = 0) =>
    Number(x)
      .toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })
      .replace(/,/g, "_").replace(".", ",").replace(/_/g, ".");
  TF.pct = (x, d = 1) => `${TF.num(x, d)} %`;
  TF.miles = (x) => `${TF.num(x / 1e3, Math.abs(x) < 1e4 ? 1 : 0)} mil`;
  TF.millones = (x, d = 1) => `${TF.num(x / 1e6, d)} M`;
  TF.compacto = (x) => (Math.abs(x) >= 1e6 ? TF.millones(x, x >= 1e7 ? 0 : 1) : Math.abs(x) >= 1e3 ? TF.miles(x) : TF.num(x));
  const FORMATOS = {
    pct: (x) => TF.pct(x), pct0: (x) => TF.pct(x, 0), miles: TF.miles, millones: (x) => TF.millones(x),
    num: (x) => TF.num(x), km: (x) => `${TF.num(x, 1)} km`, min: (x) => `${TF.num(x, 0)} min`,
  };

  // --- Tema ------------------------------------------------------------------------------
  TF.oscuro = () => document.body.classList.contains("quarto-dark");
  TF.tok = (nombre) => getComputedStyle(document.body).getPropertyValue(nombre).trim();
  const alCambiarTema = [];
  TF.alCambiarTema = (f) => alCambiarTema.push(f);
  // Los scripts van al final del <body>: el tema inicial ya está aplicado y se registra ahora, para
  // que otros cambios de clase del body durante la carga no se tomen como cambio de tema.
  let temaPrevio = TF.oscuro();
  new MutationObserver(() => {
    const t = TF.oscuro();
    if (t !== temaPrevio) {
      temaPrevio = t;
      alCambiarTema.forEach((f) => f());
    }
  }).observe(document.body, { attributes: true, attributeFilter: ["class"] });

  // --- Cifras (stat tiles): <span data-fuente="x.json" data-campo="a.b" data-fmt="pct"> -------
  TF.llenarCifras = async () => {
    for (const el of document.querySelectorAll("[data-campo]")) {
      const d = await TF.datos(el.dataset.fuente);
      const v = el.dataset.campo.split(".").reduce((o, k) => o?.[k], d);
      el.textContent = v == null ? "—" : (FORMATOS[el.dataset.fmt] || String)(v);
    }
  };

  // --- Gráficos ECharts --------------------------------------------------------------------
  const FUENTE = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
  TF.ejeCat = (extra = {}) => ({
    type: "category",
    axisLine: { lineStyle: { color: TF.tok("--axis") } },
    axisTick: { show: false },
    axisLabel: { color: TF.tok("--ink-3"), fontFamily: FUENTE },
    ...extra,
  });
  TF.ejeVal = (fmt = TF.compacto, extra = {}) => ({
    type: "value",
    splitLine: { lineStyle: { color: TF.tok("--grid"), width: 1 } },
    axisLine: { show: false },
    axisLabel: { color: TF.tok("--ink-3"), fontFamily: FUENTE, formatter: fmt },
    nameTextStyle: { color: TF.tok("--ink-3"), fontFamily: FUENTE },
    ...extra,
  });
  TF.leyenda = (extra = {}) => ({
    top: 0, left: 0, icon: "roundRect", itemWidth: 14, itemHeight: 10,
    textStyle: { color: TF.tok("--ink-2"), fontFamily: FUENTE }, ...extra,
  });
  // Barra: data-end redondeado (4 px), base recta, grosor máximo 24 px.
  TF.barra = (horizontal = false) => ({
    type: "bar", barMaxWidth: 24,
    itemStyle: { borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0] },
    emphasis: { focus: "none", itemStyle: { opacity: 0.85 } },
  });
  TF.linea = () => ({ type: "line", symbol: "circle", symbolSize: 8, showSymbol: false, lineStyle: { width: 2 },
                      itemStyle: { borderColor: TF.tok("--surface-1"), borderWidth: 2 } });

  const tooltipBase = () => ({
    backgroundColor: TF.tok("--surface-1"),
    borderColor: TF.tok("--ring"),
    borderWidth: 1,
    textStyle: { color: TF.tok("--ink-1"), fontFamily: FUENTE, fontSize: 12 },
    extraCssText: "box-shadow: 0 2px 10px rgba(0,0,0,.15); border-radius: 8px;",
    confine: true,
  });

  /** Fila de tooltip: valor fuerte primero, nombre después, con una línea corta del color de la serie. */
  TF.filaTooltip = (color, nombre, valor) =>
    `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">` +
    `<span style="display:inline-block;width:12px;height:2px;background:${color}"></span>` +
    `<b>${TF.escapar(valor)}</b><span style="color:${TF.tok("--ink-2")}">${TF.escapar(nombre)}</span></div>`;
  TF.escapar = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /**
   * Crea un gráfico en #id. `opciones()` se vuelve a llamar al cambiar de tema, para que tome
   * los tokens del modo activo. `tabla` (opcional) = {columnas, filas} para la vista accesible.
   */
  TF.grafico = (id, opciones, tabla) => {
    const el = document.getElementById(id);
    const ch = echarts.init(el, null, { renderer: "svg" });
    const pintar = () =>
      ch.setOption({
        animationDuration: 400,
        textStyle: { fontFamily: FUENTE, color: TF.tok("--ink-2") },
        tooltip: tooltipBase(),
        ...opciones(),
      }, true);
    pintar();
    TF.alCambiarTema(pintar);
    new ResizeObserver(() => ch.resize()).observe(el);
    if (tabla) TF.tabla(el, tabla);
    return ch;
  };

  /** Vista de tabla bajo un gráfico o mapa (con textContent: los nombres vienen de datos). */
  TF.tabla = (el, { columnas, filas, titulo = "Ver los datos en tabla" }) => {
    const det = document.createElement("details");
    det.className = "vista-tabla";
    const sum = document.createElement("summary");
    sum.textContent = titulo;
    const cont = document.createElement("div");
    cont.className = "tabla-scroll";
    const t = document.createElement("table");
    const tr = t.createTHead().insertRow();
    columnas.forEach((c) => { const th = document.createElement("th"); th.textContent = c; tr.appendChild(th); });
    const tb = t.createTBody();
    filas.forEach((f) => { const r = tb.insertRow(); f.forEach((v) => (r.insertCell().textContent = v)); });
    cont.appendChild(t);
    det.append(sum, cont);
    el.after(det);
  };

  // --- Mapas MapLibre ----------------------------------------------------------------------
  TF.estiloMapa = () => `https://tiles.openfreemap.org/styles/${TF.oscuro() ? "dark" : "positron"}`;
  TF.CENTRO = [-68.155, -16.505];

  /**
   * Mapa en #id. `capas(m)` agrega fuentes y capas (se vuelve a llamar si cambia el estilo base
   * por el tema); `interacciones(m)` registra eventos una sola vez.
   */
  TF.mapa = (id, capas, interacciones, opciones = {}) => {
    const m = new maplibregl.Map({
      container: id, style: TF.estiloMapa(), center: TF.CENTRO, zoom: 11.3, minZoom: 9.5, maxZoom: 16,
      cooperativeGestures: true,
      attributionControl: { compact: true, customAttribution: "Censo 2024 (INE) · GTFS Mi Teleférico" },
      ...opciones,
    });
    // Agregar fuentes y capas es idempotente: si un cambio de estilo pisa una carga en curso, la
    // segunda pasada no falla por "ya existe".
    const agregarFuente = m.addSource.bind(m);
    const agregarCapa = m.addLayer.bind(m);
    m.addSource = (id, fuente) => (m.getSource(id) ? m : agregarFuente(id, fuente));
    m.addLayer = (capa, antes) => (m.getLayer(capa.id) ? m : agregarCapa(capa, antes));
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    m.on("style.load", () => capas(m));
    m.once("load", () => interacciones?.(m));
    // diff: false fuerza "style.load", que vuelve a agregar las capas propias sobre el nuevo mapa base.
    TF.alCambiarTema(() => m.setStyle(TF.estiloMapa(), { diff: false }));
    // El contenedor puede cambiar de tamaño después de crear el mapa (fuentes, TOC, giro de pantalla).
    new ResizeObserver(() => m.resize()).observe(m.getContainer());
    return m;
  };

  /** Líneas actuales (color oficial) y estaciones. */
  TF.capasRed = async (m) => {
    const [lineas, est] = await Promise.all([TF.datos("red/lineas.geojson"), TF.datos("red/estaciones.geojson")]);
    m.addSource("lineas", { type: "geojson", data: lineas });
    m.addSource("estaciones", { type: "geojson", data: est });
    // Borde bajo cada línea: separa del fondo los colores oficiales oscuros (Azul, Morada) en modo oscuro.
    m.addLayer({ id: "lineas-borde", type: "line", source: "lineas", layout: { "line-cap": "round" },
                 paint: { "line-color": TF.oscuro() ? TF.tok("--ink-2") : TF.tok("--surface-1"), "line-width": 5.5, "line-opacity": 0.75 } });
    m.addLayer({ id: "lineas", type: "line", source: "lineas",
                 paint: { "line-color": ["get", "color"], "line-width": 3 }, layout: { "line-cap": "round" } });
    m.addLayer({ id: "estaciones", type: "circle", source: "estaciones",
                 paint: { "circle-radius": 4.5, "circle-color": TF.tok("--surface-1"),
                          "circle-stroke-color": TF.tok("--ink-1"), "circle-stroke-width": 1.5 } });
  };

  /** Popup que sigue al puntero sobre una capa; `html(props)` arma el contenido (con TF.escapar). */
  TF.popup = (m, capa, html) => {
    const p = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: "260px" });
    m.on("mousemove", capa, (e) => {
      m.getCanvas().style.cursor = "pointer";
      p.setLngLat(e.lngLat).setHTML(html(e.features[0].properties)).addTo(m);
    });
    m.on("mouseleave", capa, () => { m.getCanvas().style.cursor = ""; p.remove(); });
  };

  /** Leyenda HTML: items = [{color, texto, tipo: "caja" | "linea" | "punto"}]. */
  TF.leyendaHTML = (el, items) => {
    el.replaceChildren(...items.map(({ color, texto, tipo = "caja" }) => {
      const s = document.createElement("span");
      const i = document.createElement("i");
      if (tipo !== "caja") i.className = tipo;
      i.style.background = color;
      s.append(i, document.createTextNode(texto));
      return s;
    }));
  };

  /** Botones segmentados: <div class="segmentado" id=...> con <button data-valor>. */
  TF.segmentado = (id, alCambiar) => {
    const cont = document.getElementById(id);
    cont.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      cont.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      alCambiar(b.dataset.valor);
    });
  };

  // Clases del tiempo a pie (min) compartidas por mapas y leyendas.
  TF.BANDAS = [
    { hasta: 5, texto: "≤ 5 min", tok: "--t-1" }, { hasta: 10, texto: "5-10", tok: "--t-2" },
    { hasta: 15, texto: "10-15", tok: "--t-3" }, { hasta: 30, texto: "15-30", tok: "--t-4" },
    { hasta: 60, texto: "30-60", tok: "--t-5" }, { hasta: Infinity, texto: "≥ 60 min", tok: "--t-6" },
  ];
  TF.colorTiempo = (campo) => {
    const e = ["step", ["get", campo], TF.tok(TF.BANDAS[0].tok)];
    TF.BANDAS.slice(0, -2).forEach((b, i) => e.push(b.hasta + 1e-6, TF.tok(TF.BANDAS[i + 1].tok)));
    e.push(59.99, TF.tok(TF.BANDAS[5].tok)); // los tiempos ≥ 60 vienen recortados a 60
    return e;
  };

  document.addEventListener("DOMContentLoaded", () => TF.llenarCifras());
})();
