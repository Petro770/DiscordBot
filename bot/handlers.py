"""Yhteiset käsittelyfunktiot – kanava ja DM jakavat samaa logiikkaa."""
import asyncio
import os
import random
import re
from typing import Callable
from dataclasses import dataclass
from typing import Optional

import discord
import aiohttp

import config
from config import (
    IMAGE_EXTENSIONS,
    REPLY_DELETE_AFTER,
)
from printer.queue import PrintQueue
from core.logging import log
from core.queue import get_task_queue

from user.settings import should_include_content

# ============================================================
# SESSION (jaettu)
# ============================================================

_session: aiohttp.ClientSession | None = None

async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def _edit_status_safe(msg: discord.Message, text: str) -> None:
    """Päivitä tilaviesti turvallisesti, vaikka se olisi jo poistettu."""
    try:
        await msg.edit(content=text)
    except discord.NotFound:
        pass
    except discord.HTTPException:
        pass


def _effective_file_limit(message: discord.Message) -> int:
    """Palauta latauksille käytettävä Discord-tiedostoraja."""
    guild_limit = (
        message.guild.filesize_limit
        if message.guild is not None
        else discord.utils.DEFAULT_FILE_SIZE_LIMIT_BYTES
    )
    return min(25 * 1024 * 1024, guild_limit)


# ============================================================
# PENDING-REACTION-LOGIIKKA
# ============================================================

@dataclass
class PendingPrint:
    message_id: int
    channel_id: int
    filepaths: list[str]
    names: list[str]
    deadline: float
    emoji: str = ""
    timer_task: Optional[asyncio.Task] = None


_pending_prints: dict[int, PendingPrint] = {}

@dataclass
class PendingURL:
    message_id: int
    channel_id: int
    url: str
    names: list[str]
    deadline: float
    emoji: str = ""
    timer_task: Optional[asyncio.Task] = None
    delete_original: bool = False


_pending_urls: dict[int, PendingURL] = {}

_print_queue: PrintQueue | None = None
_bot: discord.Client | None = None


def init_handlers(bot: discord.Client, print_queue: PrintQueue):
    """Kutsutaan kerran käynnistyksessä."""
    global _print_queue, _bot
    _print_queue = print_queue
    _bot = bot

async def _remove_status(msg: discord.Message | None, delay: int | None = None):
    if msg is None:
        return
    try:
        if delay is None:
            delay = config.STATUS_DELETE_DELAY
        if delay > 0:
            await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass

async def _changelog_notify(message: discord.Message):
    """Kutsutaan työtehtävän alussa. Ei estä muuta käsittelyä."""
    if _bot is None:
        return
    try:
        from user.changelog import check_and_notify_user
        asyncio.create_task(
            check_and_notify_user(_bot, message.author.id, message.author.name)
        )
    except Exception:
        pass

async def handle_pending_image(message: discord.Message,    attachments: list[discord.Attachment],    names: list[str],):
    await _changelog_notify(message)
    filepaths: list[str] = []
    import tempfile
    for att in attachments:
        try:
            image_data = await att.read()
        except discord.HTTPException as exc:
            log.error("Kuvan %s lataaminen epäonnistui: %s", att.filename, exc)
            continue
        suffix = os.path.splitext(att.filename)[1]
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            filepaths.append(tmp.name)
            tmp.write(image_data)

    if not filepaths:
        return
    await _start_pending(message, filepaths, names)

async def handle_pending_image_links(message: discord.Message,    link_images: list[bytes],    names: list[str],):
    import tempfile
    await _changelog_notify(message)
    filepaths: list[str] = []
    for img_data in link_images:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            filepaths.append(tmp.name)
            tmp.write(img_data)

    if not filepaths:
        return
    await _start_pending(message, filepaths, names)

async def _start_pending(message: discord.Message,filepaths: list[str],names: list[str],):
    emoji = random.choice(config.PRINT_EMOJIS)
    try:
        await message.add_reaction(emoji)
    except Exception as e:
        log.warning("Emoji-reaktion lisäminen epäonnistui: %s", e)

    pending = PendingPrint(
        message_id=message.id,
        channel_id=message.channel.id,
        filepaths=filepaths,
        names=names,
        deadline = asyncio.get_running_loop().time() + config.PRINT_TIMEOUT,
        emoji=emoji,
    )
    _pending_prints[message.id] = pending
    pending.timer_task = asyncio.create_task(_print_timeout(pending))
    log.info("⏳ Odotetaan reaktiota: %d kuvaa, timeout=%ds, emoji=%s",
             len(filepaths), config.PRINT_TIMEOUT, emoji)

