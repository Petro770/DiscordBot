"""Ollama replies to direct Discord mentions."""
import asyncio
import re
from contextlib import AsyncExitStack
from pathlib import Path

import aiohttp
import discord

import config
from core.logging import log


def _system_prompt() -> str:
    project_dir = Path(__file__).resolve().parents[1]
    default_file = project_dir / "instructions" / "discord-assistant.md"
    instructions = default_file.read_text(encoding="utf-8-sig").strip()
    if config.OLLAMA_INSTRUCTIONS_FILE:
        custom_file = project_dir / config.OLLAMA_INSTRUCTIONS_FILE
        try:
            custom = custom_file.read_text(encoding="utf-8-sig").strip()
            if custom:
                instructions = custom
            else:
                log.warning("Ollama: oma ohjetiedosto on tyhjä, käytetään oletusohjetta")
        except (OSError, UnicodeError):
            log.warning("Ollama: omaa ohjetiedostoa ei saatu luettua, käytetään oletusohjetta")

    services = (
        ("YouTube", config.ENABLE_YOUTUBE),
        ("Instagram", config.ENABLE_INSTAGRAM),
        ("X", config.ENABLE_X),
        ("TikTok", config.ENABLE_TIKTOK),
        ("Twitch", config.ENABLE_TWITCH),
        ("SoundCloud", config.ENABLE_SOUNDCLOUD),
    )
    enabled_services = ", ".join(name for name, enabled in services if enabled) or "ei yhtään"
    details = [f"Käytössä olevat medialatauspalvelut: {enabled_services}."]
    if config.ENABLE_SOUNDCLOUD:
        details.append(
            "SoundCloud lähetetään oletuksena MP4-videona ja tarvittaessa MP3-tiedostona."
            if config.ENABLE_SOUNDCLOUD_VIDEO else "SoundCloud lähetetään MP3-tiedostona."
        )
    if config.ENABLE_IMAGE_PRINTING:
        reactions = ", ".join(config.PRINT_EMOJIS)
        details.append(f"Kuvatulostus on käytössä. Tulostuspyyntö hyväksytään reaktiolla: {reactions}.")
    else:
        details.append("Kuvatulostus on pois käytöstä.")
    details.append(
        "Liiteindeksointi on käytössä määritetyillä kanavilla."
        if config.ATTACHMENT_INDEX_CHANNEL_IDS else "Liiteindeksointi on pois käytöstä."
    )
    return instructions + "\n\n# Tämän botin asetukset\n" + "\n".join(details)


async def _generate(prompt: str, system_prompt: str) -> str | None:
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
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": prompt},
                            ],
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
        self._system_prompt = _system_prompt()

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
            async with self._request, AsyncExitStack() as typing:
                try:
                    await typing.enter_async_context(message.channel.typing())
                except discord.HTTPException:
                    log.warning("Ollama: kirjoitusilmaisinta ei saatu näytettyä kanavalla %s", message.channel.id)
                try:
                    answer = await asyncio.wait_for(_generate(prompt, self._system_prompt), timeout=120)
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
