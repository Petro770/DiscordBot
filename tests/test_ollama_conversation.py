import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import discord

from bot.ollama_people import conversation_scope, prepare_people
from bot.ollama_style import SessionMemory, strip_repeat_greeting


class OllamaConversationTests(unittest.IsolatedAsyncioTestCase):
    def message(self, message_id, parent=None):
        return SimpleNamespace(
            id=message_id,
            channel=SimpleNamespace(id=10),
            guild=object(),
            type=discord.MessageType.reply if parent else discord.MessageType.default,
            reference=SimpleNamespace(
                channel_id=10, message_id=parent.id, resolved=None, cached_message=parent,
            ) if parent else None,
            author=SimpleNamespace(id=1, display_name="Janne", bot=False),
            mentions=[],
            content=f"Viesti {message_id}",
        )

    async def test_replies_to_different_roots_have_separate_context(self):
        root = self.message(100)
        answer = self.message(101, root)
        followup = self.message(102, answer)
        other = self.message(200)
        scope, ancestors = await conversation_scope(followup)
        self.assertEqual(scope, (10, 100))
        self.assertEqual(await conversation_scope(other), ((10, 200), []))

        with patch("config.OLLAMA_RECENT_MESSAGES", 12):
            payload, _, count, _ = await prepare_people(
                followup, "Entä sitten?", 2, ancestors, frozenset({100, 101}),
            )
        self.assertEqual(count, 0)
        self.assertNotIn("kanavaviestit", json.loads(payload))

    async def test_memory_resolves_names_without_leaking_across_roots(self):
        memory = SessionMemory()
        payload, _, _, _ = await prepare_people(self.message(100), "Hei <@1>", 2, [])
        memory.remember((10, 100), payload, "Moi [henkilo_1]", "rento", message_ids=(100, 101))
        self.assertEqual(memory.chat_history((10, 100)), [
            {"role": "user", "content": "Janne: Hei Janne"},
            {"role": "assistant", "content": "Moi Janne"},
        ])
        self.assertEqual(memory.message_ids((10, 100)), {100, 101})
        self.assertEqual(memory.chat_history((10, 200)), [])
        self.assertEqual(memory.style((10, 200)), "")

    async def test_followup_is_marked_even_without_a_style(self):
        memory = SessionMemory()
        scope = (10, None)
        payload, _, _, _ = await prepare_people(self.message(100), "Hei", 2, [])
        self.assertNotIn("istunto", json.loads(memory.add_context(scope, payload)))
        memory.remember(scope, payload, "Hei!", None)
        self.assertEqual(json.loads(memory.add_context(scope, payload))["istunto"], {"jatkuu": True})

    def test_only_standalone_opening_greeting_is_removed(self):
        self.assertEqual(strip_repeat_greeting("Moi!\nTässä on vastaus."), "Tässä on vastaus.")
        self.assertEqual(strip_repeat_greeting("Hei!"), "Hei!")
        self.assertEqual(strip_repeat_greeting('Sano "Hei!"'), 'Sano "Hei!"')

    async def test_update_notices_and_fallbacks_do_not_become_background(self):
        question = self.message(104)
        notice = self.message(103)
        notice.author = SimpleNamespace(id=2, bot=True)
        notice.content = "🛸 **Botin päivitykset**\nVersio 1.2.1"
        fallback = self.message(102)
        fallback.author = notice.author
        fallback.content = "Ollama ei saanut muodostettua vastausta. Palvelin voi olla poissa käytöstä."
        conversation = self.message(101)
        conversation.author = notice.author
        conversation.content = "Kyllä, voidaan jutella."
        payload, _, count, _ = await prepare_people(
            question, "osaatko tehdä voltin?", 2, [notice, fallback, conversation],
        )
        data = json.loads(payload)
        self.assertEqual(count, 1)
        self.assertEqual(data["kanavaviestit"][0]["teksti"], conversation.content)
        self.assertEqual(list(data)[-1], "viesti")
        memory = SessionMemory()
        memory.remember((10, None), payload, "En fyysisesti.", None)
        self.assertEqual(list(json.loads(memory.add_context((10, None), payload)))[-1], "viesti")

    async def test_background_preserves_newest_text_within_budget(self):
        question = self.message(110)
        ancestors = [self.message(i) for i in range(109, 103, -1)]
        for message in ancestors:
            message.content = str(message.id) + " x" * 250
        with patch("config.OLLAMA_RECENT_MESSAGES", 12):
            payload, _, count, _ = await prepare_people(question, "Uusi aihe", 2, ancestors)
        background = json.loads(payload)["kanavaviestit"]
        self.assertEqual(count, 4)
        self.assertTrue(background[-1]["teksti"].startswith("109"))
        self.assertLessEqual(sum(len(item["teksti"]) for item in background), 1200)

    def test_long_repeated_answer_is_rejected_but_short_reply_is_allowed(self):
        from bot.ollama import _repeats_previous_answer

        old = "Edellisessä vastauksessa oli pitkä kuvaus. " * 5
        history = [{"role": "assistant", "content": old}]
        self.assertTrue(_repeats_previous_answer(old + "Uusi lause.", history, "{}"))
        self.assertFalse(_repeats_previous_answer("Moi!", history, "{}"))
        background = {"kanavaviestit": [{"kirjoittaja": "botti", "teksti": old}]}
        self.assertTrue(_repeats_previous_answer(old, [], json.dumps(background)))

    def test_wrapped_duplicate_and_summary_echo(self):
        from bot.ollama import _repeats_previous_answer
        from bot.ollama_style import split_style

        body = "Lasipurkin läpi näkisin toimiston, mutta kaipaisin ulos. " * 4
        body = body.strip()
        previous = f"Tässä on vastaus:\n\n**Vastaus:**  \n{body}  \n\n****  \n{body}"
        self.assertEqual(split_style(previous), (body, None))
        result, _ = split_style(f"Vastaus:  \n{body}\n\n****  \nTyyli: lyhyt sävykuvaus")
        self.assertEqual(result, body)
        history = [{"role": "assistant", "content": previous[:350]}]
        self.assertTrue(_repeats_previous_answer(result, history, "{}"))
        self.assertFalse(_repeats_previous_answer("Lasin takaa kaipaan taivasta.", history, "{}"))
        self.assertEqual(split_style("Lasin takaa kaipaan taivasta. [tyyli:runollinen]"),
                         ("Lasin takaa kaipaan taivasta.", "runollinen"))

    async def test_internal_people_json_is_blocked_before_and_after_rendering(self):
        from bot.ollama_people import echoes_internal_context, _is_conversation_message
        raw = '```json\n{"henkelö":"[henkilo_1]","nimi":"Testi","roolit":["kirjoittaja"]}\n```'
        self.assertTrue(echoes_internal_context(raw))
        prior = self.message(110)
        prior.author = SimpleNamespace(id=2, bot=True)
        prior.content = raw.replace("[henkilo_1]", "<@123>")
        self.assertFalse(_is_conversation_message(prior, 2))
        self.assertFalse(echoes_internal_context('{"musiikki": "tekno"}'))

    def test_standalone_continuation_and_model_reuse_have_separate_scopes(self):
        m = SessionMemory()
        root = (10, 100)
        target = ("http://test", "gemma3:1b")
        payload = '{"viesti":"hei","henkilöt":[]}'
        with patch("bot.ollama_style.monotonic", return_value=1000):
            m.remember(root, payload, "moi", None, target, (101, 102), 8)
            self.assertEqual(m.resolve_scope((10, 103), 8, True), root)
            self.assertEqual(m.resolve_scope((10, 103), 9, True), (10, 103))
            self.assertEqual(m.resolve_scope((10, 101), 9, False), root)
        with patch("bot.ollama_style.monotonic", return_value=1800):
            self.assertEqual(m.resolve_scope((10, 103), 8, True), (10, 103))
        self.assertEqual(m.text_target((10, 103)), target)
        self.assertFalse(m.chat_history((10, 103)))
        self.assertIsNone(m.text_target((11, 100)))

    def test_exclusions_in_priority_list(self):
        import os
        import config
        with patch.dict(os.environ, {"OLLAMA_CHAT_PRIORITY": "!qwen3:1.7b,!qwen3:8b,gemma3:1b"}):
            models, excluded = config._ollama_model_list("OLLAMA_CHAT_PRIORITY")
        self.assertEqual(models, ("gemma3:1b",))
        self.assertEqual(excluded, {"qwen3:1.7b", "qwen3:8b"})

    async def test_channel_mentions_fetch_background_and_reuse_successful_route(self):
        from unittest.mock import AsyncMock, MagicMock
        from bot.ollama import OllamaReplies

        async def history(*, limit, before):
            yield self.message(99)

        target = ("http://host", "gemma3:1b")
        generate = AsyncMock(return_value=("Hyvin istuu.", target))
        with patch("config.OLLAMA_CHANNEL_IDS", {10}), patch("config.OLLAMA_RECENT_MESSAGES", 12), patch(
            "bot.ollama._generate", generate
        ):
            replies = OllamaReplies()
            for number in (100, 102):
                message = self.message(number)
                message.content = "<@2> Kerro lisää."
                message.attachments = []
                message.channel.history = history
                message.channel.typing = MagicMock()
                message.reply = AsyncMock(return_value=self.message(number + 1))
                await replies.handle(message, 2)
        first, second = generate.await_args_list
        self.assertEqual(json.loads(first.args[0])["kanavaviestit"][0]["teksti"], "Viesti 99")
        self.assertIsNone(first.kwargs["preferred"])
        self.assertEqual(second.kwargs["preferred"], target)
        self.assertEqual(second.kwargs["history"][-1], {"role": "assistant", "content": "Hyvin istuu."})
