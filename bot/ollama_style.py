"""Temporary, channel-local style additions selected by the model."""
import re


STYLES = {
    "avaruus": "Kevyissä jutuissa voit käyttää lyhyitä avaruusvertauksia.",
    "kuivahuumori": "Kevyissä jutuissa voit käyttää kuivaa, hyväntahtoista huumoria.",
    "radiokuittaus": "Sopivassa tilanteessa voit kuitata lyhyesti radioliikenteen tyyliin.",
    "sanaleikki": "Voit käyttää luontevaa sanaleikkiä, kun se sopii aiheeseen.",
}

STYLE_INSTRUCTIONS = (
    "Jos keskustelu on leikkisä ja jokin sävy sopii myös seuraaviin viesteihin, "
    "voit ehdottaa istunnon tyylilisäystä vastauksesi viimeisellä omalla rivillä "
    "muodossa [tyyli:avaruus]. Sallitut tunnisteet ovat " + ", ".join(STYLES) + ". "
    "Tunniste on valinnainen, ja varsinainen vastaus tulee ennen sitä. "
    "Pidä vakavat vastaukset asiallisina ja komento-ohjeet täsmällisinä."
)

_STYLE_MARKER = re.compile(r"\[tyyli:([^\]\r\n]*)\]")


class SessionStyles:
    def __init__(self):
        self._channels: dict[int, tuple[str, ...]] = {}

    def instructions(self, channel_id: int) -> str:
        styles = self._channels.get(channel_id, ())
        return "\n".join(STYLES[style] for style in styles)

    def remember(self, channel_id: int, style: str):
        current = self._channels.pop(channel_id, ())
        self._channels[channel_id] = tuple(item for item in current if item != style)[-1:] + (style,)
        if len(self._channels) > 128:
            del self._channels[next(iter(self._channels))]


def split_style(answer: str) -> tuple[str, str | None]:
    answer = answer.rstrip()
    last_line = answer.rsplit("\n", 1)[-1].strip()
    marker = _STYLE_MARKER.fullmatch(last_line)
    style = marker[1] if marker and marker[1] in STYLES else None
    return _STYLE_MARKER.sub("", answer).strip(), style
