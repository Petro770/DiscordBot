"""Discord-bot: eventit ja kanavalogiikka."""
import asyncio
import discord

import config
from config import TARGET_CHANNEL_ID
from printer.queue import PrintQueue
from bot.handlers import (
    init_handlers,
    route_message,
    check_reaction,
    cleanup_pending, check_url_reaction,
)
from bot.attachments import ChannelAttachments
from bot.ollama import OllamaReplies
from core.logging import log
from core.queue import init_queue
from user.tracker import start_cleanup_task, track_unscheduled_message


def create_bot() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.reactions = True
    return discord.Client(intents=intents)


def register_events(bot: discord.Client, print_queue: PrintQueue):
    # Alusta yhteiset handlerit (kerran)
    init_handlers(bot, print_queue)
    attachments = ChannelAttachments(bot, config.ATTACHMENT_INDEX_CHANNEL_IDS)

    ollama = OllamaReplies() if config.ENABLE_OLLAMA else None

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
            await route_message(message, [message.author.name])
            return

        if message.channel.id != TARGET_CHANNEL_ID:
            return

        names = [message.author.name]
        if message.guild:
            gm = message.guild.get_member(message.author)
            if gm and gm.display_name != message.author.name:
                names.append(gm.display_name)

        await route_message(message, names)

    @bot.event
    async def on_ready():
        log.info("👽 BogosBinted online! %s", bot.user)

        try:
            await attachments.setup()
        except Exception:
            log.exception("Liiteindeksin käyttöönotto epäonnistui")

        # Alusta tehtäväjono (ennen kahta muuta)
        await init_queue()

        # 1) Käynnistä worker AINA (riippumatta kanavasta)
        task = getattr(bot, "_worker_task", None)
        if task is None or task.done():
            bot._worker_task = asyncio.create_task(print_queue.start_worker())
            print_queue._worker_task = bot._worker_task

        # 2) Jaksollinen siivous (pending)
        async def _periodic_cleanup():
            while True:
                await asyncio.sleep(60)
                await cleanup_pending()
        bot._cleanup_task = asyncio.create_task(_periodic_cleanup())

        # 3) Viestien automaattinen poisto (UUSI)
        task = getattr(bot, "_msg_cleanup_task", None)
        if task is None or task.done():
            bot._msg_cleanup_task = await start_cleanup_task(bot)

        # 4) Kanavan varmistus (ei estä käynnistystä)
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
        log.info("Kuuntelee kanavaa #%s", channel.name)

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            track_unscheduled_message(bot, message)
        tasks = [route_incoming(message)]
        if message.guild and message.attachments and message.channel.id in attachments.channels:
            tasks.append(index_attachments(message))
        if ollama and bot.user:
            tasks.append(ollama.handle(message, bot.user.id))
        await asyncio.gather(*tasks)

    @bot.event
    async def on_raw_reaction_add(reaction: discord.RawReactionActionEvent):
        await check_reaction(reaction)
        await check_url_reaction(reaction)


