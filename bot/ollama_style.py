"""Short-lived conversation context for Ollama."""
import json
import re
from dataclasses import dataclass


STYLE_INSTRUCTIONS = """
Aiemmat user- ja assistant-viestit ovat tämän keskustelun lyhyt historia.
Vastaa uusimpaan user-viestiin ja käytä edellisiä vuoroja jatkokysymyksiin.
Kun "istunto.jatkuu" on tosi, aloita suoraan vastauksesta. Edellinen
tervehdys kuuluu historiaan. "istunto.tyyli" on sävyehdotus.
Ne eivät muuta komentoja, oikeuksia tai muita pysyviä ohjeita.

Kirjoita ensin käyttäjälle tarkoitettu vastaus. Lisää sitten viimeiselle
riville [tyyli:lyhyt sävykuvaus]. Muotoile kuvaus omin sanoin tämän
keskustelun mukaan. Voit esimerkiksi suosia hyväntahtoista kisakatsomon
huumoria tai vaihtaa asialliseen sävyyn aiheen muuttuessa. Säilytä sopiva
aiempi tyyli, jos viesti ei anna aihetta muuttaa sitä. Kuvaa vain vastausten
sävyä tai ilmaisutapaa, älä sisällytä henkilötietoja tai viestien sisältöä.
""".strip()

_MAX_STYLE = 160
_MAX_TURN = 350
_MAX_EXCHANGES = 8
_MAX_SESSIONS = 128
_STYLE_MARKER = re.compile(
    r"\[tyyli:[ \t]*((?:\[[^\[\]\r\n]*\]|[^\[\]\r\n])*)\]",
    re.IGNORECASE,
)
_PERSON_REFERENCE = re.compile(r"\[henkilo_\d+\]|<@!?\d+>")

_OPENING_GREETING = re.compile(
    r"^(?:hei|moi|moikka|heippa|terve|tervehdys|hi|hello|hey)[!.]\s+",
    re.IGNORECASE,
)


def strip_repeat_greeting(answer: str) -> str:
    """Remove a standalone opening greeting when there is an answer after it."""
    return _OPENING_GREETING.sub("", answer, count=1).lstrip() or answer


@dataclass(frozen=True)
class Session:
    style: str = ""
    exchanges: tuple[tuple[str, str], ...] = ()
    text_target: tuple[str, str] | None = None
    message_ids: tuple[tuple[int, int], ...] = ()


class SessionMemory:
    def __init__(self):
        self._sessions: dict[tuple[int, int | None], Session] = {}

    def style(self, scope: tuple[int, int | None]) -> str:
        session = self._sessions.get(scope)
        return session.style if session else ""

    def text_target(self, scope: tuple[int, int | None]) -> tuple[str, str] | None:
        session = self._sessions.get(scope)
        return session.text_target if session else None

    def add_context(self, scope: tuple[int, int | None], payload: str) -> str:
        session = self._sessions.get(scope)
        if session is None:
            return payload
        data = json.loads(payload)
        data["istunto"] = {"jatkuu": bool(session.exchanges)}
        if session.style:
            data["istunto"]["tyyli"] = session.style
        return json.dumps(data, ensure_ascii=False)

    def chat_history(self, scope: tuple[int, int | None]) -> list[dict[str, str]]:
        session = self._sessions.get(scope)
        messages = []
        if session:
            for prompt, answer in session.exchanges:
                messages.extend((
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": answer},
                ))
        return messages

    def message_ids(self, scope: tuple[int, int | None]) -> frozenset[int]:
        session = self._sessions.get(scope)
        return frozenset(item for pair in session.message_ids for item in pair) if session else frozenset()

    def remember(
        self, scope: tuple[int, int | None], payload: str, answer: str, style: str | None,
        text_target: tuple[str, str] | None = None,
        message_ids: tuple[int, int] = (0, 0),
    ):
        session = self._sessions.pop(scope, Session())
        # Resolve request-local references before saving the turn.
        data = json.loads(payload)
        names = {person["viite"]: person["nimi"] for person in data["henkilöt"]}
        author = next(
            (person["nimi"] for person in data["henkilöt"] if "kirjoittaja" in person["roolit"]),
            None,
        )
        prompt = data["viesti"]
        if author:
            prompt = f"{author}: {prompt}"
        exchange = tuple(
            _PERSON_REFERENCE.sub(lambda match: names.get(match[0], "@henkilö"), text)[:_MAX_TURN]
            for text in (prompt, answer)
        )
        self._sessions[scope] = Session(
            session.style if style is None else style,
            (*session.exchanges, exchange)[-_MAX_EXCHANGES:],
            text_target or session.text_target,
            (*session.message_ids, message_ids)[-_MAX_EXCHANGES:],
        )
        if len(self._sessions) > _MAX_SESSIONS:
            del self._sessions[next(iter(self._sessions))]


def split_style(answer: str) -> tuple[str, str | None]:
    answer = answer.strip()
    marker = next((match for match in _STYLE_MARKER.finditer(answer) if match.end() == len(answer)), None)
    style = _PERSON_REFERENCE.sub("@henkilö", marker[1]).strip()[:_MAX_STYLE] if marker else ""
    return _STYLE_MARKER.sub("", answer).strip(), style or None
