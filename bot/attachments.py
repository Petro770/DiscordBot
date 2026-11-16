"""Discord integration for indexing and looking up channel attachments."""

import asyncio
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryFile
from time import monotonic

import aiohttp
import discord
from discord import app_commands

from core.attachment_index import AttachmentIndex, Fingerprint, fingerprint
from core.logging import log

HISTORY_BATCH_SIZE = 1000
HISTORY_BATCH_SECONDS = 120


class ChannelAttachments:
    def __init__(self, bot: discord.Client, channels: frozenset[int]):
        self.channels = channels
        root = Path(__file__).resolve().parent.parent
        self.index = AttachmentIndex(root / "Channels" / "attachments.sqlite3")
        self._downloads = asyncio.Semaphore(1)
        self._scanning: set[int] = set()
        self._synced = False
        self.tree = app_commands.CommandTree(bot)
        self.tree.command(name="indeksoi", description="Indeksoi erä kanavan vanhoja liitteitä.")(self.scan)
        self.tree.command(name="duplikaatit", description="Etsi tiedoston kopioita tältä kanavalta.")(self.search)

    async def setup(self) -> None:
        if self._synced:
            return
        await asyncio.to_thread(self.index.initialize)
        await self.tree.sync()
        self._synced = True

    async def _fingerprint(self, attachment: discord.Attachment) -> Fingerprint:
        digest = sha256()
        with TemporaryFile() as file:
            timeout = aiohttp.ClientTimeout(total=90)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(attachment.url) as response:
                    response.raise_for_status()
                    async for chunk in response.content.iter_chunked(128 * 1024):
                        digest.update(chunk)
                        file.write(chunk)
            file.seek(0)
            # Keep the temporary file open until the worker has finished
            # decoding, even if Discord cancels the caller.
            task = asyncio.create_task(asyncio.to_thread(fingerprint, file, digest.digest()))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def index_message(self, message: discord.Message) -> tuple[int, int]:
        added = unavailable = 0
        for attachment in message.attachments:
            async with self._downloads:
                channel_id = message.channel.id
                if await asyncio.to_thread(self.index.contains, channel_id, attachment.id):
                    continue
                try:
                    image = await self._fingerprint(attachment)
                except aiohttp.ClientResponseError as exc:
                    if exc.status not in (404, 410):
                        raise
                    unavailable += 1
                    continue
                added += await asyncio.to_thread(
                    self.index.save, channel_id, message.id, attachment.id, attachment.filename, image
                )
        return added, unavailable

    async def _check(self, interaction: discord.Interaction, *, scan: bool = False) -> bool:
        if interaction.guild_id is None or interaction.channel_id not in self.channels:
            error = "Liiteindeksi on käytössä vain määritetyillä palvelinkanavilla."
        elif scan and not interaction.permissions.manage_messages:
            error = "Historian indeksointi vaatii Viestien hallinta -oikeuden."
        elif not interaction.permissions.read_message_history:
            error = "Komento vaatii viestihistorian lukuoikeuden."
        else:
            return True
        await interaction.response.send_message(error, ephemeral=True)
        return False

    @app_commands.guild_only()
    async def scan(self, interaction: discord.Interaction) -> None:
        if not await self._check(interaction, scan=True):
            return
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
            await interaction.response.send_message("Tällä kanavalla ei ole luettavaa viestihistoriaa.", ephemeral=True)
            return
        if channel.id in self._scanning:
            await interaction.response.send_message("Kanavan indeksointi on jo käynnissä.", ephemeral=True)
            return

        self._scanning.add(channel.id)
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            position = await asyncio.to_thread(self.index.history_position, channel.id)
            after = discord.Object(id=position) if position else None
            messages = added = unavailable = 0
            deadline = monotonic() + HISTORY_BATCH_SECONDS
            async for message in channel.history(limit=HISTORY_BATCH_SIZE, after=after, oldest_first=True):
                if monotonic() >= deadline:
                    break
                new, missing = await self.index_message(message)
                await asyncio.to_thread(self.index.advance_history, channel.id, message.id)
                messages += 1
                added += new
                unavailable += missing
            else:
                if messages < HISTORY_BATCH_SIZE:
                    await interaction.followup.send(
                        f"Historia ajan tasalla. Käyty läpi {messages} viestiä, "
                        f"lisätty {added} liitettä. Saatavilla ei ollut {unavailable} liitettä.",
                        ephemeral=True,
                    )
                    return

            await interaction.followup.send(
                f"Käyty läpi {messages} viestiä, lisätty {added} liitettä. "
                f"Saatavilla ei ollut {unavailable} liitettä. Jatka komennolla /indeksoi.",
                ephemeral=True,
            )
        except Exception:
            log.exception("Kanavan %s liitehistorian indeksointi keskeytyi", channel.id)
            await interaction.followup.send(
                "Indeksointi keskeytyi. Yritä jatkaa komennolla /indeksoi.", ephemeral=True
            )
        finally:
            self._scanning.remove(channel.id)

    @app_commands.guild_only()
    @app_commands.describe(tiedosto="Tiedosto, jonka kopioita etsitään")
    async def search(self, interaction: discord.Interaction, tiedosto: discord.Attachment) -> None:
        if not await self._check(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with self._downloads:
                image = await self._fingerprint(tiedosto)
            matches = await asyncio.to_thread(self.index.find, interaction.channel_id, image)
        except Exception:
            log.exception("Kanavan %s duplikaattihaku epäonnistui", interaction.channel_id)
            await interaction.followup.send("Haku epäonnistui. Yritä uudelleen.", ephemeral=True)
            return

        lines = []
        for match in matches:
            status = "Sama tiedosto" if match.exact else f"Mahdollinen kopio (pHash {match.bit_distance}/64)"
            url = f"https://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}/{match.message_id}"
            lines.append(f"• [{status}]({url})")
        await interaction.followup.send(
            "\n".join(lines) or "Kanavan indeksistä ei löytynyt osumia.",
            ephemeral=True, suppress_embeds=True,
        )
