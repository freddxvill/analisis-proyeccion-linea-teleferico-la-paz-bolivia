"""Pipeline reproducible: `uv run python -m teleferico.pipeline [--pasos ...] [--overwrite]`."""

import argparse
import logging
import time

from teleferico import access
from teleferico.ingest import censo, dem, gtfs, limites, mt_pdf, osm
from teleferico.utils import setup_logging

log = logging.getLogger("teleferico.pipeline")

# El orden importa: gtfs usa las tablas del PDF; osm y dem usan el área de estudio del censo;
# acceso usa la red con pendiente, las estaciones, los manzanos y los límites.
PASOS = {
    "mt_pdf": mt_pdf.run,
    "gtfs": gtfs.run,
    "censo": censo.run,
    "osm": osm.run,
    "dem": dem.run,
    "limites": limites.run,
    "acceso": access.run,
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pasos", nargs="+", choices=list(PASOS), default=list(PASOS))
    parser.add_argument("--overwrite", action="store_true", help="vuelve a descargar las fuentes")
    args = parser.parse_args(argv)

    setup_logging()
    for nombre in PASOS:
        if nombre not in args.pasos:
            continue
        t0 = time.perf_counter()
        log.info("== %s ==", nombre)
        PASOS[nombre](overwrite=args.overwrite)
        log.info("== %s listo en %.1f s ==", nombre, time.perf_counter() - t0)


if __name__ == "__main__":
    main()
