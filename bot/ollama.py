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
from bot.ollama_trace import setup_trace, trace
from core.logging import log


_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_CONTEXT_KEYS = re.compile(r"""["'](viite|roolit|viesti|henkilöt|istunto|aiemmat_vuorot|kanavaviestit)["']\s*:""")


def _echoes_internal_context(answer: str) -> bool:
    keys = set(_CONTEXT_KEYS.findall(answer))
    return (
        {"viite", "roolit"} <= keys
        or {"viesti", "henkilöt"} <= keys
        or bool({"aiemmat_vuorot", "kanavaviestit"} & keys)
    )


def _is_cloud_model(model: str) -> bool:
    name = model.lower()
    return name.endswith(":cloud") or name.split(":", 1)[0].endswith("-cloud")


def _is_image(attachment: discord.Attachment) -> bool:
    if attachment.content_type:
        return attachment.content_type.split(";", 1)[0].strip().lower() in _IMAGE_TYPES
    return Path(attachment.filename).suffix.lower() in _IMAGE_SUFFIXES


async def _model_kind(session, host: str, model: str, timeout: aiohttp.ClientTimeout) -> str | None:
    try:
        async with session.post(
            f"{host}/api/show", json={"model": model}, timeout=timeout, allow_redirects=False,
        ) as response:
            data = await response.json()
        if data.get("remote_host"):
            return "remote"
        capabilities = data.get("capabilities")
        if isinstance(capabilities, list):
            return "vision" if "vision" in capabilities else "text"
        log.info("Ollama %s / %s: palvelin ei ilmoittanut mallin kykyjä", host, model)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, aiohttp.ClientResponseError) and exc.status == 404:
            log.info("Ollama %s / %s: mallia ei löydy palvelimelta", host, model)
            return "missing"
        log.warning(
            "Ollama %s / %s: mallin kykyjä ei saatu tarkistettua (%s, HTTP %s)",
            host, model, type(exc).__name__, getattr(exc, "status", "-"),
        )
    return None


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
        self._model_kinds: dict[tuple[str, str], tuple[float, str | None]] = {}

    async def model_kind(self, session, host: str, model: str, timeout: aiohttp.ClientTimeout):
        key = (host, model)
        cached = self._model_kinds.get(key)
        if cached and cached[0] > monotonic():
            return cached[1]
        kind = await _model_kind(session, host, model, timeout)
        self._model_kinds[key] = (monotonic() + (300 if kind else 30), kind)
        return kind

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
    hosts: OllamaHosts, host: str, prompt: str, system_prompt: str, image: str | None,
    message_id: int | None, models_override: tuple[str, ...] | None,
    history: list[dict[str, str]], visited: set[str],
) -> tuple[str | None, str | None, int]:
    models = models_override or config.OLLAMA_MODELS
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
                and not _is_cloud_model(entry["name"])
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning(
                "Ollama %s: mallien haku epäonnistui (%s, HTTP %s)",
                host, type(exc).__name__, getattr(exc, "status", "-"),
            )
            trace("discovery_error", message_id, host=host, error=type(exc).__name__,
                  status=getattr(exc, "status", None))
            return None, None, 0

    candidates = tuple(
        model for model in dict.fromkeys(models)
        if model not in config.OLLAMA_EXCLUDED_MODELS and model not in visited and not _is_cloud_model(model)
    )
    log.info("Ollama %s: kokeiltavat mallit=%s (ehdokkaita ennen poissulkuja=%s)",
             host, candidates, len(models))
    if not candidates:
        log.info("Ollama %s: ei uusia kokeiltavia malleja", host)
    attempts = 0
    user_message = {"role": "user", "content": prompt}
    if image is not None:
        user_message["images"] = [image]
    for model in candidates:
        visited.add(model)
        kind = await hosts.model_kind(session, host, model, discovery_timeout)
        if kind in {"remote", "missing"} or (image is not None and kind != "vision") or (image is None and kind == "vision"):
            log.info("Ollama %s / %s: ohitettu | mallityyppi=%s | kuvapyyntö=%s",
                     host, model, kind, image is not None)
            trace("model_skipped", message_id, host=host, model=model, model_kind=kind,
                  has_image=image is not None)
            continue
        attempts += 1
        started = monotonic()
        log.info("Ollama %s / %s: lähetetään chat-pyyntö", host, model)
        trace("model_attempt", message_id, host=host, model=model)
        try:
            async with session.post(
                f"{host}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        *history,
                        user_message,
                    ],
                    "stream": False,
                    "options": {"num_predict": 500},
                },
                allow_redirects=False,
            ) as response:
                data = await response.json()
            raw_answer = data["message"]["content"]
            trace("model_response", message_id, host=host, model=model, content=raw_answer,
                  done_reason=data.get("done_reason"), elapsed_seconds=round(monotonic() - started, 3))
            answer = raw_answer.strip()
            if _echoes_internal_context(answer):
                log.warning(
                    "Ollama %s / %s: sisäisen kontekstin toistanut vastaus hylättiin | viesti=%s",
                    host, model, message_id,
                )
                trace("model_response_rejected", message_id, host=host, model=model,
                      reason="internal_context_echo")
                continue
            if split_style(answer)[0]:
                log.info("Ollama %s / %s: vastaus saatu (%.1f s)", host, model, monotonic() - started)
                return answer, model, attempts
            log.warning("Ollama %s / %s: ei käyttäjälle tarkoitettua vastaustekstiä", host, model)
            trace("model_response_rejected", message_id, host=host, model=model, reason="empty_reply")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
            log.warning(
                "Ollama %s / %s: pyyntö epäonnistui (%.1f s, %s, HTTP %s)",
                host, model, monotonic() - started, type(exc).__name__, getattr(exc, "status", "-"),
            )
            trace("model_error", message_id, host=host, model=model, error=type(exc).__name__,
                  status=getattr(exc, "status", None), elapsed_seconds=round(monotonic() - started, 3))

    return None, None, attempts


