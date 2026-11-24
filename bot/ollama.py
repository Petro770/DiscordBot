"""Ollama replies to direct Discord mentions."""
import asyncio
import re

import aiohttp
import discord

import config
from core.logging import log


async def _generate(prompt: str) -> str | None:
    timeout = aiohttp.ClientTimeout(total=40, connect=3)
    async with aiohttp.ClientSession(timeout=timeout, raise_for_status=True) as session:
        for host in config.OLLAMA_HOSTS:
            models = config.OLLAMA_MODELS
            if not models:
                try:
                    async with session.get(
                        f"{host}/api/tags", timeout=aiohttp.ClientTimeout(total=5),
                        allow_redirects=False,
                    ) as response:
                        data = await response.json()
                    models = tuple(
                        entry["name"] for entry in data["models"]
                        if entry.get("name") and not entry.get("remote_host")
                        and not entry["name"].lower().endswith(":cloud")
                        and not entry["name"].lower().split(":", 1)[0].endswith("-cloud")
                    )
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    log.warning("Ollama %s: mallien haku epäonnistui (%s)", host, type(exc).__name__)
                    continue

            for model in models:
                try:
                    async with session.post(
                        f"{host}/api/chat",
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "stream": False,
                            "options": {"num_predict": 500},
                        },
                        allow_redirects=False,
                    ) as response:
                        data = await response.json()
                    answer = data["message"]["content"].strip()
                    if answer:
                        log.info("Ollama-vastaus: %s / %s", host, model)
                        return answer
                    log.warning("Ollama %s / %s: tyhjä vastaus", host, model)
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    log.warning("Ollama %s / %s: pyyntö epäonnistui (%s)", host, model, type(exc).__name__)
    return None


class OllamaReplies:
    def __init__(self):
        self._request = asyncio.Lock()

    async def handle(self, message: discord.Message, bot_user_id: int):
        if message.author.bot:
            return
        if message.guild and message.channel.id not in config.OLLAMA_CHANNEL_IDS:
            return
        mention = re.compile(rf"<@!?{bot_user_id}>")
        if not mention.search(message.content):
            return
        prompt = mention.sub("", message.content).strip()

        if not prompt:
            answer = "Kirjoita kysymys samaan viestiin maininnan kanssa."
        elif self._request.locked():
            answer = "Vastaan parhaillaan toiseen kysymykseen. Kokeile hetken päästä uudelleen."
        else:
            async with self._request:
                try:
                    answer = await asyncio.wait_for(_generate(prompt), timeout=120)
                except asyncio.TimeoutError:
                    log.warning("Ollama: vastaamisen kokonaisaika ylittyi")
                    answer = None
            if not answer:
                answer = "Ollama ei saanut tällä kertaa muodostettua vastausta."

        encoded = answer.encode("utf-16-le")
        if len(encoded) > 4000:
            answer = encoded[:3998].decode("utf-16-le", errors="ignore").rstrip() + "…"
        try:
            await message.reply(
                answer, mention_author=False, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException:
            log.warning("Ollama: vastausta viestiin %s ei saatu lähetettyä", message.id)