async def _print_timeout(pending: PendingPrint):
    try:
        await asyncio.sleep(config.PRINT_TIMEOUT)
    except asyncio.CancelledError:
        return

    if pending.message_id not in _pending_prints:
        return

    _pending_prints.pop(pending.message_id, None)
    for fp in pending.filepaths:
        if os.path.exists(fp):
            os.unlink(fp)
    if _bot is None:
        return
    try:
        channel = _bot.get_channel(pending.channel_id)
        if channel is None:
            channel = await _bot.fetch_channel(pending.channel_id)
        msg = await channel.fetch_message(pending.message_id)
        await msg.remove_reaction(pending.emoji, _bot.user)
        log.info("⏰ Timeout (viesti %d).", pending.message_id)
    except Exception:
        pass

async def _trigger_print(pending: PendingPrint, message: discord.Message):
    if pending.timer_task and not pending.timer_task.done():
        pending.timer_task.cancel()

    item = (pending.filepaths, message, pending.names)
    try:
        await asyncio.wait_for(_print_queue.queue.put(item), timeout=5)
        log.info("✅ Tulostus käynnistetty reaktiolla (%d kuvaa).", len(pending.filepaths))
    except asyncio.TimeoutError:
        for fp in pending.filepaths:
            if os.path.exists(fp):
                os.unlink(fp)
        _pending_prints.pop(pending.message_id, None)
        try:
            await message.reply("⏳ Tulostusjono täynnä, yritä myöhemmin.",
                               delete_after=REPLY_DELETE_AFTER)
        except Exception:
            pass
    finally:
        _pending_prints.pop(pending.message_id, None)

async def check_reaction(reaction: discord.RawReactionActionEvent) -> bool:
    """Tarkista onko reaktio tulostusreaktio. Palauttaa True jos käsiteltiin."""
    if reaction.user_id == _bot.user.id:
        return False

    pending = _pending_prints.get(reaction.message_id)
    if pending is None:
        return False

    if reaction.channel_id != pending.channel_id:
        return False

    emoji_str = str(reaction.emoji).rstrip('\ufe0f')
    if emoji_str not in config.PRINT_EMOJIS:
        return False

    log.info("🖨️ Tulostusreaktio: emoji=%s, viesti=%d", emoji_str, reaction.message_id)

    try:
        channel = _bot.get_channel(pending.channel_id)
        if channel is None:
            channel = await _bot.fetch_channel(pending.channel_id)
        message = await channel.fetch_message(reaction.message_id)
    except Exception as e:
        log.error("Viestin haku epäonnistui: %s", e)
        for fp in pending.filepaths:
            if os.path.exists(fp):
                os.unlink(fp)
        _pending_prints.pop(reaction.message_id, None)
        return True

    await _trigger_print(pending, message)
    return True

async def cleanup_pending():
    """Jaksollinen siivoaminen."""
    now = asyncio.get_running_loop().time()

    # Kuvat (olemassa oleva)
    expired_prints = [mid for mid, p in _pending_prints.items() if now > p.deadline]
    for mid in expired_prints:
        p = _pending_prints.pop(mid)
        for fp in p.filepaths:
            if os.path.exists(fp):
                os.unlink(fp)
        if p.timer_task and not p.timer_task.done():
            p.timer_task.cancel()
        try:
            channel = _bot.get_channel(p.channel_id)
            if channel is None:
                channel = await _bot.fetch_channel(p.channel_id)
            msg = await channel.fetch_message(mid)
            await msg.remove_reaction(p.emoji, _bot.user)
        except Exception:
            pass
        log.info("⏰ Siivottu print (viesti %d).", mid)

    # URL:t (UUSI)
    expired_urls = [mid for mid, p in _pending_urls.items() if now > p.deadline]
    for mid in expired_urls:
        p = _pending_urls.pop(mid)
        if p.timer_task and not p.timer_task.done():
            p.timer_task.cancel()
        try:
            channel = _bot.get_channel(p.channel_id)
            if channel is None:
                channel = await _bot.fetch_channel(p.channel_id)
            msg = await channel.fetch_message(mid)
            await msg.remove_reaction(p.emoji, _bot.user)
        except Exception:
            pass
        log.info("⏰ Siivottu URL (viesti %d).", mid)

# ============================================================
# VIDEO-KÄSITTELY (siirretty bot.py:stä)
# ============================================================

