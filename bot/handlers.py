"""Yhteiset käsittelyfunktiot – kanava ja DM jakavat samaa logiikkaa."""
import asyncio
import os
import random
import re
import tempfile
from typing import Callable, Optional
from dataclasses import dataclass

import discord
import aiohttp

import config
from config import (
    IMAGE_EXTENSIONS,
    REPLY_DELETE_AFTER,
)
from printer.engine import remove_print_file
from printer.queue import PrintQueue
from core.logging import log
from core.queue import TaskQueue
from scrapers.aliexpress import fetch_product_metadata, product_url as aliexpress_product_url

from user.settings import should_include_content

# ============================================================
# SESSION (jaettu)
# ============================================================

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



@dataclass
class PendingURL:
    message_id: int
    channel_id: int
    url: str
    names: list[str]
    deadline: float
    emojis: tuple[str, ...]
    timer_task: Optional[asyncio.Task] = None
    delete_original: bool = False


SOUNDCLOUD_MP3_EMOJI = "🎵"



async def _remove_status(msg: discord.Message | None, delay: Optional[int] = None):
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

def _save_print_image(data: bytes, suffix: str) -> str | None:
    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            path = temporary.name
            temporary.write(data)
    except OSError:
        log.exception("Tulostuskuvan tallennus epäonnistui")
        if path is not None:
            remove_print_file(path)
        return None
    return path


