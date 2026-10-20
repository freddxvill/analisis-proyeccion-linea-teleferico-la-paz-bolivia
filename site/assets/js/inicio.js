/* Inicio: mapa principal de tiempo a pie con la red actual y la línea propuesta. */
(function () {
  const leyenda = () =>
    TF.leyendaHTML(document.getElementById("leyenda-inicio"), [
      ...TF.BANDAS.map((b) => ({ color: TF.tok(b.tok), texto: b.texto })),
      { color: TF.tok("--ink-1"), texto: "Línea propuesta", tipo: "linea" },
    ]);

  async function capas(m) {
    const [hex, linea, nuevas] = await Promise.all([
      TF.datos("accesibilidad/hexagonos.geojson"),
      TF.datos("propuesta/linea_propuesta.geojson"),
      TF.datos("propuesta/estaciones_propuestas.geojson"),
    ]);
    m.addSource("hex", { type: "geojson", data: hex });
    m.addLayer({ id: "hex", type: "fill", source: "hex",
                 paint: { "fill-color": TF.colorTiempo("t_pendiente_min"), "fill-opacity": 0.72 } });
    await TF.capasRed(m);
    m.addSource("propuesta", { type: "geojson", data: linea });
    m.addLayer({ id: "propuesta", type: "line", source: "propuesta",
                 paint: { "line-color": TF.tok("--ink-1"), "line-width": 3, "line-dasharray": [2, 1.2] } });
    m.addSource("nuevas", { type: "geojson", data: nuevas });
    m.addLayer({ id: "nuevas", type: "circle", source: "nuevas",
                 paint: { "circle-radius": 5, "circle-color": TF.tok("--surface-1"),
                          "circle-stroke-color": TF.tok("--ink-1"), "circle-stroke-width": 2 } });
    leyenda();
  }

  function interacciones(m) {
    TF.popup(m, "hex", (p) =>
      `<div class="popup-sec">${TF.escapar(p.zona)}</div>` +
      `<div><span class="popup-valor">${p.t_pendiente_min >= 60 ? "≥ 60" : TF.num(p.t_pendiente_min)} min</span> a pie, con pendiente</div>` +
      `<div class="popup-sec">${TF.num(p.personas)} personas</div>`);
    TF.popup(m, "estaciones", (p) =>
      `<div class="popup-valor">${TF.escapar(p.nombre)}</div><div class="popup-sec">${TF.escapar(p.lineas)}</div>` +
      `<div>${TF.millones(p.pasajeros_est)} abordajes en 2025</div>`);
  }

  document.addEventListener("DOMContentLoaded", () => TF.mapa("mapa-inicio", capas, interacciones));
})();