async def handle_youtube(message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: int | None = None):
    from downloaders.youtube import download_video, YOUTUBE_QUALITY_STEPS
    from core.models import NonRetryableError

    await _changelog_notify(message)

    s = Send(message, delete_original, forward_channel_id=forward_channel_id)
    log.info("🎬 YouTube: %s", url[:80])

    file_limit = _effective_file_limit(message)

    await s.send_status("🎬 Ladataan...")

    for max_height in YOUTUBE_QUALITY_STEPS:
        await s._update_status(f"🎬 Kokeillaan laatua {max_height}p...")
        try:
            result = await download_video(url, max_height=max_height)
        except NonRetryableError as e:
            await s._update_status(e.user_facing)
            await s.send(e.user_facing, delete_after=REPLY_DELETE_AFTER)
            return
        except Exception as e:
            log.exception("YouTube-lataus epäonnistui laadulla %dp", max_height)
            await s._update_status(
                f"⚠️ Laadun {max_height}p lataus epäonnistui. Kokeillaan seuraavaa laatua..."
            )
            continue

        if result is None:
            await s._update_status(
                f"ℹ️ Laatua {max_height}p ei voitu ladata. Kokeillaan seuraavaa laatua..."
            )
            continue


        filepath, filename = result.filepath, result.filename
        try:
            size = os.path.getsize(filepath)

            if size > file_limit:
                # --- KOMPRESSIO (uusi) ---
                if config.ENABLE_VIDEO_COMPRESS:
                    await s._update_status(
                        f"🎬 Video {size // (1024*1024)} MB – kompressoidaan..."
                    )
                    try:
                        from tools.vid_compress import compress_to_720p
                        compressed_path = filepath + ".compressed.mp4"
                        await asyncio.to_thread(
                            compress_to_720p, filepath, compressed_path,
                            config.VIDEO_COMPRESS_TARGET_MB
                        )
                        # Korvaa alkuperäisen
                        os.replace(compressed_path, filepath)
                        new_size = os.path.getsize(filepath)
                        await s._update_status(
                            f"✅ Kompressio valmis: {new_size // (1024*1024)} MB."
                        )
                    except Exception as comp_err:
                        log.warning("Kompressio epäonnistui: %s", comp_err)
                        await s._update_status(
                            f"⚠️ Kompressio epäonnistui. Kokeillaan seuraavaa laatua..."
                        )
                        continue
                else:
                    await s._update_status(
                        f"ℹ️ Laatu {max_height}p liian suuri "
                        f"({size // (1024*1024)} MB). Seuraava..."
                    )
                    continue

            # --- LÄHETYS ---
            await s._update_status(
                f"✅ Sopiva laatu: {max_height}p "
                f"({os.path.getsize(filepath) // (1024*1024)} MB)."
            )

            if should_include_content(message.author.id):
                meta = result.format_message()
                content = f"🎬 {meta}" if meta else f"🎬 *{filename}*"
            else:
                content = ""

            file = discord.File(filepath, filename=filename)
            await s.send(content, file=file)
            await s.delete_original()
            return

        finally:
            if os.path.exists(filepath):
                os.unlink(filepath)

    await s._update_status("⚠️ Lataus epäonnistui kaikilla kokeilluilla laadulla.")
    await s.send("⚠️ Lataus epäonnistui.", delete_after=REPLY_DELETE_AFTER)

async def handle_instagram(message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: int | None = None):
    from downloaders.instagram import download_instagram
    from core.models import NonRetryableError

    await _changelog_notify(message)

    await asyncio.sleep(1)
    log.info("📱 Instagram: %s", url[:80])

    s = Send(message, delete_original, forward_channel_id=forward_channel_id)
    file_limit = _effective_file_limit(message)

    await s.send_status("📱 Ladataan... anna hetki.")

    try:
        result = await download_instagram(url)
    except NonRetryableError as e:
        await s.send(e.user_facing, delete_after=REPLY_DELETE_AFTER)
        return

    if result is None:
        await s.send(
            "⚠️ Instagram-lataus epäonnistui.\n(Tarkista että postaus on julkinen.)",
            delete_after=REPLY_DELETE_AFTER,
        )
        return

    filepath, filename = result.filepath, result.filename
    size = os.path.getsize(filepath)

    try:
        if size > file_limit:
            await s.send(
                f"⚠️ Tiedosto liian suuri Discordille ({size // 1024 // 1024} MB > {file_limit // 1024 // 1024} MB).",
                delete_after=REPLY_DELETE_AFTER,
            )
        else:
            emoji = "🎬" if result.is_video else "🖼️"
            if should_include_content(message.author.id):
                meta = result.format_message()
                content = f"{emoji} {meta}" if meta else f"{emoji} *{filename}*"
            else:
                content = ""
            file = discord.File(filepath, filename=filename)
            await s.send(content, file=file)
            await s.delete_original()
    except Exception as e:
        log.error("Instagram-tiedoston lähettäminen epäonnistui: %s", e)
        await s.send("⚠️ Tiedoston lähettäminen epäonnistui.", delete_after=REPLY_DELETE_AFTER)
    finally:
        if os.path.exists(filepath):
            os.unlink(filepath)

