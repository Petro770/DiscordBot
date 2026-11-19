"""Read public metadata from AliExpress product pages."""

import asyncio
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

import aiohttp


def product_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url.rstrip(").,!?]*_~|`"))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "aliexpress.com", "www.aliexpress.com", "m.aliexpress.com",
    }:
        return None
    match = re.fullmatch(r"/item/([0-9]{1,20})\.html/?", parsed.path)
    if match:
        return f"https://www.aliexpress.com/item/{match[1]}.html"
    return None


class ProductMetadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        attributes = dict(attrs)
        key = attributes.get("property") or attributes.get("name") or attributes.get("itemprop")
        content = attributes.get("content")
        if key and content and content.strip():
            self.fields.setdefault(key.lower(), content.strip())


async def fetch_product_metadata(
    session: aiohttp.ClientSession, url: str,
) -> dict[str, str]:
    url = product_url(url)
    if url is None:
        return {}
    try:
        async with session.get(
            url,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=8),
        ) as response:
            if response.status != 200 or response.content_type != "text/html":
                return {}
            metadata = ProductMetadata()
            try:
                html = await response.content.readexactly(512 * 1024)
            except asyncio.IncompleteReadError as exc:
                html = exc.partial
            metadata.feed(html.decode("utf-8", errors="replace"))
            metadata.close()
            return metadata.fields
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return {}