class Send:
    """Abstrahoi reply vs send+mention."""

    def __init__(
        self, bot: discord.Client, queue: TaskQueue, message: discord.Message,
        delete_original: bool = False, forward_channel_id: Optional[int] = None,
    ):
        self.bot = bot
        self.queue = queue
        self.message = message
        self.channel = message.channel
        self.user = message.author
        self.should_delete_original = delete_original
        self.forward_channel_id = forward_channel_id
        self._status_msg: discord.Message | None = None
        self._file_path: str | None = None
        self._delivered = False

    async def send_status(self, content: str) -> None:
        """Lähetä tilaviesti jonon kautta (rate-limited + viestisuojeltu)."""
        async def _do():
            self._status_msg = await self._do_send(content)
        await self.queue.submit(
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

        await self.queue.submit(
            message_id=self.message.id,
            coro_factory=_do,
            user_id=self.user.id,
        )

    async def send(self, content, file=None, silent=True, delete_after=None, *, embed=None):
        """Lopullinen viesti – korkeampi prioriteetti, siivoa tilaviestin ensin."""

        async def _do():
            await self._cleanup_status()
            if file is not None and hasattr(file, "fp"):
                fp = getattr(getattr(file, "fp", None), "name", None)
                self._file_path = fp if isinstance(fp, str) else None
            result_msg = await self._do_send(content, file=file, silent=silent, delete_after=delete_after, embed=embed)
            self._delivered = result_msg is not None
            if self.forward_channel_id and self._delivered:
                await self._forward_to_channel(content, file, embed=embed)
            return result_msg

        # Prioriteetti 1 = korkea (lopullinen viesti etenee ennen tilaviestejä)
        result = await self.queue.submit_priority(
            message_id=self.message.id,
            coro_factory=_do,
            user_id=self.user.id,
            priority=1,
        )
        return result

    async def _forward_to_channel(self, content: str, file, *, embed=None) -> None:
        """Lähetä viesti myös julkiselle kanavalle."""
        try:
            target = self.bot.get_channel(self.forward_channel_id)
            if target is None:
                target = await self.bot.fetch_channel(self.forward_channel_id)
            mention = f"<@!{self.user.id}>"

            if file is not None and self._file_path and os.path.exists(self._file_path):
                new_file = discord.File(self._file_path, filename=file.filename)
                await target.send(f"{mention} {content}", file=new_file)
            else:
                kwargs = {"embed": embed} if embed is not None else {}
                await target.send(f"{mention} {content}", **kwargs)

            log.info("Forward kanavalle onnistui.")
        except Exception as e:
            log.warning("Forward kanavalle epäonnistui: %s", e)

    async def _do_send(self, content: str, file=None, silent=True, delete_after=None, *, embed=None) -> discord.Message | None:
        kwargs = {}
        if embed is not None:
            kwargs["embed"] = embed
        if delete_after is not None:
            kwargs["delete_after"] = delete_after

        if self.should_delete_original:
            mention = f"<@!{self.user.id}>"
            result = await self.channel.send(f"{mention} {content}", file=file, **kwargs)
        else:
            kwargs["silent"] = silent
            result = await self.message.reply(content, file=file, **kwargs)

        if result is None:
            log.warning("Discord-lähetys ei palauttanut viestiä | alkuperäinen=%s", self.message.id)
            return None

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
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            log.warning("Tilaviestin poisto epäonnistui | alkuperäinen=%s | HTTP=%s", self.message.id, exc.status)
        self._status_msg = None

    async def delete_original(self) -> None:
        """Poista alkuperäinen viesti ja siivoa tilaviestin."""
        await self._cleanup_status()
        if not self.should_delete_original:
            return
        if not self._delivered:
            log.warning("Alkuperäinen viesti säilytettiin, koska vastausta ei toimitettu | viesti=%s", self.message.id)
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

class MessageHandlers:
    def __init__(self, bot: discord.Client, print_queue: PrintQueue, task_queue: TaskQueue):
        self._bot = bot
        self._print_queue = print_queue
        self._task_queue = task_queue
        self._pending_prints: dict[int, PendingPrint] = {}
        self._pending_urls: dict[int, PendingURL] = {}
        self._session: aiohttp.ClientSession | None = None
        self._closed = False

    async def get_session(self) -> aiohttp.ClientSession:
        if self._closed:
            raise RuntimeError("Botin viestinkäsittely on suljettu.")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        self._closed = True
        timers = [
            item.timer_task
            for item in (*self._pending_prints.values(), *self._pending_urls.values())
            if item.timer_task is not None
        ]
        for task in timers:
            task.cancel()
        await asyncio.gather(*timers, return_exceptions=True)
        for pending in self._pending_prints.values():
            for path in pending.filepaths:
                remove_print_file(path)
        self._pending_prints.clear()
        self._pending_urls.clear()
        if self._session is not None:
            await self._session.close()

    async def _changelog_notify(self, message: discord.Message):
        """Kutsutaan työtehtävän alussa. Ei estä muuta käsittelyä."""
        if self._bot.user is None:
            return
        try:
            from user.changelog import check_and_notify_user
            asyncio.create_task(
                check_and_notify_user(self._bot, message.author.id, message.author.name, source=message)
            )
        except Exception:
            pass

    async def handle_pending_image(self, message: discord.Message, attachments: list[discord.Attachment], names: list[str]):
        await self._changelog_notify(message)
        filepaths = []
        try:
            for attachment in attachments:
                try:
                    data = await asyncio.wait_for(attachment.read(), timeout=30)
                except (discord.HTTPException, asyncio.TimeoutError, OSError):
                    log.warning("Tulostuskuvan lataus epäonnistui | liite=%s", attachment.id, exc_info=True)
                    continue
                path = _save_print_image(data, os.path.splitext(attachment.filename)[1])
                if path is not None:
                    filepaths.append(path)
            if filepaths:
                await self._start_pending(message, filepaths, names)
                filepaths = []
        finally:
            for path in filepaths:
                remove_print_file(path)


    async def handle_pending_image_links(self, message: discord.Message, link_images: list[bytes], names: list[str]):
        await self._changelog_notify(message)
        filepaths = []
        try:
            for data in link_images:
                path = _save_print_image(data, ".jpg")
                if path is not None:
                    filepaths.append(path)
            if filepaths:
                await self._start_pending(message, filepaths, names)
                filepaths = []
        finally:
            for path in filepaths:
                remove_print_file(path)


    async def _start_pending(self, message: discord.Message,filepaths: list[str],names: list[str],):
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
        self._pending_prints[message.id] = pending
        pending.timer_task = asyncio.create_task(self._print_timeout(pending))
        log.info("⏳ Odotetaan reaktiota: %d kuvaa, timeout=%ds, emoji=%s",
                 len(filepaths), config.PRINT_TIMEOUT, emoji)

    async def _print_timeout(self, pending: PendingPrint):
        try:
            await asyncio.sleep(config.PRINT_TIMEOUT)
        except asyncio.CancelledError:
            return

        if pending.message_id not in self._pending_prints:
            return

        self._pending_prints.pop(pending.message_id, None)
        for fp in pending.filepaths:
            remove_print_file(fp)
        if self._bot.user is None:
            return
        try:
            channel = self._bot.get_channel(pending.channel_id)
            if channel is None:
                channel = await self._bot.fetch_channel(pending.channel_id)
            msg = await channel.fetch_message(pending.message_id)
            await msg.remove_reaction(pending.emoji, self._bot.user)
            log.info("⏰ Timeout (viesti %d).", pending.message_id)
        except Exception:
            pass

    async def _trigger_print(self, pending: PendingPrint, message: discord.Message):
        if pending.timer_task and not pending.timer_task.done():
            pending.timer_task.cancel()

        item = (pending.filepaths, message, pending.names)
        try:
            await asyncio.wait_for(self._print_queue.queue.put(item), timeout=5)
            log.info("✅ Tulostus käynnistetty reaktiolla (%d kuvaa).", len(pending.filepaths))
        except asyncio.CancelledError:
            for fp in pending.filepaths:
                remove_print_file(fp)
            raise
        except asyncio.TimeoutError:
            for fp in pending.filepaths:
                remove_print_file(fp)
            self._pending_prints.pop(pending.message_id, None)
            try:
                await message.reply("⏳ Tulostusjono täynnä, yritä myöhemmin.",
                                   delete_after=REPLY_DELETE_AFTER)
            except Exception:
                pass
        finally:
            self._pending_prints.pop(pending.message_id, None)

    async def check_reaction(self, reaction: discord.RawReactionActionEvent) -> bool:
        """Tarkista onko reaktio tulostusreaktio. Palauttaa True jos käsiteltiin."""
        if self._bot.user is None or reaction.user_id == self._bot.user.id:
            return False

        pending = self._pending_prints.get(reaction.message_id)
        if pending is None:
            return False

        if reaction.channel_id != pending.channel_id:
            return False

        emoji_str = str(reaction.emoji).rstrip('\ufe0f')
        if emoji_str not in config.PRINT_EMOJIS:
            return False

        log.info("🖨️ Tulostusreaktio: emoji=%s, viesti=%d", emoji_str, reaction.message_id)

        try:
            channel = self._bot.get_channel(pending.channel_id)
            if channel is None:
                channel = await self._bot.fetch_channel(pending.channel_id)
            message = await channel.fetch_message(reaction.message_id)
        except Exception as e:
            log.error("Viestin haku epäonnistui: %s", e)
            for fp in pending.filepaths:
                remove_print_file(fp)
            self._pending_prints.pop(reaction.message_id, None)
            return True

        await self._trigger_print(pending, message)
        return True

    async def cleanup_pending(self):
        """Jaksollinen siivoaminen."""
        now = asyncio.get_running_loop().time()

        # Kuvat (olemassa oleva)
        expired_prints = [mid for mid, p in self._pending_prints.items() if now > p.deadline]
        for mid in expired_prints:
            p = self._pending_prints.pop(mid)
            for fp in p.filepaths:
                remove_print_file(fp)
            if p.timer_task and not p.timer_task.done():
                p.timer_task.cancel()
            try:
                channel = self._bot.get_channel(p.channel_id)
                if channel is None:
                    channel = await self._bot.fetch_channel(p.channel_id)
                msg = await channel.fetch_message(mid)
                await msg.remove_reaction(p.emoji, self._bot.user)
            except Exception:
                pass
            log.info("⏰ Siivottu print (viesti %d).", mid)

        # URL:t (UUSI)
        expired_urls = [mid for mid, p in self._pending_urls.items() if now > p.deadline]
        for mid in expired_urls:
            p = self._pending_urls.pop(mid)
            if p.timer_task and not p.timer_task.done():
                p.timer_task.cancel()
            try:
                channel = self._bot.get_channel(p.channel_id)
                if channel is None:
                    channel = await self._bot.fetch_channel(p.channel_id)
                msg = await channel.fetch_message(mid)
                await self._remove_url_reactions(msg, p)
            except Exception:
                pass
            log.info("⏰ Siivottu URL (viesti %d).", mid)

    # ============================================================
    # VIDEO-KÄSITTELY (siirretty bot.py:stä)
    # ============================================================

    async def handle_youtube(self, message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: Optional[int] = None):
        from downloaders.youtube import download_video, YOUTUBE_QUALITY_STEPS
        from core.models import NonRetryableError

        await self._changelog_notify(message)

        s = Send(self._bot, self._task_queue, message, delete_original, forward_channel_id=forward_channel_id)
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

    async def handle_instagram(self, message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: Optional[int] = None):
        from downloaders.instagram import download_instagram
        from core.models import NonRetryableError

        await self._changelog_notify(message)

        await asyncio.sleep(1)
        log.info("📱 Instagram: %s", url[:80])

        s = Send(self._bot, self._task_queue, message, delete_original, forward_channel_id=forward_channel_id)
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

    async def handle_x(self, message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: Optional[int] = None,):
        from downloaders.x import download_x
        from core.models import NonRetryableError

        await self._changelog_notify(message)

        log.info("🐦 X: %s", url[:80])
        s = Send(self._bot, self._task_queue, message, delete_original, forward_channel_id=forward_channel_id)
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

    async def handle_tiktok(self, message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: Optional[int] = None):
        from downloaders.tiktok import download_tiktok
        from core.models import NonRetryableError

        await self._changelog_notify(message)

        log.info("🎵 TikTok: %s", url[:80])
        s = Send(self._bot, self._task_queue, message, delete_original, forward_channel_id=forward_channel_id)
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

    async def handle_twitch(self, message: discord.Message, url: str, delete_original: bool = False,forward_channel_id: Optional[int] = None):
        from downloaders.twitch import download_twitch
        from core.models import NonRetryableError

        await self._changelog_notify(message)

        log.info("🎮 Twitch: %s", url[:80])
        s = Send(self._bot, self._task_queue, message, delete_original, forward_channel_id=forward_channel_id)
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

    async def handle_soundcloud(self,
        message: discord.Message,
        url: str,
        delete_original: bool = False,
        forward_channel_id: Optional[int] = None,
        *,
        audio_only: bool = False,
    ):
        from core.models import NonRetryableError
        from downloaders.soundcloud import download_soundcloud
        from tools.soundcloud_video import make_soundcloud_video

        video_requested = not audio_only and config.ENABLE_SOUNDCLOUD_VIDEO
        log.info("SoundCloud [%d]: pyydetty muoto %s", message.id, "MP4" if video_requested else "MP3")
        await self._changelog_notify(message)
        sender = Send(self._bot, self._task_queue, message, delete_original, forward_channel_id=forward_channel_id)
        await sender.send_status("🎵 Ladataan SoundCloud-kappaletta...")

        try:
            result = await download_soundcloud(url)
        except NonRetryableError as error:
            await sender.send(error.user_facing, delete_after=REPLY_DELETE_AFTER)
            return

        if result is None:
            await sender.send("⚠️ SoundCloud-kappaleen lataus epäonnistui.", delete_after=REPLY_DELETE_AFTER)
            return

        video_path = None
        try:
            limit = _effective_file_limit(message)
            if video_requested:
                await sender._update_status("🎵 Tehdään kansikuvavideo...")
                video_path = await make_soundcloud_video(
                    result.filepath, result.artwork_url, result.title, result.uploader, limit,
                    avatar_url=str(message.author.display_avatar.with_size(1024).url),
                    message_id=message.id,
                )
                if video_path is None:
                    log.warning("SoundCloud [%d]: MP4 ei valmistunut lähetykseen, käytetään MP3:a", message.id)

            filepath = video_path or result.filepath
            filename = os.path.splitext(result.filename)[0] + ".mp4" if video_path else result.filename
            size = os.path.getsize(filepath)
            if size > limit:
                log.warning("SoundCloud [%d]: liite ylittää kokorajan (%d > %d tavua)", message.id, size, limit)
                await sender.send(
                    f"⚠️ Äänitiedosto ylittää Discordin kokorajan "
                    f"({size / 1024**2:.1f} / {limit / 1024**2:.1f} Mt).",
                    delete_after=REPLY_DELETE_AFTER,
                )
                return

            content = f"🎵 {result.format_message()}" if should_include_content(message.author.id) else ""
            file = discord.File(filepath, filename=filename)
            try:
                log.info(
                    "SoundCloud [%d]: %s Discord-lähetysjonoon (%d tavua, raja %d)",
                    message.id, "MP4" if video_path else "MP3", size, limit,
                )
                sent = await sender.send(content, file=file)
            finally:
                file.close()
            if sent is not None:
                log.info("SoundCloud [%d]: Discord hyväksyi liitteen (vastaus %d)", message.id, sent.id)
                await sender.delete_original()
            else:
                log.warning("SoundCloud [%d]: lähetysjono ei palauttanut vastausviestiä", message.id)
        except discord.HTTPException as error:
            log.exception(
                "SoundCloud [%d]: Discord-pyyntö epäonnistui (HTTP %d, koodi %d)",
                message.id, error.status, error.code,
            )
            await sender.send("⚠️ Äänitiedoston lähettäminen epäonnistui.", delete_after=REPLY_DELETE_AFTER)
        finally:
            if video_path:
                os.unlink(video_path)
            os.unlink(result.filepath)


    # ============================================================
    # URL-ROUTING (yhteinen)
    # ============================================================

    async def handle_aliexpress(self,
        message: discord.Message,
        url: str,
        delete_original: bool = False,
        forward_channel_id: Optional[int] = None,
    ) -> None:
        fields = await fetch_product_metadata(await self.get_session(), url)
        title = fields.get("og:title")
        image = fields.get("og:image", "")
        amount = fields.get("product:price:amount") or fields.get("price", "")
        currency = fields.get("product:price:currency") or fields.get("pricecurrency", "")
        sender = Send(self._bot, self._task_queue, message, delete_original, forward_channel_id=forward_channel_id)
        embed = None
        if title:
            embed = discord.Embed(title=title[:256], url=url)
            if image.startswith("//"):
                image = f"https:{image}"
            if image.startswith("https://") and len(image) <= 2048:
                embed.set_thumbnail(url=image)
            if re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", amount) and len(amount) <= 20:
                if re.fullmatch(r"[A-Z]{3}", currency):
                    embed.add_field(name="Sivulla näkyvä hinta", value=f"{amount} {currency}")
        if await sender.send(f"🛒 AliExpress · <{url}>", embed=embed):
            await sender.delete_original()


    async def route_message(self, message: discord.Message, names: list[str]):
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
            await handle_unohdaminut(message, bot=self._bot)
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
            mention.id == self._bot.user.id
            for mention in message.mentions
            if self._bot.user is not None
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
            relevant_urls.extend(product for url in urls if (product := aliexpress_product_url(url)))

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
                        await self.handle_youtube(message, url, delete_original=delete_original, forward_channel_id=fwd)
                    elif is_instagram(url):
                        await self.handle_instagram(message, url, delete_original=delete_original, forward_channel_id=fwd)
                    elif is_x(url):
                        await self.handle_x(message, url, delete_original=delete_original, forward_channel_id=fwd)
                    elif is_tiktok(url):
                        await self.handle_tiktok(message, url, delete_original=delete_original, forward_channel_id=fwd)
                    elif is_twitch(url):
                        await self.handle_twitch(message, url, delete_original=delete_original, forward_channel_id=fwd)
                    elif is_soundcloud(url):
                        await self.handle_soundcloud(message, url, delete_original=delete_original, forward_channel_id=fwd)
                    elif aliexpress_product_url(url):
                        await self.handle_aliexpress(message, url, delete_original=delete_original, forward_channel_id=fwd)
                else:
                    # Kanava, ei mentionia → reaktiokysely
                    await self._start_pending_url(message, relevant_urls[0], names, delete_original=delete_original)
                    return True

        # --- Kuvat (liitteet) ---
        if config.ENABLE_IMAGE_PRINTING:
            image_attachments = [
                att for att in message.attachments
                if att.filename.lower().endswith(IMAGE_EXTENSIONS)
            ]
            if image_attachments:
                await self.handle_pending_image(message, image_attachments, names)
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
                clean_content, await self.get_session(), on_progress=_progress
            )

            # Poista tilaviesti
            if status_msg is not None:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

            if link_images:
                await self.handle_pending_image_links(message, link_images, names)
                return True

        return False

    async def _send_and_cleanup(self, message: discord.Message,delete_original: bool,content: str,file: discord.File | None = None,):
        """Lähetä viesti + poista alkuperäinen jos pyydetty."""
        s = Send(self._bot, self._task_queue, message, delete_original)
        if await s.send(content, file=file) is not None:
            await s.delete_original()

    # ============================================================
    # PENDING URL (reaktio-kysely videotulostukseen)
    # ============================================================

    async def _remove_url_reactions(self, message: discord.Message, pending: PendingURL):
        for emoji in pending.emojis:
            try:
                await message.remove_reaction(emoji, self._bot.user)
            except discord.HTTPException:
                log.debug("URL-reaktion %s poisto epäonnistui", emoji)


    async def _start_pending_url(self,
        message: discord.Message, url: str, names: list[str], delete_original: bool = False,
    ):
        from downloaders.soundcloud import is_soundcloud

        emojis = (config.URL_REACTION_EMOJI,)
        if config.ENABLE_SOUNDCLOUD_VIDEO and is_soundcloud(url):
            emojis += (SOUNDCLOUD_MP3_EMOJI,)

        for emoji in emojis:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException as e:
                log.warning("PendingURL: reaktion lisäys epäonnistui: %s", e)

        pending = PendingURL(
            message_id=message.id,
            channel_id=message.channel.id,
            url=url,
            names=names,
            deadline=asyncio.get_running_loop().time() + config.PRINT_TIMEOUT,
            emojis=emojis,
            delete_original=delete_original,
        )
        self._pending_urls[message.id] = pending
        pending.timer_task = asyncio.create_task(self._pending_url_timeout(pending))
        log.info("⏳ Odotetaan URL-reaktiota: %s (timeout=%ds)", url[:60], config.PRINT_TIMEOUT)

    async def _pending_url_timeout(self, pending: PendingURL):
        try:
            await asyncio.sleep(config.PRINT_TIMEOUT)
        except asyncio.CancelledError:
            return

        if self._pending_urls.get(pending.message_id) is not pending:
            return

        self._pending_urls.pop(pending.message_id, None)
        if self._bot.user is None:
            return
        try:
            channel = self._bot.get_channel(pending.channel_id)
            if channel is None:
                channel = await self._bot.fetch_channel(pending.channel_id)
            msg = await channel.fetch_message(pending.message_id)
            await self._remove_url_reactions(msg, pending)
            log.info("⏰ PendingURL timeout (viesti %d).", pending.message_id)
        except Exception:
            pass

    async def _trigger_url(self, pending: PendingURL, message: discord.Message, *, audio_only: bool):
        """Kun reaktio saatu → käsittele URL."""

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
                await self.handle_youtube(message, url, delete_original=del_orig)
            elif is_instagram(url):
                await self.handle_instagram(message, url, delete_original=del_orig)
            elif is_x(url):
                await self.handle_x(message, url, delete_original=del_orig)
            elif is_tiktok(url):
                await self.handle_tiktok(message, url, delete_original=del_orig)
            elif is_twitch(url):
                await self.handle_twitch(message, url, delete_original=del_orig)
            elif is_soundcloud(url):
                await self.handle_soundcloud(message, url, delete_original=del_orig, audio_only=audio_only)
            elif aliexpress_product_url(url):
                await self.handle_aliexpress(message, url, delete_original=del_orig)
            else:
                await message.reply("⚠️ Tuntuma URL ei ole tunnistettu.", delete_after=REPLY_DELETE_AFTER)
        except Exception as e:
            log.error("PendingURL: käsittely epäonnistui: %s", e)
            try:
                await message.reply("⚠️ Käsittely epäonnistui.", delete_after=REPLY_DELETE_AFTER)
            except Exception:
                pass

    async def check_url_reaction(self, reaction: discord.RawReactionActionEvent) -> bool:
        """Tarkista onko reaktio pending-URL-reaktio."""
        if self._bot.user is None or reaction.user_id == self._bot.user.id:
            return False

        pending = self._pending_urls.get(reaction.message_id)
        if pending is None:
            return False

        if reaction.channel_id != pending.channel_id:
            return False

        emoji_str = str(reaction.emoji).rstrip('\ufe0f')
        if emoji_str not in pending.emojis:
            return False

        self._pending_urls.pop(reaction.message_id)
        if pending.timer_task:
            pending.timer_task.cancel()

        log.info("URL-reaktio saatu: viesti=%d, emoji=%s", reaction.message_id, emoji_str)

        try:
            channel = self._bot.get_channel(pending.channel_id)
            if channel is None:
                channel = await self._bot.fetch_channel(pending.channel_id)
            message = await channel.fetch_message(reaction.message_id)
        except Exception as e:
            log.error("PendingURL: viestin haku epäonnistui: %s", e)
            return True

        if SOUNDCLOUD_MP3_EMOJI in pending.emojis:
            await self._remove_url_reactions(message, pending)
        await self._trigger_url(pending, message, audio_only=emoji_str == SOUNDCLOUD_MP3_EMOJI)
        return True


def _make_threadsafe_progress(s: "Send") -> Callable[[str], None]:
    """Luo callbackin joka päivittää tilaviestin thread-turvallisesti."""
    loop = asyncio.get_running_loop()

    def _callback(text: str) -> None:
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(s._update_status(text)))

    return _callback