async def handle_x(message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: int | None = None,):
    from downloaders.x import download_x
    from core.models import NonRetryableError

    await _changelog_notify(message)

    log.info("🐦 X: %s", url[:80])
    s = Send(message, delete_original, forward_channel_id=forward_channel_id)
    file_limit = _effective_file_limit(message)

    await s.send_status("🐦 Ladataan... anna hetki.")

    try:
        result = await download_x(url)
    except NonRetryableError as e:
        await s.send(e.user_facing, delete_after=REPLY_DELETE_AFTER)
        return

    if result is None:
        await s.send(
            "⚠️ X-videon lataus epäonnistui.\n(Tarkista että twiitti on julkinen.)",
            delete_after=REPLY_DELETE_AFTER,
        )
        return

    filepath, filename = result.filepath, result.filename
    size = os.path.getsize(filepath)

    try:
        if size > file_limit:
            await s.send(
                f"⚠️ Video liian suuri Discordille ({size // 1024 // 1024} MB > {file_limit // 1024 // 1024} MB).",
                delete_after=REPLY_DELETE_AFTER,
            )
        else:

            if should_include_content(message.author.id):
                meta = result.format_message()
                content = f"🐦 {meta}" if meta else f"🐦 *{filename}*"
            else:
                content = ""
            file = discord.File(filepath, filename=filename)
            await s.send(content, file=file)
            await s.delete_original()
    except Exception as e:
        log.error("X-tiedoston lähettäminen epäonnistui: %s", e)
        await s.send("⚠️ Tiedoston lähettäminen epäonnistui.", delete_after=REPLY_DELETE_AFTER)
    finally:
        if os.path.exists(filepath):
            os.unlink(filepath)

async def handle_tiktok(message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: int | None = None):
    from downloaders.tiktok import download_tiktok
    from core.models import NonRetryableError

    await _changelog_notify(message)

    log.info("🎵 TikTok: %s", url[:80])
    s = Send(message, delete_original, forward_channel_id=forward_channel_id)
    file_limit = _effective_file_limit(message)

    await s.send_status("🎵 Ladataan... anna hetki.")

    try:
        result = await download_tiktok(url)
    except NonRetryableError as e:
        await s.send(e.user_facing, delete_after=REPLY_DELETE_AFTER)
        return

    if result is None:
        await s.send(
            "⚠️ TikTok-videon lataus epäonnistui.\n(Tarkista että video on julkinen.)",
            delete_after=REPLY_DELETE_AFTER,
        )
        return

    filepath, filename = result.filepath, result.filename
    size = os.path.getsize(filepath)

    try:
        if size > file_limit:
            await s.send(
                f"⚠️ Video liian suuri Discordille ({size // 1024 // 1024} MB > {file_limit // 1024 // 1024} MB).",
                delete_after=REPLY_DELETE_AFTER,
            )
        else:

            if should_include_content(message.author.id):
                meta = result.format_message()
                content = f"🎵 {meta}" if meta else f"🎵 *{filename}*"
            else:
                content = ""

            file = discord.File(filepath, filename=filename)
            await s.send(content, file=file)
            await s.delete_original()
    except Exception as e:
        log.error("TikTok-tiedoston lähettäminen epäonnistui: %s", e)
        await s.send("⚠️ Tiedoston lähettäminen epäonnistui.", delete_after=REPLY_DELETE_AFTER)
    finally:
        if os.path.exists(filepath):
            os.unlink(filepath)

