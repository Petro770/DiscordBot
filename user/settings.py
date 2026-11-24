"""Käyttäjäkohtaiset asetukset ja data."""
import json
from datetime import datetime, timezone
from pathlib import Path
import asyncio

import discord

from core.logging import log

# ============================================================
# TIEDOSTOT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
USER_DATA_FILE = BASE_DIR / "user_data.json"


# ============================================================
# OLETUSASETUKSET
# ============================================================

WARNING_SETTINGS = {
    "KUVAKOPIOVAROITUS": "image_duplicate_warning",
    "REPOSTAUSVAROITUS": "repost_warning",
}
WARNING_MODES = {"KANAVA": "channel", "DM": "dm", "POIS": "off"}
WARNING_MODE_LABELS = {
    "channel": "Varoita kanavalla",
    "dm": "Varoita yksityisviestillä",
    "off": "Älä varoita",
}

DEFAULTS: dict[str, any] = {
    "image_duplicate_warning": "channel",
    "repost_warning": "channel",
    "include_content": True,  # Näytetäänkö metadata (otsikko, kuvaus, linkki)
}


# ============================================================
# I/O
# ============================================================

def load_user_data() -> dict[str, dict]:
    """Lataa käyttäjädata JSON-tiedostosta."""
    if not USER_DATA_FILE.exists():
        return {}
    try:
        with open(USER_DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("user_data.json luku epäonnistui: %s", e)
        return {}


def save_user_data(data: dict[str, dict]) -> None:
    """Tallenna käyttäjädata JSON-tiedostoon."""
    try:
        with open(USER_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        log.error("user_data.json kirjoitus epäonnistui: %s", e)


def get_user_entry(user_id: int) -> dict:
    """Palauttaa käyttäjän datan (luo tyhjän jos puuttuu)."""
    data = load_user_data()
    return data.get(str(user_id), {})


def set_user_entry(user_id: int, entry: dict) -> None:
    """Tallenna käyttäjän data."""
    data = load_user_data()
    data[str(user_id)] = entry
    save_user_data(data)


# ============================================================
# ASETTUKSET
# ============================================================

def get_setting(user_id: int, key: str) -> any:
    """Hae käyttäjän asetus. Palauttaa oletuksen jos ei ole määritelty."""
    entry = get_user_entry(user_id)
    return entry.get("settings", {}).get(key, DEFAULTS.get(key))


def set_setting(user_id: int, key: str, value: any) -> None:
    """Aseta käyttäjän arvo."""
    if key not in DEFAULTS:
        log.warning("Tuntematon asetusavain: %s", key)
        return

    entry = get_user_entry(user_id)
    entry.setdefault("settings", {})[key] = value
    entry["last_updated"] = datetime.now(timezone.utc).isoformat()
    set_user_entry(user_id, entry)
    log.info("⚙️ Asetus päivitetty: user=%s, %s=%s", user_id, key, value)


# ============================================================
# KOMENNOT
# ============================================================

SETTING_ALIASES: dict[str, str] = {
    "SISÄLTÖ": "include_content",
    "CONTENT": "include_content",
    "METADATA": "include_content",
    "INFO": "include_content",
}

ON_WORDS = {"PÄÄLLÄ", "ON", "YES", "TRUE", "KYLLÄ", "1", "KÄYTTÖÖN", "INCLUDE"}
OFF_WORDS = {"POIS", "OFF", "NO", "FALSE", "EI", "0", "PIILOTA", "EXCLUDE"}


def parse_setting_command(text: str) -> tuple[str, bool | str] | None:
    """Tunnista asetuskomento tekstistä.

    Palauttaa (avain, arvo) tai None jos ei ole asetuskomento.

    Esimerkkejä:
        "SISÄLTÖ POIS"       → ("include_content", False)
        "SISÄLTÖ PÄÄLLÄ"     → ("include_content", True)
        "CONTENT OFF"        → ("include_content", False)
    """
    words = [w.upper().strip() for w in text.split()]
    if len(words) < 2:
        return None

    key_word = words[0]
    if key_word in WARNING_SETTINGS:
        mode = WARNING_MODES.get(" ".join(words[1:]))
        if mode is not None:
            return WARNING_SETTINGS[key_word], mode
        return None

    # Ensimmäinen sana = asetusavain
    key = SETTING_ALIASES.get(key_word)
    if key is None:
        return None

    # Jäljellä olevat sanat: etsi ON/OFF
    remaining = " ".join(words[1:]).upper()
    if any(w in remaining for w in ON_WORDS):
        return key, True
    if any(w in remaining for w in OFF_WORDS):
        return key, False

    return None


async def handle_setting_command(
    message: discord.Message,
) -> bool:
    """Käsittele asetuskomento. Palauttaa True jos komento tunnistettiin."""
    if not message.content:
        return False

    result = parse_setting_command(message.content.strip())
    if result is None:
        return False

    key, value = result
    user_id = message.author.id

    set_setting(user_id, key, value)

    # Vastaus
    if key == "include_content":
        if value:
            result = await message.reply(
                "✅ Sisältö (otsikko, kuvaus, linkki) **päällä**.",
                silent=True,
            )
            from user.tracker import register_message
            register_message(result, lifetime_seconds=10)  # lyhyt, ei tarvitse tallentaa
        else:
            result = await message.reply(
                "✅ Sisältö **pois** – lähetetään vain tiedosto.",
                silent=True,
            )
            from user.tracker import register_message
            register_message(result, lifetime_seconds=10)
    else:
        command = message.content.split()[0].upper()
        result = await message.reply(
            f"✅ {command}: **{WARNING_MODE_LABELS[value]}**.",
            silent=True,
        )
        from user.tracker import register_message
        register_message(result, lifetime_seconds=10)

    return True


def should_include_content(user_id: int) -> bool:
    """Tarkista näytetäänkö sisältö (metadata) tälle käyttäjälle."""
    return bool(get_setting(user_id, "include_content"))

# ============================================================
# UNOHDAMINUT – KÄYTTÄJÄN TIEDOJEN TÄYSI POISTO
# ============================================================

UNOHDAMINUT_TRIGGERS = {"UNOHDAMINUT", "UNOHDA", "FORGETME", "DELETE_ME", "ERASE"}


def is_unohdaminut(text: str) -> bool:
    """Tunnista UNOHDAMINUT-komento."""
    if not text:
        return False
    words = [w.upper().strip() for w in text.split()]
    return words[0] in UNOHDAMINUT_TRIGGERS


async def handle_unohdaminut(message: discord.Message, bot: discord.Client | None = None) -> bool:
    """Käsittele UNOHDAMINUT-komennon.

    Toiminta:
    1. Vastaa käyttäjälle heti ("Poistan...")
    2. Taustalla: poista kaikki botin DM-viestit + tracking + asetukset
    3. Taustalla: lähetä lopullinen kuittaus

    Palauttaa True jos komento tunnistettiin.
    """
    user_id = message.author.id

    # 1) Heti kuittaus – käyttäjä tietää että käsitellään
    try:
        status = await message.reply(
            "👽 Poistan kaiken. Anna hetki...",
            silent=True,
        )
    except Exception:
        status = None

    # 2) Taustatehtävä – ei blokkkaa event-loopia
    async def _background_erase():
        try:
            from user.tracker import purge_user_all
            dm_removed = await purge_user_all(bot, user_id)

            # 3) Lopullinen kuittaus
            try:
                if dm_removed > 0:
                    await message.channel.send(
                        f"🛸 Valmis. {dm_removed} viestiä, asetukset ja jäljet poistettu.",
                        silent=True,
                    )
                else:
                    await message.channel.send(
                        "🛸 Valmis. Tallennetut tietosi on poistettu.",
                        silent=True,
                    )
            except Exception:
                pass

            # Poista tilaviesti (jos on olemassa)
            if status is not None:
                try:
                    await status.delete()
                except Exception:
                    pass

        except Exception as e:
            log.error("UNOHDAMINUT: Taustapuhdistus epäonnistui: %s", e)
            try:
                await message.channel.send(
                    "⚠️ Poisto epäonnistui. Yritä myöhemmin.",
                    silent=True,
                )
            except Exception:
                pass

    asyncio.create_task(_background_erase())
    return True
