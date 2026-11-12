"""Downloaderien yhteiset pienet apufunktiot.

Alustakohtaiset downloaderit voivat käyttää näitä ilman, että niiden tarvitsee
tuntea toistensa toteutusta.
"""

import os
import tempfile
import uuid


def make_tempfile(suffix: str = ".mp4") -> str:
    """Varaa uniikin väliaikaistiedoston polun."""
    with tempfile.NamedTemporaryFile(prefix="dl_", suffix=suffix, delete=False) as file:
        return file.name


def finalize(filepath: str, prefix: str) -> str:
    """Siirrä lataus väliaikaiskansioon uniikilla nimellä."""
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}_{os.path.basename(filepath)}"
    final = os.path.join(tempfile.gettempdir(), filename)
    os.replace(filepath, final)
    return final