async def _generate(
    prompt: str, system_prompt: str, hosts: OllamaHosts, image: str | None = None, *,
    message_id: int | None = None, preferred: tuple[str, str] | None = None,
    history: list[dict[str, str]] | None = None,
) -> tuple[str, tuple[str, str]] | None:
    timeout = aiohttp.ClientTimeout(
        total=config.OLLAMA_MODEL_TIMEOUT_SECONDS,
        connect=config.OLLAMA_CONNECT_TIMEOUT_SECONDS,
    )
    discovery_timeout = aiohttp.ClientTimeout(total=config.OLLAMA_DISCOVERY_TIMEOUT_SECONDS)
    if not hosts.hosts:
        log.warning("Ollama: yhtään palvelinta ei ole määritetty | viesti=%s", message_id)

    priority = config.OLLAMA_VISION_PRIORITY if image is not None else config.OLLAMA_CHAT_PRIORITY
    phases: list[tuple[tuple[str, ...], tuple[str, ...] | None]] = []
    if preferred and preferred[0] in hosts.hosts:
        phases.append(((preferred[0],), (preferred[1],)))
    phases.extend((hosts.hosts, (model,)) for model in priority)
    phases.append((hosts.hosts, None))
    visited = {host: set() for host in hosts.hosts}
    attempts = 0
    async with aiohttp.ClientSession(timeout=timeout, raise_for_status=True) as session:
        for phase_hosts, models in phases:
            if models and (
                models[0] in config.OLLAMA_EXCLUDED_MODELS
                or _is_cloud_model(models[0])
                or (config.OLLAMA_MODELS and models[0] not in config.OLLAMA_MODELS)
            ):
                continue
            remaining = [host for host in phase_hosts if not models or models[0] not in visited[host]]
            while remaining:
                trace("waiting_host", message_id, candidates=list(remaining))
                async with hosts.reserve(remaining) as host:
                    remaining.remove(host)
                    trace("host_selected", message_id, host=host)
                    answer, model, host_attempts = await _generate_on_host(
                        session, discovery_timeout, hosts, host, prompt, system_prompt, image,
                        message_id, models, history or [], visited[host],
                    )
                    attempts += host_attempts
                    if answer and model:
                        return answer, (host, model)
    trace("models_exhausted", message_id, has_image=image is not None, attempts=attempts)
    if image is not None and not attempts:
        log.warning(
            "Ollama: yhtään kuvia tukevaa mallia ei saatu vahvistettua | viesti=%s | palvelimia=%s",
            message_id, len(hosts.hosts),
        )
    elif not attempts:
        log.warning(
            "Ollama: yksikään määritetty palvelin ei tarjonnut käyttökelpoista paikallista tekstimallia | viesti=%s | palvelimia=%s",
            message_id, len(hosts.hosts),
        )
    else:
        log.warning(
            "Ollama: mallikierros päättyi ilman vastausta | viesti=%s | kuvapyyntö=%s | chat-yrityksiä=%s",
            message_id, image is not None, attempts,
        )
    return None