async def handle_twitch(message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: int | None = None):
    from downloaders.twitch import download_twitch
    from core.models import NonRetryableError

    await _changelog_notify(message)

    log.info("🎮 Twitch: %s", url[:80])
    s = Send(message, delete_original, forward_channel_id=forward_channel_id)
    file_limit = _effective_file_limit(message)

    await s.send_status("🎮 Ladataan Twitch-videota... anna hetki.")

    try:
        result = await download_twitch(url)
    except NonRetryableError as e:
        await s.send(e.user_facing, delete_after=REPLY_DELETE_AFTER)
        return

    if result is None:
        await s.send(
            "⚠️ Twitch-lataus epäonnistui.\n(Tarkista että video on julkinen.)",
            delete_after=REPLY_DELETE_AFTER,
        )
        return

    filepath, filename = result.filepath, result.filename
    size = os.path.getsize(filepath)

    try:
        if size > file_limit:
            await s.send(
                f"⚠️ Video liian suuri Discordille ({size // 1024 // 1024} MB > {file_limit // 1024 // 1024} MB).",
                delete_after=REPLY_DELETE_AFTER,
            )
        else:
            if should_include_content(message.author.id):
                meta = result.format_message()
                content = f"🎮 {meta}" if meta else f"🎮 *{filename}*"
            else:
                content = ""
            file = discord.File(filepath, filename=filename)
            await s.send(content, file=file)
            await s.delete_original()
    except Exception as e:
        log.error("Twitch-tiedoston lähettäminen epäonnistui: %s", e)
        await s.send("⚠️ Tiedoston lähettäminen epäonnistui.", delete_after=REPLY_DELETE_AFTER)
    finally:
        if os.path.exists(filepath):
            os.unlink(filepath)

async def handle_soundcloud(
    message: discord.Message,
    url: str,
    delete_original: bool = False,
    forward_channel_id: int | None = None,
):
    from core.models import NonRetryableError
    from downloaders.soundcloud import download_soundcloud

    await _changelog_notify(message)
    sender = Send(message, delete_original, forward_channel_id=forward_channel_id)
    await sender.send_status("🎵 Ladataan SoundCloud-kappaletta...")

    try:
        result = await download_soundcloud(url)
    except NonRetryableError as error:
        await sender.send(error.user_facing, delete_after=REPLY_DELETE_AFTER)
        return

    if result is None:
        await sender.send("⚠️ SoundCloud-kappaleen lataus epäonnistui.", delete_after=REPLY_DELETE_AFTER)
        return

    try:
        size = os.path.getsize(result.filepath)
        limit = _effective_file_limit(message)
        if size > limit:
            await sender.send(
                f"⚠️ Äänitiedosto ylittää Discordin kokorajan "
                f"({size / 1024**2:.1f} / {limit / 1024**2:.1f} Mt).",
                delete_after=REPLY_DELETE_AFTER,
            )
            return

        content = f"🎵 {result.format_message()}" if should_include_content(message.author.id) else ""
        file = discord.File(result.filepath, filename=result.filename)
        try:
            sent = await sender.send(content, file=file)
        finally:
            file.close()
        if sent is not None:
            await sender.delete_original()
    except discord.HTTPException:
        log.exception("SoundCloud-tiedoston lähettäminen epäonnistui")
        await sender.send("⚠️ Äänitiedoston lähettäminen epäonnistui.", delete_after=REPLY_DELETE_AFTER)
    finally:
        os.unlink(result.filepath)


# ============================================================
# URL-ROUTING (yhteinen)
# ============================================================

