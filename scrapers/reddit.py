import re
from typing import Callable
import asyncio
import urllib.parse
import aiohttp

from core.logging import log

import time
_proxy_cache: dict[str, tuple[float, str | None]] = {}
CACHE_TTL = 300  # 5 min

REDDIT_URL_PATTERN = re.compile(
    r"https?://(?:www\.|old\.|np\.)?reddit\.com/(r/[^/]+)/comments/([^/]+)",
    re.IGNORECASE,
)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s<>\"']+", text)


def is_reddit(url: str) -> bool:
    return bool(REDDIT_URL_PATTERN.search(url))


def parse_reddit_url(url: str) -> tuple[str, str] | None:
    match = REDDIT_URL_PATTERN.search(url)
    if not match:
        return None
    return match.group(1).replace("r/", ""), match.group(2)


# ============================================================
# PROXY-VAIHTOEHDOT
# ============================================================

def _proxy_codetabs(target: str) -> str:
    return f"https://api.codetabs.com/v1/proxy?quest={urllib.parse.quote(target, safe='')}"


def _proxy_allorigins(target: str) -> str:
    return f"https://api.allorigins.win/raw?url={urllib.parse.quote(target, safe='')}"


def _proxy_corsproxy(target: str) -> str:
    return f"https://corsproxy.io/?url={urllib.parse.quote(target, safe='')}"


# ============================================================
# PÄÄLOGIIKKA: PROXY-KETJU
# ============================================================

async def extract_images_reddit(
    url: str,
    session: aiohttp.ClientSession,
    on_progress: Callable[[str], None] | None = None,
) -> list[str]:
    parsed = parse_reddit_url(url)
    if not parsed:
        return []

    subreddit, post_id = parsed
    base_url = f"https://www.reddit.com/r/{subreddit}/comments/{post_id}"
    json_url = f"{base_url}.json?raw_json=1"

    cache_key = f"reddit:{subreddit}:{post_id}"
    if cache_key in _proxy_cache:
        ts, cached = _proxy_cache[cache_key]
        if time.time() - ts < CACHE_TTL:
            return cached if cached else []

    if on_progress:
        on_progress(f"📡 Etsitään kuvaa (r/{subreddit})...")

    text = await _fetch_via_proxy(json_url, session, on_progress)
    if text is None:
        text = await _fetch_via_proxy(base_url, session, on_progress)
    if text is None:
        if on_progress:
            on_progress("⚠️ Kaikki proxyt epäonnistuivat.")
        _proxy_cache[cache_key] = (time.time(), [])
        return []

    images = _parse_reddit_json(text)
    if images:
        _proxy_cache[cache_key] = (time.time(), images)
        if on_progress:
            on_progress(f"✅ Löydetty {len(images)} kuvaa.")

    return images


async def _fetch_via_proxy(
    target_url: str,
    session: aiohttp.ClientSession,
    on_progress: Callable[[str], None] | None = None,
) -> str | None:
    proxies = [
        ("codetabs", _proxy_codetabs),
        ("allorigins", _proxy_allorigins),
        ("corsproxy", _proxy_corsproxy),
    ]
    _evict_cache()

    for name, fn in proxies:
        proxy_url = fn(target_url)
        if on_progress:
            on_progress(f"🔄 Proxy: {name}...")
        try:
            async with session.get(
                proxy_url,
                headers={"User-Agent": BROWSER_UA},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    if len(text) > 50:
                        if on_progress:
                            on_progress(f"✅ {name} onnistui.")
                        return text
                    if on_progress:
                        on_progress(f"⚠️ {name}: tyhjä vastaus.")
                else:
                    if on_progress:
                        on_progress(f"⚠️ {name}: HTTP {resp.status}.")
        except Exception as e:
            if on_progress:
                on_progress(f"❌ {name}: {type(e).__name__}.")

    return None


def _parse_reddit_json(text: str) -> list[str]:
    """Parsea Reddit JSON-vastauksesta kuva-URL:t."""
    import json

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Ei JSONia — ehkä HTML. Etsi og:image tai i.redd.it.
        urls = re.findall(r"https?://(?:i\.redd\.it|preview\.redd\.it)/[^\s\"'<>]+", text)
        if urls:
            return list(dict.fromkeys(urls))  # dedup, preserve order
        og = re.search(r'og:image["\'][^>]+content=["\']([^"\']+)', text)
        if og:
            return [og.group(1)]
        return []

    try:
        post = data[0]["data"]["children"][0]["data"]
    except (IndexError, KeyError, TypeError):
        return []

    image_urls = []

    main_url = post.get("url_overridden_by_domain") or post.get("url", "")
    if main_url and main_url.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        image_urls.append(main_url)

    preview = post.get("preview", {})
    for img in preview.get("images", []):
        sources = img.get("sources", [])
        if sources:
            best = sources[-1]["url"]
            if best not in image_urls:
                image_urls.append(best)

    return list(dict.fromkeys(image_urls))



# ============================================================
# LATAUS
# ============================================================

async def download_image(url: str, session: aiohttp.ClientSession) -> bytes | None:

    # Yritä suoraan
    try:
        async with session.get(
            url,
            headers={"User-Agent": BROWSER_UA},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception:
        pass

    # Jos suora ei toiminut (i.redd.it voi blockata), yritä proxyä
    log.info("Kuvaa ladataan proxyta: %s", url[:60])
    for name, fn in [("codetabs", _proxy_codetabs), ("allorigins", _proxy_allorigins)]:
        try:
            proxy_url = fn(url)
            async with session.get(
                proxy_url,
                headers={"User-Agent": BROWSER_UA},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception:
            continue

    log.error("Kuvan lataus epäonnistui: %s", url[:80])
    return None


# ============================================================
# JULKINEN API
# ============================================================
async def extract_from_message_links(
    text: str,
    session: aiohttp.ClientSession,
    on_progress: Callable[[str], None] | None = None,
) -> list[bytes]:
    urls = extract_urls(text)
    reddit_urls = [u for u in urls if is_reddit(u)]
    if not reddit_urls:
        return []

    image_urls: list[str] = []
    for rurl in reddit_urls:
        if on_progress:
            on_progress(f"📋 Tarkistetaan: {rurl[:50]}...")
        images = await extract_images_reddit(rurl, session, on_progress)
        image_urls.extend(images)

    results: list[bytes] = []
    for i, img_url in enumerate(image_urls):
        if on_progress:
            on_progress(f"⬇️ Ladataan kuvaa {i+1}/{len(image_urls)}...")
        data = await download_image(img_url, session)
        if data:
            results.append(data)
        elif on_progress:
            on_progress(f"❌ Kuva {i+1} epäonnistui.")

    return results


def _evict_cache():
    now = time.time()
    for k in list(_proxy_cache.keys()):  # list copy
        if now - _proxy_cache[k][0] > CACHE_TTL:
            _proxy_cache.pop(k, None)