class OllamaReplies:
    def __init__(self):
        setup_trace()
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
        trace("discord_input", message.id, channel_id=channel_id,
              channel_name=getattr(message.channel, "name", None) if message.guild else None,
              private=not bool(message.guild), content=message.content,
              attachment_count=len(message.attachments))
        prompt = mention.sub("", message.content).strip()
        images = [attachment for attachment in message.attachments if _is_image(attachment)]
        image = next((attachment for attachment in images if attachment.size <= _MAX_IMAGE_BYTES), None)
        if message.attachments and not images:
            log.info(
                "Ollama: liitteissä ei ollut tuettua kuvaformaattia | viesti=%s | liitteitä=%s",
                message.id, len(message.attachments),
            )
        if image is not None and not prompt:
            prompt = "Kuvaile lyhyesti, mitä kuvassa näkyy."

        if self._pending >= 20 + len(self._hosts.hosts):
            log.warning("Ollama: jono täynnä | viesti=%s | kanava=%s", message.id, channel_id)
            try:
                await message.add_reaction("🚫")
            except discord.HTTPException:
                log.warning("Ollama: täyden jonon reaktiota ei saatu lisättyä | viesti=%s", message.id)
            trace("queue_full", message.id, channel_id=channel_id)
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
                trace("waiting_turn", message.id)
                await asyncio.shield(previous)
            payload = style = text_target = None
            if images and image is None:
                log.warning(
                    "Ollama: kuvaliitteet ylittävät kokorajan | viesti=%s | kuvia=%s | raja=%s tavua",
                    message.id, len(images), _MAX_IMAGE_BYTES,
                )
                trace("image_error", message.id, reason="Kokoraja ylittyi")
                answer = "Liitä enintään 8 Mt:n kuva, niin voin yrittää tulkita sen."
            elif prompt:
                trace("waiting_worker", message.id)
                async with self._workers:
                    answer, style, payload, text_target = await self._answer(message, prompt, bot_user_id, image)
            else:
                log.info("Ollama: maininnassa ei ollut kysymystä tai sopivaa kuvaa | viesti=%s", message.id)
                answer = "Kirjoita kysymys samaan viestiin maininnan kanssa."
            sent = await self._reply(message, answer)
            if sent and payload is not None:
                self._memory.remember(channel_id, payload, answer, style, text_target)
                if style:
                    log.info("Ollama: istunnon tyyli päivitetty | kanava=%s", channel_id)
            trace("finished", message.id, outcome=(
                "success" if sent and payload is not None else "fallback" if sent else "send_error"
            ))
        except asyncio.CancelledError:
            trace("cancelled", message.id)
            raise
        except Exception as exc:
            trace("failed", message.id, error=type(exc).__name__)
            raise
        finally:
            self._pending -= 1
            if previous is not None and not previous.done():
                previous.add_done_callback(finish_turn)
            else:
                finish_turn()

    async def _answer(
        self, message: discord.Message, prompt: str, bot_user_id: int,
        image: discord.Attachment | None,
    ) -> tuple[str, str | None, str | None, tuple[str, str] | None]:
        log.info("Ollama: käsittely alkaa | viesti=%s", message.id)
        trace("preparing", message.id, has_image=image is not None)
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
                    trace("image_error", message.id, error=type(exc).__name__)
                    return "Kuvaa ei saatu ladattua Discordista.", None, None, None
                if not raw or len(raw) > _MAX_IMAGE_BYTES:
                    log.warning("Ollama: kuvan data hylätty | viesti=%s | tavua=%s", message.id, len(raw))
                    trace("image_error", message.id, reason="Tyhjä tai liian suuri kuva")
                    return "Kuvan pitää olla enintään 8 Mt ja sisältää kuvadataa.", None, None, None
                image_data = b64encode(raw).decode("ascii")
                log.info("Ollama: kuva ladattu | viesti=%s | tavua=%s", message.id, len(raw))

            payload, mentions, recent_count, people_count = await prepare_people(message, prompt, bot_user_id)
            context = self._memory.add_context(message.channel.id, payload)
            history = self._memory.chat_history(message.channel.id)
            preferred = self._memory.text_target(message.channel.id)
            trace("model_input", message.id, system=self._system_prompt, user=context,
                  has_image=image_data is not None, history=history, history_turns=len(history) // 2,
                  recent_messages=recent_count, people_count=people_count,
                  session_style=self.session_style(message.channel.id), text_target=preferred)
            try:
                result = await asyncio.wait_for(
                    _generate(context, self._system_prompt, self._hosts, image_data,
                              message_id=message.id, preferred=preferred if image is None else None, history=history),
                    timeout=config.OLLAMA_TOTAL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                log.warning(
                    "Ollama: vastaamisen kokonaisaika (%g s) ylittyi | viesti=%s | kuvapyyntö=%s",
                    config.OLLAMA_TOTAL_TIMEOUT_SECONDS, message.id, image is not None,
                )
                trace("model_timeout", message.id, timeout_seconds=config.OLLAMA_TOTAL_TIMEOUT_SECONDS)
                result = None
        raw_answer, target = result or ("", None)
        answer, style = split_style(raw_answer)
        if not answer:
            log.warning("Ollama: viesti %s jäi ilman mallin vastausta", message.id)
            if image is not None:
                return "Ollama ei saanut tulkittua kuvaa. Tarkista lokista, löytyikö kuvaa tukeva malli.", None, None, None
            return "Ollama ei saanut muodostettua vastausta. Palvelin voi olla poissa käytöstä tai sopiva paikallinen malli voi puuttua.", None, None, None
        rendered = render_people(answer, mentions)
        trace("parsed_response", message.id, content=rendered, style=style,
              text_target=target if image is None else None)
        return rendered, style, payload, target if image is None else None

    async def _reply(self, message: discord.Message, answer: str) -> bool:
        channel_id = message.channel.id
        encoded = answer.encode("utf-16-le")
        if len(encoded) > 4000:
            answer = encoded[:3998].decode("utf-16-le", errors="ignore").rstrip() + "…"
        try:
            sent = await message.reply(
                answer, mention_author=False, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException as exc:
            log.warning(
                "Ollama: vastausta ei saatu lähetettyä | viesti=%s | kanava=%s | HTTP=%s | Discord=%s",
                message.id, channel_id, exc.status, exc.code,
            )
            trace("discord_send_error", message.id, channel_id=channel_id,
                  status=exc.status, code=exc.code, content=answer)
            return False
        trace("discord_output", message.id, channel_id=channel_id, reply_id=sent.id, content=answer)
        log.info("Ollama: vastaus lähetetty | viesti=%s | kanava=%s", message.id, channel_id)
        return True
