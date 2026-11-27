"""Downloaderien yhteiset pienet apufunktiot.

Alustakohtaiset downloaderit voivat käyttää näitä ilman, että niiden tarvitsee
tuntea toistensa toteutusta.
"""

import os
import shutil
import tempfile
import uuid
from functools import lru_cache

from core.models import NonRetryableError


@lru_cache(maxsize=1)
def ffmpeg_executables() -> tuple[str, str]:
    """Resolve FFmpeg on demand inside the download worker."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe and os.path.dirname(ffmpeg) == os.path.dirname(ffprobe):
        return ffmpeg, ffprobe

    try:
        from static_ffmpeg import run

        ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
    except Exception as exc:
        raise NonRetryableError(
            f"FFmpegin alustus epäonnistui ({type(exc).__name__}): {exc}",
            "⚠️ FFmpeg ei ole käytettävissä. Käynnistä botti projektin .venv-ympäristöstä "
            "tai lisää ffmpeg ja ffprobe samasta kansiosta bottikoneen PATHiin.",
        ) from exc
    return ffmpeg, ffprobe


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