async def route_message(message: discord.Message, names: list[str]):
    """Yhteinen reititys: linkit → videot, kuvat → tulostus, muu → kuittaus."""
    from downloaders.youtube import is_youtube
    from downloaders.instagram import is_instagram
    from downloaders.x import is_x
    from downloaders.tiktok import is_tiktok
    from downloaders.twitch import is_twitch
    from downloaders.soundcloud import is_soundcloud

    # --- UNOHDAMINUT (ensimminä, ei saa osua muihin käsitteisiin) ---
    from user.settings import is_unohdaminut, handle_unohdaminut
    if is_unohdaminut(message.content):
        await handle_unohdaminut(message, bot=_bot)
        return True

    # Ohjekomennot
    from core.help import handle_help
    if await handle_help(message):
        return True

    # Tarkista ensin asetuskomennot
    from user.settings import handle_setting_command
    if await handle_setting_command(message):
        return True

    # --- Tunnista POISTA/DELETE (casesensitive) ---
    delete_original = False
    clean_content = message.content
    if message.content:
        words = message.content.split()
        if "POISTA" in words or "DELETE" in words:
            delete_original = True
            # Poista käsky sana sisältölinkkien tunnistuksesta
            clean_content = " ".join(w for w in words if w not in ("POISTA", "DELETE"))

    # --- Tunnista JAA (DM → kanava) ---
    forward_to_channel = False
    if message.content:
        words = message.content.split()
        if "JAA" in words or "FORWARD" in words:
            forward_to_channel = True
            # Luetaan kanava-id configista, jos käsky löytyy
            clean_content = " ".join(w for w in words if w not in ("JAA", "FORWARD"))

    # --- Onko botti mentionattu? ---
    bot_mentioned = any(
        mention.id == _bot.user.id
        for mention in message.mentions
        if _bot is not None
    )

    # --- Linkit ---
    if clean_content:
        urls = re.findall(r"https?://[^\s<>\"']+", clean_content)
        relevant_urls = []

        if config.ENABLE_YOUTUBE:
            relevant_urls.extend(u for u in urls if is_youtube(u))
        if config.ENABLE_INSTAGRAM:
            relevant_urls.extend(u for u in urls if is_instagram(u))
        if config.ENABLE_X:
            relevant_urls.extend(u for u in urls if is_x(u))
        if config.ENABLE_TIKTOK:
            relevant_urls.extend(u for u in urls if is_tiktok(u))
        if config.ENABLE_TWITCH:
            relevant_urls.extend(u for u in urls if is_twitch(u))
        if config.ENABLE_SOUNDCLOUD:
            relevant_urls.extend(u for u in urls if is_soundcloud(u))

        if relevant_urls:
            # DM: käsittele aina suoraan
            # Kanava + mention: käsittele suoraan
            # Kanava ILMA mentionia: kysy reaktiolla
            is_dm = isinstance(message.channel, discord.DMChannel)

            if len(relevant_urls) > 1:
                log.info("Useampi URL tunnistettu (%d), käsitellään vain ensimmäinen.", len(relevant_urls))

            if is_dm or bot_mentioned:
                # Suora käsittely
                url = relevant_urls[0]
                fwd = config.TARGET_CHANNEL_ID if forward_to_channel else None
                if is_youtube(url):
                    await handle_youtube(message, url, delete_original=delete_original, forward_channel_id=fwd)
                elif is_instagram(url):
                    await handle_instagram(message, url, delete_original=delete_original, forward_channel_id=fwd)
                elif is_x(url):
                    await handle_x(message, url, delete_original=delete_original, forward_channel_id=fwd)
                elif is_tiktok(url):
                    await handle_tiktok(message, url, delete_original=delete_original, forward_channel_id=fwd)
                elif is_twitch(url):
                    await handle_twitch(message, url, delete_original=delete_original, forward_channel_id=fwd)
                elif is_soundcloud(url):
                    await handle_soundcloud(message, url, delete_original=delete_original, forward_channel_id=fwd)
            else:
                # Kanava, ei mentionia → reaktiokysely
                await _start_pending_url(message, relevant_urls[0], names, delete_original=delete_original)
                return True

    # --- Kuvat (liitteet) ---
    if config.ENABLE_IMAGE_PRINTING:
        image_attachments = [
            att for att in message.attachments
            if att.filename.lower().endswith(IMAGE_EXTENSIONS)
        ]
        if image_attachments:
            await handle_pending_image(message, image_attachments, names)
            return True

    # --- Kuvat (linkit / Reddit) ---
    if config.ENABLE_IMAGE_PRINTING and clean_content:
        from scrapers.reddit import extract_from_message_links, extract_urls, is_reddit

        # Ennen tilaviestin lähettämistä: varmista että sisältöön on Reddit-URL:ia
        urls = extract_urls(clean_content)
        reddit_urls = [u for u in urls if is_reddit(u)]
        if not reddit_urls:
            return False

        # Tilaviesti alussa
        status_msg: discord.Message | None = None
        try:
            status_msg = await message.reply("📡 Etsitään Reddit-kuvia...", silent=True)
        except Exception:
            pass

        def _progress(text: str) -> None:
            nonlocal status_msg
            if status_msg is None:
                return
            asyncio.ensure_future(_edit_status_safe(status_msg, text))

        link_images = await extract_from_message_links(
            clean_content, await get_session(), on_progress=_progress
        )

        # Poista tilaviesti
        if status_msg is not None:
            try:
                await status_msg.delete()
            except Exception:
                pass

        if link_images:
            await handle_pending_image_links(message, link_images, names)
            return True

    return False

async def _send_and_cleanup(message: discord.Message,delete_original: bool,content: str,file: discord.File | None = None,):
    """Lähetä viesti + poista alkuperäinen jos pyydetty."""
    s = Send(message, delete_original)
    await s.send(content, file=file)
    await s.delete_original()

