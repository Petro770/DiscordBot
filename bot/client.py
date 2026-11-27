"""Discord-bot: eventit ja kanavalogiikka."""
import asyncio
import discord

import config
from config import TARGET_CHANNEL_ID
from printer.queue import PrintQueue
from bot.handlers import MessageHandlers
from bot.attachments import ChannelAttachments
from bot.ollama import OllamaReplies
from core.logging import log
from core.queue import TaskQueue
from user.tracker import start_cleanup_task, track_unscheduled_message


class BotClient(discord.Client):
    async def close(self):
        # Discord can call close more than once during shutdown.
        cleanup = getattr(self, "_runtime_shutdown", None)
        if cleanup is None:
            cleanup = self._runtime_shutdown = asyncio.create_task(self._close_runtime())
        await asyncio.shield(cleanup)

    async def _close_runtime(self):
        await super().close()
        tasks = [task for name in ("_worker_task", "_cleanup_task", "_msg_cleanup_task")
                 if (task := getattr(self, name, None)) is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if hasattr(self, "_task_queue"):
            await self._task_queue.stop()
            await self._message_handlers.close()


def create_bot() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.reactions = True
    return BotClient(intents=intents)


def register_events(bot: discord.Client, print_queue: PrintQueue):
    task_queue = bot._task_queue = TaskQueue()
    handlers = bot._message_handlers = MessageHandlers(bot, print_queue, task_queue)
    attachments = ChannelAttachments(bot, config.ATTACHMENT_INDEX_CHANNEL_IDS)

    ollama = OllamaReplies() if config.ENABLE_OLLAMA else None
    log.info(
        "Ollama: %s | OLLAMA_CHANNEL_IDS=%s (%s) | palvelimia=%s | mallit=%s | poissulut=%s",
        "käytössä" if ollama else "pois käytöstä (ENABLE_OLLAMA)",
        sorted(config.OLLAMA_CHANNEL_IDS),
        config.OLLAMA_CHANNEL_SOURCE,
        len(config.OLLAMA_HOSTS),
        config.OLLAMA_MODELS or "automaattinen haku",
        sorted(config.OLLAMA_EXCLUDED_MODELS),
    )

    @attachments.tree.command(name="ai-tyyli", description="Näytä tämän keskustelun AI:n istuntokohtaiset tyyliohjeet.")
    async def show_ai_style(interaction: discord.Interaction):
        if ollama is None:
            content = "Ollama-vastaukset ovat pois käytöstä."
        else:
            style = ollama.session_style(interaction.channel_id)
            if style:
                bullets = "\n".join(f"• {discord.utils.escape_markdown(line)}" for line in style.splitlines())
                content = f"**Tämän keskustelun AI-tyyliohjeet**\n{bullets}"
            elif interaction.guild_id is not None and not isinstance(interaction.channel, discord.Thread):
                content = "Tyyliohjeet ovat vastausketjukohtaisia. Komento näyttää tyylin Discord-ketjussa tai yksityisviestissä."
            else:
                content = "Tässä keskustelussa ei ole aktiivisia AI-tyylilisäyksiä."
        await interaction.response.send_message(content, allowed_mentions=discord.AllowedMentions.none())

    async def index_attachments(message: discord.Message):
        try:
            _, unavailable = await attachments.index_message(message, warn_duplicates=not message.author.bot)
            if unavailable:
                log.warning("Viestin %s liitteistä %s ei ollut saatavilla", message.id, unavailable)
        except Exception:
            log.exception("Viestin %s liiteindeksointi epäonnistui", message.id)

    async def route_incoming(message: discord.Message):
        if message.author.bot:
            return

        if isinstance(message.channel, discord.DMChannel):
            await handlers.route_message(message, [message.author.name])
            return

        if message.channel.id != TARGET_CHANNEL_ID:
            return

        names = [message.author.name]
        if message.guild:
            gm = message.guild.get_member(message.author.id)
            if gm and gm.display_name != message.author.name:
                names.append(gm.display_name)

        await handlers.route_message(message, names)

    @bot.event
    async def on_ready():
        log.info("Discord-botti yhdistetty: %s", bot.user)

        try:
            await attachments.setup()
        except Exception:
            log.exception("Liiteindeksin käyttöönotto epäonnistui")

        # Alusta tehtäväjono (ennen kahta muuta)
        await task_queue.start()

        # 1) Käynnistä worker AINA (riippumatta kanavasta)
        task = getattr(bot, "_worker_task", None)
        if task is None or task.done():
            bot._worker_task = asyncio.create_task(print_queue.start_worker())
            print_queue._worker_task = bot._worker_task

        # 2) Jaksollinen siivous (pending)
        async def _periodic_cleanup():
            while True:
                await asyncio.sleep(60)
                await handlers.cleanup_pending()
        task = getattr(bot, "_cleanup_task", None)
        if task is None or task.done():
            bot._cleanup_task = asyncio.create_task(_periodic_cleanup())

        # 3) Viestien automaattinen poisto (UUSI)
        task = getattr(bot, "_msg_cleanup_task", None)
        if task is None or task.done():
            bot._msg_cleanup_task = await start_cleanup_task(bot)

        # 4) Kanavan varmistus (ei estä käynnistystä)
        if TARGET_CHANNEL_ID is None:
            return
        channel = bot.get_channel(TARGET_CHANNEL_ID)
        if channel is None:
            for attempt in range(3):
                try:
                    channel = await bot.fetch_channel(TARGET_CHANNEL_ID)
                    break
                except discord.HTTPException as exc:
                    log.error("⚠️ Kanavaa %s ei löytynyt: %s", TARGET_CHANNEL_ID, exc)
                    if attempt < 2:
                        await asyncio.sleep(5 * (attempt + 1))
        if channel is not None:
            log.info("Kuuntelee kanavaa #%s", channel.name)

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            track_unscheduled_message(bot, message)
        tasks = {"viestireititys": route_incoming(message)}
        if message.guild and message.attachments and message.channel.id in attachments.channels:
            tasks["liiteindeksi"] = index_attachments(message)
        if ollama and bot.user:
            tasks["Ollama"] = ollama.handle(message, bot.user.id)
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for name, result in zip(tasks, results):
            if isinstance(result, Exception):
                log.error("%s epäonnistui | viesti=%s | kanava=%s",
                          name, message.id, message.channel.id, exc_info=result)

    @bot.event
    async def on_raw_reaction_add(reaction: discord.RawReactionActionEvent):
        await handlers.check_reaction(reaction)
        await handlers.check_url_reaction(reaction)


