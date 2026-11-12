"""Entry point CLI:lle - käynnistää botin konsolissa."""
import asyncio
import signal
import sys

import discord

import config
from bot.client import create_bot, register_events
from printer.queue import PrintQueue
from core.logging import log, enable_console



async def main():
    # CLI-versio: loki näkyy myös konsolissa
    enable_console()

    if not config.TOKEN:
        raise SystemExit("Aseta DISCORD_TOKEN config.py-tiedostoon.")

    log.info("BogosBinted v%s käynnistyy...", config.BOT_VERSION)

    bot = create_bot()
    print_queue = PrintQueue()
    register_events(bot, print_queue)

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(_shutdown(bot, print_queue))
            )

    try:
        await bot.start(config.TOKEN)
    finally:
        print_queue.stop()


async def _shutdown(bot: discord.Client, print_queue: PrintQueue):
    log.info("Suljetaan...")
    print_queue.stop()
    await bot.close()


if __name__ == "__main__":
    asyncio.run(main())