class Send:
    """Abstrahoi reply vs send+mention."""

    # --- Lisää nämä rivit luokan tasolle ---
    forward_channel_id: int | None
    _file_path: str | None

    def __init__(self,message: discord.Message,delete_original: bool = False,forward_channel_id: int | None = None, ):
        self.message = message
        self.channel = message.channel
        self.user = message.author
        self.should_delete_original = delete_original
        self.forward_channel_id = forward_channel_id
        self._status_msg: discord.Message | None = None
        self._file_path: str | None = None

    async def send_status(self, content: str) -> None:
        """Lähetä tilaviesti jonon kautta (rate-limited + viestisuojeltu)."""
        async def _do():
            self._status_msg = await self._do_send(content)
        await get_task_queue().submit(
            message_id=self.message.id,
            coro_factory=_do,
            user_id=self.user.id,
        )

    async def _update_status(self, content: str) -> None:
        """Muokkaa tilaviestiä – lokityyli: lisää rivi edellisen perään."""
        if self._status_msg is None:
            await self.send_status(content)
            return

        async def _do():
            try:
                if config.STATUS_LOG_MODE:
                    # Lokityyli: lisää uusi rivi vanhan perään
                    existing = self._status_msg.content
                    updated = f"{existing}\n{content}" if existing else content
                    # Rajoita 2000 merkkiin (Discord-raja)
                    if len(updated) > 1990:
                        updated = updated[-1987:] + "…"
                    self._status_msg = await self._status_msg.edit(content=updated)
                else:
                    # Vanha malli: pyyhitä ja kirjoita uudestaan
                    self._status_msg = await self._status_msg.edit(content=content)
            except discord.NotFound:
                self._status_msg = None
                self._status_msg = await self._do_send(content)
            except discord.HTTPException as e:
                log.warning("Tilaviestin päivitys epäonnistui: %s", e)

        await get_task_queue().submit(
            message_id=self.message.id,
            coro_factory=_do,
            user_id=self.user.id,
        )

    async def send(self, content, file=None, silent=True, delete_after=None):
        """Lopullinen viesti – korkeampi prioriteetti, siivoa tilaviestin ensin."""

        async def _do():
            await self._cleanup_status()
            if file is not None and hasattr(file, "fp"):
                fp = getattr(getattr(file, "fp", None), "name", None)
                self._file_path = fp if isinstance(fp, str) else None
            result_msg = await self._do_send(content, file=file, silent=silent, delete_after=delete_after)
            if self.forward_channel_id and result_msg is not None:
                await self._forward_to_channel(content, file)
            return result_msg

        # Prioriteetti 1 = korkea (lopullinen viesti etenee ennen tilaviestejä)
        result = await get_task_queue().submit_priority(
            message_id=self.message.id,
            coro_factory=_do,
            user_id=self.user.id,
            priority=1,
        )
        return result

    async def _forward_to_channel(self, content: str, file) -> None:
        """Lähetä viesti myös julkiselle kanavalle."""
        if _bot is None:
            return
        try:
            target = _bot.get_channel(self.forward_channel_id)
            if target is None:
                target = await _bot.fetch_channel(self.forward_channel_id)
            mention = f"<@!{self.user.id}>"

            if file is not None and self._file_path and os.path.exists(self._file_path):
                new_file = discord.File(self._file_path, filename=file.filename)
                await target.send(f"{mention} {content}", file=new_file)
            else:
                await target.send(f"{mention} {content}")

            log.info("Forward kanavalle onnistui.")
        except Exception as e:
            log.warning("Forward kanavalle epäonnistui: %s", e)

    async def _do_send(self, content: str, file=None, silent=True, delete_after=None) -> discord.Message:
        kwargs = {}
        if delete_after is not None:
            kwargs["delete_after"] = delete_after

        if self.should_delete_original:
            mention = f"<@!{self.user.id}>"
            result = await self.channel.send(f"{mention} {content}", file=file, **kwargs)
        else:
            kwargs["silent"] = silent
            result = await self.message.reply(content, file=file, **kwargs)

        # Rekisteröi viesti poistolokiin
        from user.tracker import register_message
        register_message(result)

        return result

    async def _cleanup_status(self) -> None:
        """Poista aiemmin lähetetty tilaviesti."""
        if self._status_msg is None:
            return
        try:
            await self._status_msg.delete()
        except Exception:
            pass
        self._status_msg = None

    async def delete_original(self) -> None:
        """Poista alkuperäinen viesti ja siivoa tilaviestin."""
        await self._cleanup_status()
        if not self.should_delete_original:
            return
        try:
            await self.message.delete()
        except discord.Forbidden:
            log.warning(
                "Botilla ei ole oikeutta poistaa viestiä. "
                "Tarkista Manage Messages -oikeus. "
                "Viesti ID: %s, kanava ID: %s",
                self.message.id,
                self.channel.id,
            )
        except discord.NotFound:
            log.info("Poistettava viesti ei enää ole olemassa. Viesti ID: %s", self.message.id)
        except discord.HTTPException:
            log.warning("Discord API -virhe viestiä poistettaessa. Viesti ID: %s", self.message.id)

