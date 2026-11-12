"""Tulostusjono rate-limitauksella."""
import asyncio
import os
import time
import random
from collections import deque
from printer.responses import get_response

from config import (
    DELAY_BETWEEN_PRINTS,
    MEME_TEXT,
    MAX_PRINTS_PER_MINUTE,
    MAX_QUEUE_SIZE,
    PRINTER_NAME,
    REACTION_EMOJI,
    REPLY_DELETE_AFTER,
)
from printer.engine import print_image
from core.logging import log


class PrintQueue:
    """Tulostusjono rate-limitauksella ja taustatyöläisellä."""

    def __init__(self, max_per_min: int = MAX_PRINTS_PER_MINUTE,
                 delay: float = DELAY_BETWEEN_PRINTS,
                 max_size: int = MAX_QUEUE_SIZE):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self.max_per_min = max_per_min
        self.delay = delay
        self.recent_prints: deque = deque(maxlen=max_per_min)
        self.running = False
        self._worker_task: asyncio.Task | None = None

    def is_rate_limited(self) -> bool:
        now = time.time()
        while self.recent_prints and now - self.recent_prints[0] > 60:
            self.recent_prints.popleft()
        return len(self.recent_prints) >= self.max_per_min

    def mark_print(self):
        self.recent_prints.append(time.time())

    async def start_worker(self):
        self.running = True
        try:
            while self.running:
                item = await self.queue.get()

                filepaths, message, names = item  # ← names on nyt lista

                ok_count = 0
                err_count = 0

                for filepath in filepaths:
                    while self.is_rate_limited():
                        log.info("⏳ Tulostusraja täynnä, odotetaan %.1f s...", self.delay)
                        await asyncio.sleep(self.delay)

                    log.info("🖨️ Tulostetaan: %s → %s", names[0], PRINTER_NAME)

                    try:
                        await asyncio.to_thread(print_image, filepath, PRINTER_NAME)
                        self.mark_print()
                        ok_count += 1
                    except Exception as e:
                        log.error("❌ Virhe: %s", e)
                        err_count += 1
                    finally:
                        if os.path.exists(filepath):
                            os.unlink(filepath)

                    if filepath != filepaths[-1]:
                        await asyncio.sleep(self.delay)

                # Kuittaus
                if ok_count > 0:
                    try:
                        await message.add_reaction(random.choice(["👽", "🛸", "📡", "✅", "🤖", "👁️", "⚡"]))
                    except Exception:
                        pass

                    text = get_response(ok_count, names)  # ← lista, ei string
                    try:
                        result = await message.reply(text, silent=True)
                        from user.tracker import register_message
                        register_message(result, lifetime_seconds=24 * 3600)
                    except Exception as exc:
                        log.warning("Kuittausviestin lähetys epäonnistui: %s", exc)
                else:
                    try:
                        await message.reply("⚠️ Tulostus epäonnistui.",
                                           delete_after=REPLY_DELETE_AFTER)
                    except Exception:
                        pass

                self.queue.task_done()

        except asyncio.CancelledError:
            log.info("Tulostustyöläinen keskeytetty.")
            raise



    def stop(self):
        self.running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()

