import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from bot.client import create_bot, register_events
from bot.handlers import MessageHandlers, Send
from core.queue import TaskQueue
from tools.git_update import GitUpdate, UpdateError
from printer.queue import PrintQueue


class RuntimeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_uses_injected_queue_before_ready_and_after_restart(self):
        for _ in range(2):
            queue = TaskQueue(workers=1, msg_interval=0)
            bot = SimpleNamespace(user=None)
            runtime = MessageHandlers(bot, Mock(), queue)
            message = SimpleNamespace(id=1, author=SimpleNamespace(id=2), channel=Mock(),
                                      reply=AsyncMock(return_value=Mock()))
            try:
                self.assertFalse(await runtime.check_reaction(SimpleNamespace(user_id=2)))
                with patch("user.tracker.register_message"):
                    self.assertIs(await Send(bot, queue, message).send("Vastaus"), message.reply.return_value)
                session = await runtime.get_session()
            finally:
                await runtime.close()
                await queue.stop()
            self.assertTrue(session.closed)

    async def test_client_close_releases_per_client_resources(self):
        bot = create_bot()
        register_events(bot, PrintQueue())
        await bot._task_queue.start()
        session = await bot._message_handlers.get_session()
        await asyncio.gather(bot.close(), bot.close())
        self.assertTrue(session.closed)
        self.assertFalse(bot._task_queue._tasks)

    async def test_stop_cancels_pending_and_active_submissions(self):
        queue = TaskQueue(workers=1)
        started = asyncio.Event()

        async def blocked():
            started.set()
            await asyncio.Future()

        active = asyncio.create_task(queue.submit(1, blocked))
        await started.wait()
        pending = asyncio.create_task(queue.submit(2, blocked))
        await asyncio.sleep(0)
        await queue.stop()
        for task in (active, pending):
            with self.assertRaises(asyncio.CancelledError):
                await task
        with self.assertRaises(RuntimeError):
            await queue.submit(3, blocked)


class GitDependencyTests(unittest.TestCase):
    def test_preflight_uses_selected_manifest_and_reports_missing_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            updater = GitUpdate(Path(folder))

            def run(arguments, **kwargs):
                self.assertIn("--dry-run", arguments)
                self.assertIn("--no-index", arguments)
                self.assertEqual(Path(arguments[-1]).read_text(), "discord.py>=2.3\n")
                return SimpleNamespace(returncode=1, stderr="missing dependency", stdout="")

            with patch.object(updater, "git", return_value="discord.py>=2.3") as git, \
                 patch("tools.git_update.subprocess.run", side_effect=run):
                with self.assertRaisesRegex(UpdateError, "missing dependency"):
                    updater.check_dependencies("target", Path(sys.executable))
                git.assert_called_once_with("show", "target:requirements.txt")
