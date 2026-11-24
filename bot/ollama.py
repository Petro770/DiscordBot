"""Ollama replies to direct Discord mentions."""
import asyncio
from base64 import b64encode
import re
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from time import monotonic

import aiohttp
import discord

import config
from bot.ollama_people import PEOPLE_INSTRUCTIONS, prepare_people, render_people
from bot.ollama_style import STYLE_INSTRUCTIONS, SessionMemory, split_style
from core.logging import log


_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024


def _is_image(attachment: discord.Attachment) -> bool:
    if attachment.content_type:
        return attachment.content_type.split(";", 1)[0].strip().lower() in _IMAGE_TYPES
    return Path(attachment.filename).suffix.lower() in _IMAGE_SUFFIXES


async def _supports_vision(session, host: str, model: str, timeout: aiohttp.ClientTimeout) -> bool:
    try:
        async with session.post(
            f"{host}/api/show", json={"model": model}, timeout=timeout, allow_redirects=False,
        ) as response:
            data = await response.json()
        if not data.get("remote_host") and "vision" in data.get("capabilities", ()):
            return True
        log.info("Ollama %s / %s: mallilla ei ole paikallista kuvatukea", host, model)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, AttributeError) as exc:
        log.warning("Ollama %s / %s: kuvatukea ei saatu tarkistettua (%s)", host, model, type(exc).__name__)
    return False


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


class OllamaHosts:
    def __init__(self, hosts: tuple[str, ...]):
        self.hosts = tuple(dict.fromkeys(hosts))
        self._busy: set[str] = set()
        self._available = asyncio.Condition()

    @asynccontextmanager
    async def reserve(self, candidates: list[str]):
        async with self._available:
            await self._available.wait_for(lambda: any(host not in self._busy for host in candidates))
            host = next(host for host in candidates if host not in self._busy)
            self._busy.add(host)
        try:
            yield host
        finally:
            async with self._available:
                self._busy.remove(host)
                self._available.notify_all()


async def _generate_on_host(
    session: aiohttp.ClientSession, discovery_timeout: aiohttp.ClientTimeout,
    host: str, prompt: str, system_prompt: str, image: str | None,
) -> str | None:
    models = config.OLLAMA_MODELS
    if not models:
        log.info("Ollama %s: haetaan mallilista", host)
        try:
            async with session.get(
                f"{host}/api/tags", timeout=discovery_timeout,
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
            log.warning(
                "Ollama %s: mallien haku epäonnistui (%s, HTTP %s)",
                host, type(exc).__name__, getattr(exc, "status", "-"),
            )
            return None

    candidates = tuple(model for model in models if model not in config.OLLAMA_EXCLUDED_MODELS)
    log.info("Ollama %s: kokeiltavat mallit=%s (ehdokkaita ennen poissulkuja=%s)",
             host, candidates, len(models))
    user_message = {"role": "user", "content": prompt}
    if image is not None:
        user_message["images"] = [image]
    for model in candidates:
        if image is not None and not await _supports_vision(session, host, model, discovery_timeout):
            continue
        started = monotonic()
        log.info("Ollama %s / %s: lähetetään chat-pyyntö", host, model)
        try:
            async with session.post(
                f"{host}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        user_message,
                    ],
                    "stream": False,
                    "options": {"num_predict": 500},
                },
                allow_redirects=False,
            ) as response:
                data = await response.json()
            answer = data["message"]["content"].strip()
            if answer:
                log.info("Ollama %s / %s: vastaus saatu (%.1f s)", host, model, monotonic() - started)
                return answer
            log.warning("Ollama %s / %s: tyhjä vastaus", host, model)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning(
                "Ollama %s / %s: pyyntö epäonnistui (%.1f s, %s, HTTP %s)",
                host, model, monotonic() - started, type(exc).__name__, getattr(exc, "status", "-"),
            )

    return None


async def _generate(
    prompt: str, system_prompt: str, hosts: OllamaHosts, image: str | None = None,
) -> str | None:
    timeout = aiohttp.ClientTimeout(
        total=config.OLLAMA_MODEL_TIMEOUT_SECONDS,
        connect=config.OLLAMA_CONNECT_TIMEOUT_SECONDS,
    )
    discovery_timeout = aiohttp.ClientTimeout(total=config.OLLAMA_DISCOVERY_TIMEOUT_SECONDS)
    remaining = list(hosts.hosts)
    async with aiohttp.ClientSession(timeout=timeout, raise_for_status=True) as session:
        while remaining:
            async with hosts.reserve(remaining) as host:
                remaining.remove(host)
                answer = await _generate_on_host(session, discovery_timeout, host, prompt, system_prompt, image)
                if answer:
                    return answer
    return None


