"""Ohje- ja apukomennot."""
import discord

from core.logging import log

# ============================================================
# KOMENNOT (tunnistus)
# ============================================================

HELP_TRIGGERS = {"OHJE", "APU", "HELP", "?"}

# Erityisohjeet (toinen sana)
TOPIC_ALIASES: dict[str, str] = {
    "SISÄLTÖ": "content",
    "CONTENT": "content",
    "METADATA": "content",
    "POISTA": "delete",
    "DELETE": "delete",
    "JAA": "forward",
    "FORWARD": "forward",
    "ASETUKSET": "settings",
    "SETTINGS": "settings",
    "UNOHDAMINUT": "forget",
    "UNOHDA": "forget",
}


def parse_help_command(text: str) -> str | None:
    """Tunnista ohjekomento. Palauttaa aiheen ('general' tai topic) tai None."""
    if not text:
        return None

    words = [w.upper().strip() for w in text.split()]
    if not words:
        return None

    first = words[0]
    if first not in HELP_TRIGGERS:
        return None

    # "OHJE" yksin → yleinen ohje
    if len(words) == 1:
        return "general"

    # "OHJE SISÄLTÖ" → erityisohje
    topic = TOPIC_ALIASES.get(words[1])
    if topic is None:
        return "unknown"

    return topic


# ============================================================
# SISÄLTÖ
# ============================================================

HELP_GENERAL = """👽 **Bogos Binted – Ohje**

**Videot & kuvat:**
Lähetä linkki (YouTube, Instagram, X, TikTok, Twitch, SoundCloud) tai kuva → bot lataa ja lähettää tiedoston.

**AliExpress:**
Lähetä tuotelinkki → botti palauttaa siistin linkin ja saatavilla olevat tuotetiedot.

**Komennot:**
• `POISTA` – poista alkuperäinen viesti käsittelyn jälkeen
• `JAA` – lähetä tulos myös kanavalle (DM:stä)
• `SISÄLTÖ POIS` – älä näytä otsikkoa/kuvausta
• `SISÄLTÖ PÄÄLLÄ` – näytä otsikko/kuvaus (oletus)
• `UNOHDAMINUT` – poista kaikki tietoni ja DM-historia
• `OHJE` – näytä tämä ohje
• `OHJE SISÄLTÖ` – lisätieto sisältö-asetuksesta
• `OHJE ASETUKSET` – käyttäjäkohtaiset varoitusasetukset

**Esimerkki:**
`POISTA JAA https://youtu.be/xxxxx`
→ lataa, poista viestisi, lähetä tulos kanavalle

*Yksityiskohdat: `OHJE SISÄLTÖ`, `OHJE POISTA`, `OHJE JAA`, `OHJE UNOHDAMINUT`*"""


HELP_CONTENT = """📋 **SISÄLTÖ-asetus**

Määrittelään näytetäänkö tiedoston yhteydessä metadata (otsikko, julkaisija, kuvaus, linkki) vai lähetetäänkö pelkkä tiedosto.

**Komennot:**
• `SISÄLTÖ PÄÄLLÄ` → metadata näkyvissä (oletus)
• `SISÄLTÖ POIS` → vain tiedosto, ei tekstiä

**Esimerkki:**
SISÄLTÖ PÄÄLLÄ:
  🎬 **Videootsikko**
  👤 @uploader
  💬 Kuvaus tässä...
  [tiedosto.mp4]

SISÄLTÖ POIS:
  [tiedosto.mp4]

*Asetus on pysyvä ja käyttäjäkohtainen.*"""


HELP_SETTINGS = """⚙️ **Käyttäjäasetukset**

• `KUVAKOPIOVAROITUS KANAVA` / `DM` / `POIS` – mahdolliset kuvakopiot
• `REPOSTAUSVAROITUS KANAVA` / `DM` / `POIS` – täsmälliset liitekopiot

Molempien oletus on `KANAVA`. `DM` lähettää varoituksen yksityisviestinä ja `POIS` kytkee sen pois.
Jos varoitustavalle ei ole omaa asetusta, voit valita sen myös kanavavaroituksen painikkeista.
Voit muuttaa omia asetuksiasi botin yksityisviestissä tai sen kohdekanavalla.
Sisältöasetuksen ohje löytyy komennolla `OHJE SISÄLTÖ`."""


HELP_DELETE = """🗑️ **POISTA-komento**

Lisää `POISTA` viestin alkuun, jotta bot poistaa alkuperäisen viestisi onnistuneen käsittelyn jälkeen.

**Esimerkki:**
`POISTA https://youtu.be/xxxxx`
→ bot lataa, lähettää tiedoston ja poistaa viestisi

*Ilman POISTAA viestisi jää paikalleen.*"""


HELP_FORWARD = """📤 **JAA-komento**

Lähetä tiedosto DM:ssä ja lisää `JAA` – bot lähettää tuloksen myös julkiselle kanavalle.

**Esimerkki:**
`JAA https://youtu.be/xxxxx`
→ bot lähettää tiedoston sinulle JA kanavalle (mainitsee sinut)

*Toimii vain DM:stä. Kanavalla ei tarvita.*"""


HELP_UNKNOWN = "👽 Tunnistamaton ohjeaihe. Kokeile `OHJE` ilman lisäystä."

HELP_FORGET = """🗑️ **UNOHDAMINUT**

Poistaa kaiken botin tallentaman tietosi:
• Kaikki botin lähettämät DM-viestit poistetaan Discordista
• DM-tracking-tiedosto tuhotaan
• Käyttäjäasetukset (SISÄLTÖ jne.) poistetaan

**Komento:**
`UNOHDAMINUT`

*Toiminta on peruuttamaton. Bogos Binted ei muista sinua enää.*"""


# ============================================================
# JULKINEN API
# ============================================================

async def handle_help(message: discord.Message) -> bool:
    """Käsittele ohjekomento. Palauttaa True jos tunnistettiin."""
    if not message.content:
        return False

    topic = parse_help_command(message.content.strip())
    if topic is None:
        return False

    if topic == "general":
        content = HELP_GENERAL
    elif topic == "content":
        content = HELP_CONTENT
    elif topic == "settings":
        content = HELP_SETTINGS
    elif topic == "delete":
        content = HELP_DELETE
    elif topic == "forward":
        content = HELP_FORWARD
    elif topic == "forget":
        content = HELP_FORGET
    else:
        content = HELP_UNKNOWN

    try:
        result = await message.reply(content, silent=True)
        from user.tracker import register_message
        register_message(result)
    except Exception as e:
        log.warning("Ohjeen lähetys epäonnistui: %s", e)

    return True


