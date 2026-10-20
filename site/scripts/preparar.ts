// Prepara el proyecto Quarto antes de renderizar:
// - copia los notebooks del repo (../notebooks) a site/notebooks, para renderizarlos con sus
//   resultados guardados (Quarto no ejecuta los .ipynb por defecto);
// - copia el diagrama Mermaid (../docs/diagrama.mmd, fuente única) en orientación vertical y le
//   agrega los enlaces de cada paso a su página, que solo tienen sentido en el sitio.
// Uso: `quarto run scripts/preparar.ts` desde site/ (también corre como pre-render).

const raiz = new URL("../../", import.meta.url);
const sitio = new URL("../", import.meta.url);

await Deno.mkdir(new URL("notebooks/", sitio), { recursive: true });
for await (const f of Deno.readDir(new URL("notebooks/", raiz))) {
  if (f.isFile && f.name.endsWith(".ipynb")) {
    await Deno.copyFile(new URL(`notebooks/${f.name}`, raiz), new URL(`notebooks/${f.name}`, sitio));
  }
}

const enlaces: Record<string, string> = {
  A1: "demanda.html",
  A2: "accesibilidad.html",
  A3: "accesibilidad.html#equidad",
  M0: "propuesta.html",
  M1: "propuesta.html#modelo-de-demanda",
  M2: "propuesta.html",
  M3: "propuesta.html",
  T2: "notebooks/02_red_peatonal_pendiente.html",
  E2: "notebooks.html",
};
// En el sitio va vertical: en horizontal el flujo es tan ancho que el texto queda ilegible.
const mmd = (await Deno.readTextFile(new URL("docs/diagrama.mmd", raiz))).replace(/^flowchart LR/m, "flowchart TB");
const clicks = Object.entries(enlaces).map(([nodo, url]) => `    click ${nodo} "${url}"`).join("\n");
await Deno.writeTextFile(new URL("assets/diagrama.mmd", sitio), `${mmd.trimEnd()}\n\n${clicks}\n`);
