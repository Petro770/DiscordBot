"""Tulostuslogiikka – Windows (GDI) ja Linux (lp)."""
import os
import platform
from PIL import Image, ImageOps

from config import PRINTER_NAME
from core.logging import log


class InvalidPrintImage(ValueError):
    pass


def load_image(path: str) -> Image.Image:
    """Lataa kuvan valkoisella taustalla RGB-tilana."""
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        log.warning("Tulostuskuvan lukeminen epäonnistui: %s", exc)
        raise InvalidPrintImage("Tiedosto ei ole kelvollinen tai tuettu kuva.") from exc
    white = Image.new("RGBA", image.size, "white")
    white.alpha_composite(image)
    return white.convert("RGB")


def _print_windows(image: Image.Image, printer_name: str, title: str) -> str:
    import win32ui
    from PIL import ImageWin

    dc = win32ui.CreateDC()
    scaled = None
    started = False
    try:
        dc.CreatePrinterDC(printer_name)
        page_w, page_h = dc.GetDeviceCaps(8), dc.GetDeviceCaps(10)
        dpi_x, dpi_y = dc.GetDeviceCaps(88), dc.GetDeviceCaps(90)

        # Skaalaa kuva tulostusalueen leveyteen
        scale = page_w / image.width
        target_w = page_w
        target_h = max(1, round(image.height * scale))

        try:
            scaled = image.resize((target_w, target_h), Image.Resampling.LANCZOS)

            dc.StartDoc(title)
            started = True

            for top in range(0, target_h, page_h):
                bottom = min(top + page_h, target_h)
                part = scaled.crop((0, top, target_w, bottom))
                dc.StartPage()
                ImageWin.Dib(part).draw(dc.GetHandleOutput(), (0, 0, part.width, part.height))
                dc.EndPage()
            dc.EndDoc()

        finally:
            if scaled is not None:
                scaled.close()

        started = False
        return "Työ lisätty Windowsin tulostusjonoon."

    except Exception:
        if started:
            try:
                dc.AbortDoc()
            except Exception:
                pass
        raise
    finally:
        dc.DeleteDC()

def _print_windows_file(filepath: str, printer_name: str) -> str:
    image = load_image(filepath)
    try:
        return _print_windows(image, printer_name, "DiscordBot Print")
    finally:
        image.close()


def _print_linux(filepath: str, printer_name: str) -> str:
    import subprocess
    subprocess.run(["lp", "-d", printer_name, filepath], check=True)
    return "Työ lisätty Linuxin tulostusjonoon."


def print_image(filepath: str, printer_name: str | None = None) -> str:
    printer_name = printer_name or PRINTER_NAME
    if platform.system().lower() == "linux":
        return _print_linux(filepath, printer_name)
    return _print_windows_file(filepath, printer_name)