class OllamaReplies:
    def __init__(self):
        self._hosts = OllamaHosts(config.OLLAMA_HOSTS)
        self._workers = asyncio.Semaphore(max(1, len(self._hosts.hosts)))
        self._pending = 0
        self._reply_tails: dict[int, asyncio.Future] = {}
        self._memory = SessionMemory()
        self._system_prompt = "\n\n".join((_system_prompt(), PEOPLE_INSTRUCTIONS, STYLE_INSTRUCTIONS))

    def session_style(self, channel_id: int | None) -> str:
        return self._memory.style(channel_id) if channel_id is not None else ""

    async def handle(self, message: discord.Message, bot_user_id: int):
        if message.author.bot:
            return
        mention = re.compile(rf"<@!?{bot_user_id}>")
        if not mention.search(message.content) and not any(user.id == bot_user_id for user in message.mentions):
            return

        channel_id = message.channel.id
        parent_id = getattr(message.channel, "parent_id", None)
        if message.guild and not config.OLLAMA_CHANNEL_IDS.intersection((channel_id, parent_id)):
            log.info(
                "Ollama: maininta ohitettu | viesti=%s | kanava=%s | yläkanava=%s | sallitut=%s",
                message.id, channel_id, parent_id, sorted(config.OLLAMA_CHANNEL_IDS),
            )
            return
        log.info("Ollama: maininta hyväksytty | viesti=%s | kanava=%s", message.id, channel_id)
        prompt = mention.sub("", message.content).strip()
        images = [attachment for attachment in message.attachments if _is_image(attachment)]
        image = next((attachment for attachment in images if attachment.size <= _MAX_IMAGE_BYTES), None)
        if image is not None and not prompt:
            prompt = "Kuvaile lyhyesti, mitä kuvassa näkyy."

        if self._pending >= 20 + len(self._hosts.hosts):
            log.warning("Ollama: jono täynnä | viesti=%s | kanava=%s", message.id, channel_id)
            try:
                await message.add_reaction("🚫")
            except discord.HTTPException:
                log.warning("Ollama: täyden jonon reaktiota ei saatu lisättyä | viesti=%s", message.id)
            return

        previous = self._reply_tails.get(channel_id)
        turn = asyncio.get_running_loop().create_future()
        self._reply_tails[channel_id] = turn
        self._pending += 1
        log.info("Ollama: viesti jonossa | viesti=%s | kesken=%s", message.id, self._pending)

        def finish_turn(_previous=None):
            if not turn.done():
                turn.set_result(None)
            if self._reply_tails.get(channel_id) is turn:
                del self._reply_tails[channel_id]

        try:
            # Read context after the preceding turn has been sent and recorded.
            if previous is not None:
                await asyncio.shield(previous)
            payload = style = None
            if images and image is None:
                answer = "Liitä enintään 8 Mt:n kuva, niin voin yrittää tulkita sen."
            elif prompt:
                async with self._workers:
                    answer, style, payload = await self._answer(message, prompt, bot_user_id, image)
            else:
                answer = "Kirjoita kysymys samaan viestiin maininnan kanssa."
            if await self._reply(message, answer) and payload is not None:
                self._memory.remember(channel_id, payload, answer, style)
                if style:
                    log.info("Ollama: istunnon tyyli päivitetty | kanava=%s", channel_id)
        finally:
            self._pending -= 1
            if previous is not None and not previous.done():
                previous.add_done_callback(finish_turn)
            else:
                finish_turn()

    async def _answer(
        self, message: discord.Message, prompt: str, bot_user_id: int,
        image: discord.Attachment | None,
    ) -> tuple[str, str | None, str | None]:
        log.info("Ollama: käsittely alkaa | viesti=%s", message.id)
        async with AsyncExitStack() as typing:
            try:
                await typing.enter_async_context(message.channel.typing())
            except discord.HTTPException:
                log.warning("Ollama: kirjoitusilmaisinta ei saatu näytettyä kanavalla %s", message.channel.id)
            image_data = None
            if image is not None:
                try:
                    raw = await asyncio.wait_for(image.read(), timeout=10)
                except (discord.HTTPException, asyncio.TimeoutError) as exc:
                    log.warning("Ollama: kuvaa ei saatu ladattua | viesti=%s | %s", message.id, type(exc).__name__)
                    return "Kuvaa ei saatu ladattua Discordista.", None, None
                if not raw or len(raw) > _MAX_IMAGE_BYTES:
                    return "Kuvan pitää olla enintään 8 Mt ja sisältää kuvadataa.", None, None
                image_data = b64encode(raw).decode("ascii")
                log.info("Ollama: kuva ladattu | viesti=%s | tavua=%s", message.id, len(raw))

            payload, mentions = await prepare_people(message, prompt, bot_user_id)
            context = self._memory.add_context(message.channel.id, payload)
            try:
                answer = await asyncio.wait_for(
                    _generate(context, self._system_prompt, self._hosts, image_data),
                    timeout=config.OLLAMA_TOTAL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                log.warning(
                    "Ollama: vastaamisen kokonaisaika (%g s) ylittyi | viesti=%s",
                    config.OLLAMA_TOTAL_TIMEOUT_SECONDS, message.id,
                )
                answer = None
        answer, style = split_style(answer or "")
        if not answer:
            log.warning("Ollama: viesti %s jäi ilman mallin vastausta", message.id)
            if image is not None:
                return "Ollama ei saanut tulkittua kuvaa. Tarkista lokista, löytyikö kuvaa tukeva malli.", None, None
            return "Ollama ei saanut tällä kertaa muodostettua vastausta.", None, None
        return render_people(answer, mentions), style, payload

    async def _reply(self, message: discord.Message, answer: str) -> bool:
        channel_id = message.channel.id
        encoded = answer.encode("utf-16-le")
        if len(encoded) > 4000:
            answer = encoded[:3998].decode("utf-16-le", errors="ignore").rstrip() + "…"
        try:
            await message.reply(
                answer, mention_author=False, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException as exc:
            log.warning(
                "Ollama: vastausta ei saatu lähetettyä | viesti=%s | kanava=%s | HTTP=%s | Discord=%s",
                message.id, channel_id, exc.status, exc.code,
            )
            return False
        log.info("Ollama: vastaus lähetetty | viesti=%s | kanava=%s", message.id, channel_id)
        return True