# ============================================================
# PENDING URL (reaktio-kysely videotulostukseen)
# ============================================================

async def _start_pending_url(message: discord.Message,url: str,names: list[str],delete_original: bool = False, ):
    emoji = "🎬"
    try:
        await message.add_reaction(emoji)
    except Exception as e:
        log.warning("PendingURL: reaktion lisäys epäonnistui: %s", e)

    pending = PendingURL(
        message_id=message.id,
        channel_id=message.channel.id,
        url=url,
        names=names,
        deadline=asyncio.get_running_loop().time() + config.PRINT_TIMEOUT,
        emoji=emoji,
        delete_original=delete_original,
    )
    _pending_urls[message.id] = pending
    pending.timer_task = asyncio.create_task(_pending_url_timeout(pending))
    log.info("⏳ Odotetaan URL-reaktiota: %s (timeout=%ds)", url[:60], config.PRINT_TIMEOUT)

async def _pending_url_timeout(pending: PendingURL):
    try:
        await asyncio.sleep(config.PRINT_TIMEOUT)
    except asyncio.CancelledError:
        return

    if pending.message_id not in _pending_urls:
        return

    _pending_urls.pop(pending.message_id, None)
    if _bot is None:
        return
    try:
        channel = _bot.get_channel(pending.channel_id)
        if channel is None:
            channel = await _bot.fetch_channel(pending.channel_id)
        msg = await channel.fetch_message(pending.message_id)
        await msg.remove_reaction(pending.emoji, _bot.user)
        log.info("⏰ PendingURL timeout (viesti %d).", pending.message_id)
    except Exception:
        pass

async def _trigger_url(pending: PendingURL, message: discord.Message):
    """Kun reaktio saatu → käsittele URL."""
    if pending.timer_task and not pending.timer_task.done():
        pending.timer_task.cancel()
    _pending_urls.pop(pending.message_id, None)

    # Reititä URL normaaliin käsittelyyn.
    from downloaders.youtube import is_youtube
    from downloaders.instagram import is_instagram
    from downloaders.x import is_x
    from downloaders.tiktok import is_tiktok
    from downloaders.twitch import is_twitch
    from downloaders.soundcloud import is_soundcloud

    url = pending.url
    del_orig = pending.delete_original

    try:
        if is_youtube(url):
            await handle_youtube(message, url, delete_original=del_orig)
        elif is_instagram(url):
            await handle_instagram(message, url, delete_original=del_orig)
        elif is_x(url):
            await handle_x(message, url, delete_original=del_orig)
        elif is_tiktok(url):
            await handle_tiktok(message, url, delete_original=del_orig)
        elif is_twitch(url):
            await handle_twitch(message, url, delete_original=del_orig)
        elif is_soundcloud(url):
            await handle_soundcloud(message, url, delete_original=del_orig)
        else:
            await message.reply("⚠️ Tuntuma URL ei ole tunnistettu.", delete_after=REPLY_DELETE_AFTER)
    except Exception as e:
        log.error("PendingURL: käsittely epäonnistui: %s", e)
        try:
            await message.reply("⚠️ Käsittely epäonnistui.", delete_after=REPLY_DELETE_AFTER)
        except Exception:
            pass

async def check_url_reaction(reaction: discord.RawReactionActionEvent) -> bool:
    """Tarkista onko reaktio pending-URL-reaktio."""
    if reaction.user_id == _bot.user.id:
        return False

    pending = _pending_urls.get(reaction.message_id)
    if pending is None:
        return False

    if reaction.channel_id != pending.channel_id:
        return False

    emoji_str = str(reaction.emoji).rstrip('\ufe0f')
    if emoji_str != config.URL_REACTION_EMOJI:
        return False

    log.info("🎬 URL-reaktio saatu: viesti=%d, url=%s", reaction.message_id, pending.url[:60])

    try:
        channel = _bot.get_channel(pending.channel_id)
        if channel is None:
            channel = await _bot.fetch_channel(pending.channel_id)
        message = await channel.fetch_message(reaction.message_id)
    except Exception as e:
        log.error("PendingURL: viestin haku epäonnistui: %s", e)
        _pending_urls.pop(reaction.message_id, None)
        return True

    await _trigger_url(pending, message)
    return True

def _make_threadsafe_progress(s: "Send") -> Callable[[str], None]:
    """Luo callbackin joka päivittää tilaviestin thread-turvallisesti."""
    loop = asyncio.get_running_loop()

    def _callback(text: str) -> None:
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(s._update_status(text)))

    return _callback
