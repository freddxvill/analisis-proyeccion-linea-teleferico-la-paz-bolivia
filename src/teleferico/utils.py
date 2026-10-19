"""Utilidades de descarga y logging."""

import logging
from pathlib import Path

import requests

log = logging.getLogger("teleferico")


def download(url: str, dest: Path, overwrite: bool = False, timeout: int = 300) -> Path:
    """Descarga `url` en `dest` salvo que ya exista (caché simple por archivo)."""
    if dest.exists() and not overwrite:
        log.info("En caché: %s", dest.name)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("Descargando %s", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    return dest


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
