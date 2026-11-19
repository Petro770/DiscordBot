"""Discord integration for indexing and looking up channel attachments."""

import asyncio
from collections import Counter
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryFile
from time import monotonic

import aiohttp
import discord
from discord import app_commands

import config
from core.attachment_index import AttachmentIndex, Fingerprint, Match, RepostStats, fingerprint
from core.logging import log
from user.settings import DEFAULTS, WARNING_MODE_LABELS, get_user_entry, set_setting
from user.tracker import register_message

HISTORY_BATCH_SIZE = 1000
HISTORY_BATCH_SECONDS = 120


class ScanContinuation(discord.ui.View):
    def __init__(self, attachments: "ChannelAttachments"):
        super().__init__(timeout=600)
        self.attachments = attachments

    @discord.ui.button(label="Jatka indeksointia", style=discord.ButtonStyle.primary)
    async def continue_scan(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.attachments._scan(interaction, continuation=self)


WARNING_TYPES = {
    "repost_warning": "Repostaus",
    "image_duplicate_warning": "Kuvakopio",
}


class WarningPreferenceButton(discord.ui.Button):
    def __init__(self, user_id: int, key: str, mode: str, row: int):
        label = {"channel": "Kanava", "dm": "DM", "off": "Pois"}[mode]
        super().__init__(label=f"{WARNING_TYPES[key]} · {label}", row=row)
        self.user_id = user_id
        self.key = key
        self.mode = mode

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Vain varoituksen saanut käyttäjä voi valita asetuksen.", ephemeral=True
            )
            return

        settings = get_user_entry(self.user_id).get("settings", {})
        if self.key in settings:
            await interaction.response.send_message(
                "Olet jo valinnut asetuksen. Muutosohje löytyy komennolla `OHJE ASETUKSET`.",
                ephemeral=True,
            )
            return

        set_setting(self.user_id, self.key, self.mode)
        if get_user_entry(self.user_id).get("settings", {}).get(self.key) != self.mode:
            await interaction.response.send_message(
                "Asetuksen tallennus epäonnistui. Kokeile uudelleen.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ {WARNING_TYPES[self.key]} · **{WARNING_MODE_LABELS[self.mode]}**",
            ephemeral=True,
        )


class WarningPreferences(discord.ui.View):
    def __init__(self, user_id: int, keys: list[str]):
        super().__init__(timeout=600)
        self.message: discord.Message | None = None
        for row, key in enumerate(keys):
            for mode in WARNING_MODE_LABELS:
                self.add_item(WarningPreferenceButton(user_id, key, mode, row))

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                log.debug("Varoituksen %s asetusvalintaa ei voitu poistaa", self.message.id)


