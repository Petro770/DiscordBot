import asyncio
import subprocess
import sys
import io
import logging
from pathlib import Path

if __package__:
    from core.logging import log
else:
    log = logging.getLogger("steamdb")
from playwright.async_api import async_playwright

# --- Stealth-import: yritetään eri variantteja ---
try:
    # Vanilla 1.x / useimmat versiot
    from playwright_stealth import stealth_async
    STEALTH_MODE = "stealth_async"
except ImportError:
    try:
        # Uudempi API (2.x)
        from playwright_stealth import Stealth
        STEALTH_MODE = "Stealth"
    except ImportError:
        # Viimeinen varalta: manuaalinen init-script
        STEALTH_MODE = "manual"

try:
    from PIL import Image
except ImportError:
    print("PIL ei ole asennettu. Asennetaan: pip install Pillow")
    subprocess.run([sys.executable, "-m", "pip", "install", "Pillow"], check=True)
    from PIL import Image


def install_playwright_browsers():
    log.warning("SteamDB: Playwrightin Chromium puuttuu, yritetään asentaa se")
    print("Playwrightin Chromium puuttuu. Asennetaan Chromium...", flush=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True, timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.error("SteamDB: Chromiumin asennus epäonnistui: %s", exc)
        raise RuntimeError("Chromiumin asennus epäonnistui. Suorita python -m playwright install chromium.") from exc


async def apply_stealth(page):
    """Aplikoi stealth-tilan riippumatta paketin versiosta."""
    if STEALTH_MODE == "stealth_async":
        await stealth_async(page)
        print("Stealth aktivoitu (stealth_async)")

    elif STEALTH_MODE == "Stealth":
        stealth = Stealth()
        # Yritetään useita API-muotoja
        try:
            await stealth.use(page)
        except AttributeError:
            try:
                await stealth.apply(page)
            except AttributeError:
                await page.add_init_script(stealth.script())
        print("Stealth aktivoitu (Stealth-luokka)")

    else:
        # Manuaalinen fallback: injektoidaan stealth-js suoraan
        stealth_js = """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['fi-FI', 'fi', 'en-US', 'en'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        window.chrome = { runtime: {} };
        """
        await page.add_init_script(stealth_js)
        print("Stealth aktivoitu (manuaalinen init-script)")


async def capture_steamdb_chart():
    async with async_playwright() as p:
        print("Käynnistetään suojattu selain...")

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-infobars",
        ]

        executable = Path(p.chromium.executable_path)
        if not executable.is_file():
            await asyncio.to_thread(install_playwright_browsers)
            if not executable.is_file():
                log.error("SteamDB: Chromiumin suoritustiedosto puuttuu asennuksen jälkeen: %s", executable)
                raise RuntimeError(
                    "Chromium puuttuu asennuksen jälkeen. Tarkista selaimen asennuskansion kirjoitusoikeus "
                    "ja suorita python -m playwright install chromium."
                )
        try:
            browser = await p.chromium.launch(headless=False, args=launch_args)
        except Exception as exc:
            log.error("SteamDB: Chromiumin käynnistys epäonnistui: %s", exc)
            raise RuntimeError("SteamDB:n Chromiumia ei voitu käynnistää. Tarkista Playwright-asennus.") from exc

        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="fi-FI",
            timezone_id="Europe/Helsinki",
            accept_downloads=True,
        )

        page = await context.new_page()

        # --- Stealth ENNEN navigointia ---
        await apply_stealth(page)

        print("Navigoidaan SteamDB-sivulle... (Cloudflare saattaa miettiä hetken)")
        await page.goto("https://steamdb.info", wait_until="domcontentloaded")

        chart_selector = "#charts"
        try:
            print("Odotetaan kaavion latautumista (30s timeout)...")
            await page.wait_for_selector(chart_selector, timeout=30000)

            # Annetaan canvas/SVG renderöityä
            await page.wait_for_timeout(2000)

            chart_element = await page.query_selector(chart_selector)
            image_bytes = await chart_element.screenshot()

            image = Image.open(io.BytesIO(image_bytes))
            image.save("steamdb_price_history.png")
            print("\n✅ Onnistui! Kaavio tallennettu: steamdb_price_history.png")

        except Exception as e:
            print("\n❌ Kaaviota ei saatu ladattua.")
            print(f"   Syy: {e}")
            print("   Jätetään selain auki 8s, jotta voit tarkastaa tilanteen...")
            await page.wait_for_timeout(8000)

        await browser.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(capture_steamdb_chart())