class ChannelAttachments:
    def __init__(self, bot: discord.Client, channels: frozenset[int]):
        self.channels = channels
        root = Path(__file__).resolve().parent.parent
        self.index = AttachmentIndex(root / "Channels" / "attachments.sqlite3")
        self._downloads = asyncio.Semaphore(1)
        self._scanning: set[int] = set()
        self._synced = False
        self.tree = app_commands.CommandTree(bot)
        self.tree.command(name="repostaajat", description="Näytä tämän kanavan eniten liitteitä uudelleen lähettäneet.")(self.reposters)
        self.tree.command(name="indeksoi", description="Indeksoi erä kanavan vanhoja liitteitä.")(self.scan)
        self.tree.command(name="duplikaatit", description="Etsi tiedoston kopioita tältä kanavalta.")(self.search)

    async def setup(self) -> None:
        if self._synced:
            return
        log.info("Liiteindeksi: alustetaan SQLite, kanavat=%s, kuvavaroituksen raja=%g %%",
                 sorted(self.channels), config.REPOST_WARNING_THRESHOLD)
        await asyncio.to_thread(self.index.initialize)
        log.info("Liiteindeksi: SQLite valmis, synkronoidaan Discord-komennot")
        await self.tree.sync()
        self._synced = True
        log.info("Liiteindeksi: Discord-komennot synkronoitu")

    async def _fingerprint(self, attachment: discord.Attachment) -> Fingerprint:
        started = monotonic()
        log.info("Liite %s: lataus alkaa, ilmoitettu koko=%s B", attachment.id, attachment.size)
        digest = sha256()
        with TemporaryFile() as file:
            timeout = aiohttp.ClientTimeout(total=90)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(attachment.url) as response:
                    response.raise_for_status()
                    async for chunk in response.content.iter_chunked(128 * 1024):
                        digest.update(chunk)
                        file.write(chunk)
            log.info("Liite %s: ladattu %s B (%.2f s), lasketaan tunnisteet",
                     attachment.id, file.tell(), monotonic() - started)
            file.seek(0)
            # Keep the temporary file open until the worker has finished
            # decoding, even if Discord cancels the caller.
            task = asyncio.create_task(asyncio.to_thread(fingerprint, file, digest.digest()))
            try:
                image = await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
            log.info("Liite %s: SHA-256 valmis, pHash ja värikartta=%s (%.2f s yhteensä)",
                     attachment.id, "valmiit" if image.phash is not None else "ei laskettu",
                     monotonic() - started)
            return image

    async def index_message(
        self, message: discord.Message, *, warn_duplicates: bool = False
    ) -> tuple[int, int]:
        added = unavailable = 0
        if message.attachments:
            log.info("Liiteindeksi: kanava=%s viesti=%s, liitteitä=%s, automaattinen haku=%s",
                     message.channel.id, message.id, len(message.attachments), warn_duplicates)
            await asyncio.to_thread(
                self.index.save_message_author, message.channel.id, message.id,
                message.author.id, message.author.bot,
            )
        exact: dict[bytes, RepostStats] = {}
        matches: dict[int, Match] = {}
        for attachment in message.attachments:
            log.debug("Liite %s: odottaa käsittelyvuoroa, viesti=%s", attachment.id, message.id)
            async with self._downloads:
                channel_id = message.channel.id
                log.info("Liite %s: tarkistetaan tietokannasta, viesti=%s", attachment.id, message.id)
                if await asyncio.to_thread(self.index.contains, channel_id, attachment.id):
                    log.info("Liite %s: löytyi indeksistä, ohitetaan", attachment.id)
                    continue
                try:
                    image = await self._fingerprint(attachment)
                except aiohttp.ClientResponseError as exc:
                    log.warning("Liite %s: lataus epäonnistui, HTTP %s", attachment.id, exc.status)
                    if exc.status not in (404, 410):
                        raise
                    unavailable += 1
                    continue
                log.info("Liite %s: tallennetaan tietokantaan", attachment.id)
                saved = await asyncio.to_thread(
                    self.index.save, channel_id, message.id, attachment.id, attachment.filename, image
                )
                added += saved
                log.info("Liite %s: %s", attachment.id, "tallennettu" if saved else "oli jo indeksissä")
                if saved and warn_duplicates:
                    log.info("Liite %s: etsitään aiempaa osumaa kanavalta %s", attachment.id, channel_id)
                    stats = await asyncio.to_thread(
                        self.index.exact_repost_stats, channel_id, message.id, message.author.id, image.sha256
                    )
                    if stats is not None:
                        exact[image.sha256] = stats
                        log.info("Liite %s: täsmäosuma, ensimmäinen viesti=%s, omia lähetyksiä=%s, "
                                 "kanavalla=%s, tuntemattomia lähettäjiä=%s",
                                 attachment.id, stats.first_message_id, stats.author_count,
                                 stats.channel_count, stats.unknown_authors)
                        continue
                    previous = await asyncio.to_thread(
                        self.index.find, channel_id, image, before_message_id=message.id, limit=1,
                        visual_threshold=config.REPOST_WARNING_THRESHOLD,
                    )
                    if previous:
                        match = previous[0]
                        log.info("Liite %s: aiempi viesti=%s, täsmäosuma=%s, pisteet=%.2f%%, "
                                 "pHash-etäisyys=%s, väriero=%.2f",
                                 attachment.id, match.message_id, match.exact, match.similarity,
                                 match.bit_distance, match.color_distance)
                        matches[match.message_id] = match
                    else:
                        log.info("Liite %s: ei aiempia osumia", attachment.id)
        if exact or matches:
            settings = get_user_entry(message.author.id).get("settings", {})
            warning_keys = []
            if exact:
                warning_keys.append("repost_warning")
            if matches:
                warning_keys.append("image_duplicate_warning")
            modes = {key: settings.get(key, DEFAULTS[key]) for key in warning_keys}
            repost_mode = modes.get("repost_warning")
            image_mode = modes.get("image_duplicate_warning")
            for mode in ("channel", "dm"):
                if mode == repost_mode or mode == image_mode:
                    await self._warn_duplicates(
                        message,
                        exact if mode == repost_mode else {},
                        list(matches.values()) if mode == image_mode else [],
                        private=mode == "dm",
                        unset_keys=[key for key in warning_keys if key not in settings] if mode == "channel" else [],
                    )
        if message.attachments:
            log.info("Liiteindeksi: viesti=%s valmis, lisätty=%s, puuttui=%s, osumaviestejä=%s",
                     message.id, added, unavailable, len(exact) + len(matches))
        return added, unavailable

    async def _warn_duplicates(
        self, message: discord.Message, exact: dict[bytes, RepostStats], similar: list[Match],
        *, private: bool, unset_keys: list[str],
    ) -> None:
        base_url = f"https://discord.com/channels/{message.guild.id}/{message.channel.id}"
        heading = "⚠️ **Repostausosuma**"
        global_rank = None
        content_ranks = {}
        if exact:
            try:
                global_rank, content_ranks = await asyncio.to_thread(
                    self.index.repost_ranks, message.author.id, list(exact)
                )
                log.info("Liiteindeksi: repostisijoitukset laskettu, viesti=%s, "
                         "globaali=%s, sisältösijoituksia=%d",
                         message.id, global_rank, len(content_ranks))
            except Exception:
                log.exception("Liiteindeksi: repostisijoitusten haku epäonnistui, viesti=%s", message.id)
        if global_rank is not None:
            heading += f" · Globaali sija **#{global_rank}**"

        lines = []
        for digest, stats in exact.items():
            rank = content_ranks.get(digest)
            own_count = f"ainakin {stats.author_count}" if stats.unknown_authors else str(stats.author_count)
            lines.append(
                f"• **100 % SHA-256** · Omat **{own_count}** / kanava **{stats.channel_count}** · "
                f"[Ensimmäinen osuma]({base_url}/{stats.first_message_id})"
                + (f" · Sisältösija **#{rank}**" if rank is not None else "")
            )
        for match in similar:
            score = f"{match.similarity:.1f}".replace(".", ",")
            color_difference = f"{match.color_distance:.1f}".replace(".", ",")
            lines.append(
                f"• **Mahdollinen kuvakopio · {score} %** · "
                f"pHash-ero {match.bit_distance}/64 · Väriero {color_difference}/255 · "
                f"[Aiempi osuma]({base_url}/{match.message_id})"
            )
        destination = "yksityisviestinä" if private else "kanavalle"
        target = message.author if private else message.channel
        send_options = {}
        if private:
            heading += f" · [Viestisi]({message.jump_url})"
        else:
            send_options["reference"] = message.to_reference(fail_if_not_exists=False)

        log.info("Liiteindeksi: lähetetään varoitus %s, viesti=%s", destination, message.id)
        try:
            for offset in range(0, len(lines), 5):
                content = "\n".join([heading, *lines[offset:offset + 5]])
                view = None
                if offset == 0 and unset_keys:
                    settings = get_user_entry(message.author.id).get("settings", {})
                    keys = [key for key in unset_keys if key not in settings]
                    if keys:
                        content += "\n\nValitse, miten haluat saada seuraavat varoitukset."
                        view = WarningPreferences(message.author.id, keys)
                warning = await target.send(
                    content,
                    view=view,
                    allowed_mentions=discord.AllowedMentions.none(),
                    suppress_embeds=True,
                    **send_options,
                )
                if view is not None:
                    view.message = warning
                if private:
                    register_message(warning)
        except discord.HTTPException:
            log.exception("Viestin %s duplikaattivaroituksen lähetys %s epäonnistui", message.id, destination)
        else:
            log.info("Liiteindeksi: duplikaattivaroitus lähetetty %s, viesti=%s", destination, message.id)

    async def _check(self, interaction: discord.Interaction, *, scan: bool = False) -> bool:
        if interaction.guild_id is None or interaction.channel_id not in self.channels:
            error = "Liiteindeksi on käytössä vain määritetyillä palvelinkanavilla."
        elif scan and not interaction.permissions.manage_messages:
            error = "Historian indeksointi vaatii Viestien hallinta -oikeuden."
        elif not interaction.permissions.read_message_history:
            error = "Komento vaatii viestihistorian lukuoikeuden."
        else:
            return True
        log.info("Liiteindeksi: komento hylätty kanavalla %s. %s", interaction.channel_id, error)
        await interaction.response.send_message(error, ephemeral=True)
        return False

    @app_commands.guild_only()
    async def scan(self, interaction: discord.Interaction) -> None:
        await self._scan(interaction)

    async def _scan(
        self, interaction: discord.Interaction, *, continuation: ScanContinuation | None = None
    ) -> None:
        if not await self._check(interaction, scan=True):
            return
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel, discord.StageChannel)):
            await interaction.response.send_message("Tällä kanavalla ei ole luettavaa viestihistoriaa.", ephemeral=True)
            return
        if channel.id in self._scanning:
            log.info("/indeksoi: kanava=%s, indeksointi on jo käynnissä", channel.id)
            await interaction.response.send_message("Kanavan indeksointi on jo käynnissä.", ephemeral=True)
            return

        self._scanning.add(channel.id)
        log.info("/indeksoi: käynnistyy kanavalla %s", channel.id)
        try:
            if continuation is None:
                await interaction.response.defer(ephemeral=True, thinking=True)
            else:
                await interaction.response.edit_message(content="Indeksoidaan seuraavaa erää…", view=None)
                continuation.stop()
                log.info("/indeksoi: jatkettiin painikkeesta, kanava=%s", channel.id)
            position = await asyncio.to_thread(self.index.history_position, channel.id)
            after = discord.Object(id=position) if position else None
            log.info("/indeksoi: kanava=%s, aiempi historiakohta=%s", channel.id, position)
            messages = added = unavailable = 0
            deadline = monotonic() + HISTORY_BATCH_SECONDS
            has_more = True
            async for message in channel.history(
                limit=HISTORY_BATCH_SIZE + 1, after=after, oldest_first=True
            ):
                if messages == HISTORY_BATCH_SIZE or monotonic() >= deadline:
                    log.info("/indeksoi: kanava=%s, erän raja=%s", channel.id,
                             "viestimäärä" if messages == HISTORY_BATCH_SIZE else "aika")
                    break
                new, missing = await self.index_message(message)
                await asyncio.to_thread(self.index.advance_history, channel.id, message.id)
                log.debug("/indeksoi: historiakohta tallennettu, kanava=%s viesti=%s", channel.id, message.id)
                messages += 1
                added += new
                unavailable += missing
            else:
                if messages == 0:
                    log.info("/indeksoi: kanava=%s, ei uusia viestejä", channel.id)
                    await interaction.edit_original_response(
                        content="Ei uusia viestejä indeksoitavaksi. Kanavan historia on ajan tasalla.",
                        view=None,
                    )
                    return
                has_more = False

            log.info("/indeksoi: kanava=%s, tarkistettu=%s, lisätty=%s, puuttui=%s",
                     channel.id, messages, added, unavailable)
            summary = f"Tarkistettu {messages} viestiä. Lisätty {added} uutta liitettä."
            if unavailable:
                summary += f" Saatavilla ei ollut {unavailable} liitettä."
            completion = "Historiaa on vielä jäljellä." if has_more else "Kanavan historia on ajan tasalla."
            await interaction.edit_original_response(
                content=f"{completion} {summary}",
                view=ScanContinuation(self) if has_more else None,
            )
        except Exception:
            log.exception("Kanavan %s liitehistorian indeksointi keskeytyi", channel.id)
            if interaction.response.is_done():
                await interaction.edit_original_response(
                    content="Indeksointi keskeytyi. Voit yrittää jatkaa tallennetusta kohdasta.",
                    view=ScanContinuation(self),
                )
        finally:
            self._scanning.remove(channel.id)

    @app_commands.guild_only()
    @app_commands.describe(tiedosto="Tiedosto, jonka kopioita etsitään")
    async def search(self, interaction: discord.Interaction, tiedosto: discord.Attachment) -> None:
        if not await self._check(interaction):
            return
        log.info("/duplikaatit: käynnistyy, kanava=%s liite=%s", interaction.channel_id, tiedosto.id)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with self._downloads:
                image = await self._fingerprint(tiedosto)
            log.info("/duplikaatit: haetaan indeksistä, kanava=%s liite=%s", interaction.channel_id, tiedosto.id)
            matches = await asyncio.to_thread(self.index.find, interaction.channel_id, image)
        except Exception:
            log.exception("Kanavan %s duplikaattihaku epäonnistui", interaction.channel_id)
            await interaction.followup.send("Haku epäonnistui. Yritä uudelleen.", ephemeral=True)
            return

        log.info("/duplikaatit: kanava=%s liite=%s, täsmäosumia=%s, mahdollisia=%s",
                 interaction.channel_id, tiedosto.id, sum(match.exact for match in matches),
                 sum(not match.exact for match in matches))
        lines = []
        for match in matches:
            status = "Sama tiedosto" if match.exact else f"Mahdollinen kuvakopio ({match.similarity:.1f} %)"
            url = f"https://discord.com/channels/{interaction.guild_id}/{interaction.channel_id}/{match.message_id}"
            lines.append(f"• [{status}]({url})")
        await interaction.followup.send(
            "\n".join(lines) or "Kanavan indeksistä ei löytynyt osumia.",
            ephemeral=True, suppress_embeds=True,
        )

    @app_commands.guild_only()
    async def reposters(self, interaction: discord.Interaction) -> None:
        if not await self._check(interaction):
            return
        channel = interaction.channel
        if not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message(
                "Tältä kanavalta ei voi hakea viestejä.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        started = monotonic()
        log.info("/repostaajat: ryhmitellään SQLite-tulokset, kanava=%s", channel.id)
        missing = resolved = 0
        partial = False
        try:
            known, unknown = await asyncio.to_thread(self.index.repost_summary, channel.id)
            counts = Counter(known)
            log.info(
                "/repostaajat: SQLite valmis (%.2f s), kanava=%s, "
                "ryhmiteltyjä viestejä=%d, Discordista haettavia lähettäjiä=%d",
                monotonic() - started, channel.id, sum(counts.values()), len(unknown),
            )

            async def fetch_author(message_id: int):
                try:
                    message = await channel.fetch_message(message_id)
                except discord.NotFound:
                    return None
                await asyncio.to_thread(
                    self.index.save_message_author, channel.id, message_id,
                    message.author.id, message.author.bot,
                )
                return message.author

            deadline = monotonic() + 600
            batch_size = 5
            for offset in range(0, len(unknown), batch_size):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    partial = True
                    break
                batch = unknown[offset:offset + batch_size]
                log.info("/repostaajat: kanava=%s, haetaan Discordista lähettäjiä %d–%d/%d",
                         channel.id, offset + 1, offset + len(batch), len(unknown))
                results = await asyncio.gather(
                    *(asyncio.wait_for(fetch_author(message_id), timeout=remaining) for message_id in batch),
                    return_exceptions=True,
                )
                for author in results:
                    if isinstance(author, asyncio.TimeoutError):
                        partial = True
                    elif isinstance(author, BaseException):
                        raise author
                    elif author is None:
                        missing += 1
                    else:
                        resolved += 1
                        if not author.bot:
                            counts[author.id] += 1
                if partial:
                    break
        except Exception:
            log.exception("/repostaajat: haku epäonnistui, kanava=%s", channel.id)
            await interaction.edit_original_response(content="Repostaajalistan haku epäonnistui.")
            return

        log.info("/repostaajat: valmis (%.2f s), kanava=%s, käyttäjiä=%s, "
                 "selvitettyjä tekijöitä=%s, puuttuvia viestejä=%s, osittainen=%s",
                 monotonic() - started, channel.id, len(counts), resolved, missing, partial)
        top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        lines = ["**Kanavan repostaajat · Top 5**"]
        if top:
            try:
                examples = await asyncio.to_thread(
                    self.index.repost_examples, channel.id, [author_id for author_id, _ in top]
                )
                log.info("/repostaajat: ensimmäisiä osumia=%d, kanava=%s",
                         sum(len(pairs) for pairs in examples.values()), channel.id)
            except Exception:
                log.exception("/repostaajat: esimerkkien haku epäonnistui, kanava=%s", channel.id)
                examples = {}
                lines.append("Ensimmäisten osumien haku epäonnistui.")

            base_url = f"https://discord.com/channels/{interaction.guild_id}/{channel.id}"
            for rank, (author_id, count) in enumerate(top, start=1):
                lines.append(f"\n**{rank}.**, **{count} kpl**, <@{author_id}>")
                lines.extend(
                    f"  • **{repost_count} kpl** · [Ensimmäinen osuma]({base_url}/{original_id})"
                    for original_id, repost_count in examples.get(author_id, ())
                )
        else:
            lines.append("Indeksistä ei löytynyt listattavia uudelleenlähetyksiä.")
        if missing:
            lines.append(f"Tekijää ei saatu selville {missing} poistetusta viestistä.")
        if partial:
            lines.append("Lista on osittainen. Aja /repostaajat uudelleen jatkaaksesi tekijöiden hakua.")
        await interaction.edit_original_response(
            content="\n".join(lines), allowed_mentions=discord.AllowedMentions.none()
        )
