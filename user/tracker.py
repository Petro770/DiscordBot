"""Viestien seuranta ja automaattinen poisto.

Tallentaa botin lähettämien viestien ID:t ja poistoaikataulun
kanavakohtaisiin JSON-tiedostoihin (DM/ ja Channels/ kansioissa).

Taustatehtävä skannaa tiedostot säännöllisesti ja poistaa
vanhentuneet viestit Discordista.
"""
import json
import os
import time
import asyncio
from pathlib import Path

import discord

from config import MESSAGE_RETENTION_DAYS, CLEANUP_INTERVAL
from core.logging import log

# ============================================================
# KANSIORAKENNE
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DM_DIR = BASE_DIR / "DM"
CHANNELS_DIR = BASE_DIR / "Channels"

# Oletussäilytys sekunteina
DEFAULT_LIFETIME_SECONDS = MESSAGE_RETENTION_DAYS * 24 * 60 * 60


def _ensure_dirs():
    """Luo kansiot jos puuttuvat."""
    DM_DIR.mkdir(exist_ok=True)
    CHANNELS_DIR.mkdir(exist_ok=True)


_ensure_dirs()


# ============================================================
# TIEDOSTO-I/O
# ============================================================

def _get_file_path(channel: discord.abc.Messageable) -> Path:
    """Palauttaa oikean tiedostopolun (DM tai kanava)."""
    if isinstance(channel, discord.DMChannel):
        return DM_DIR / f"{channel.id}.json"
    return CHANNELS_DIR / f"{channel.id}.json"


def _load_data(path: Path) -> dict:
    """Lataa JSON-tiedosto. Palauttaa tyhjän dict jos ei ole olemassa."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("message_tracker: luku epäonnistui (%s): %s", path.name, e)
        return {}


def _save_data(path: Path, data: dict) -> None:
    """Tallenna JSON-tiedosto. Poista tiedosto jos tyhjä."""
    try:
        if not data:
            if path.exists():
                path.unlink()
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        log.error("message_tracker: kirjoitus epäonnistui (%s): %s", path.name, e)


# ============================================================
# REKISTERÖINTI
# ============================================================

def register_message(message: discord.Message,lifetime_seconds: int | None = None,) -> None:
    """Rekisteröi botin lähettämä viesti poistolokiin.

    Parametrit:
        message: Discord-viesti joka on jo lähetetty.
        lifetime_seconds: Säilytysaika sekunteina. None → oletus (365 pv).
    """
    if lifetime_seconds is None:
        lifetime_seconds = DEFAULT_LIFETIME_SECONDS

    path = _get_file_path(message.channel)
    data = _load_data(path)

    now = time.time()
    data[str(message.id)] = {
        "delete_at": now + lifetime_seconds,
        "created_at": now,
    }

    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _save_data, path, data)
        log.debug(
            "📝 Viesti rekisteröity: ch=%s, msg=%d, poistetaan %.0f pv kuluttuen",
            message.channel.id, message.id, lifetime_seconds / 86400,
        )
    except RuntimeError:
        _save_data(path, data)


# ============================================================
# SIIVOUS
# ============================================================

async def _cleanup_one_file(bot: discord.Client, path: Path, channel_id: int) -> int:
    """Siivoa yksi tiedosto. Palauttaa poistettujen viestien määrän."""
    data = _load_data(path)
    if not data:
        if path.exists():
            path.unlink()
        return 0

    now = time.time()
    expired = {k: v for k, v in data.items() if now >= v.get("delete_at", 0)}

    if not expired:
        return 0

    # Hae kanava kerran
    channel: discord.abc.Messageable | None = None
    try:
        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)
    except Exception:
        # Kanavaa ei löydy tai ei oikeuksia – siivoa silti lokista
        log.info("🧹 Kanavaa %d ei löytynyt, siivotaan lokista.", channel_id)

    removed = 0
    for msg_id_str in expired:
        if channel is not None:
            try:
                msg = await channel.fetch_message(int(msg_id_str))
                await msg.delete()
            except discord.NotFound:
                pass  # jo poistettu
            except discord.Forbidden:
                log.info("🧹 Ei oikeutta poistaa viestiä %s kanavalta %d.", msg_id_str, channel_id)
            except Exception as e:
                log.warning("🧹 Poisto epäonnistui (msg=%s): %s", msg_id_str, e)

        del data[msg_id_str]
        removed += 1

    _save_data(path, data)
    return removed


async def cleanup_expired(bot: discord.Client) -> int:
    """Skannaa kaikki tiedostot ja poista vanhentuneet viestit.

    Palauttaa poistettujen viestien kokonaismäärän.
    """
    total_removed = 0

    for folder in (DM_DIR, CHANNELS_DIR):
        if not folder.exists():
            continue
        for file in folder.iterdir():
            if not file.suffix == ".json":
                continue
            try:
                channel_id = int(file.stem)
            except ValueError:
                continue

            try:
                removed = await _cleanup_one_file(bot, file, channel_id)
                if removed > 0:
                    log.info("🧹 Siivottu %d viestiä (%s).", removed, file.name)
                    total_removed += removed
            except Exception as e:
                log.warning("🧹 Siivousvirhe (%s): %s", file.name, e)

    return total_removed


# ============================================================
# TAUSTATEHTÄVÄ
# ============================================================

async def start_cleanup_task(bot: discord.Client) -> asyncio.Task:
    """Käynnistä jaksollinen siivoustehtävä. Palauttaa Task-objektin."""
    log.info("🧹 Viestisiivous käynnistyy (interval=%ds, retention=%d pv).",
             CLEANUP_INTERVAL, MESSAGE_RETENTION_DAYS)

    async def _loop():
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            try:
                await cleanup_expired(bot)
            except Exception as e:
                log.warning("🧹 Siivoustehtävä epäonnistui: %s", e)

    return asyncio.create_task(_loop())


# ============================================================
# KÄYTTÄJÄN POISTO
# ============================================================

async def purge_dm(bot: discord.Client, user_id: int) -> int:
    """Poista kaikki rekisteröidyt DM-viestit Discordista + tracking-tiedosto.

    Palauttaa poistettujen viestien määrän.
    """
    path = DM_DIR / f"{user_id}.json"

    if not path.exists():
        return 0

    data = _load_data(path)
    if not data:
        path.unlink(missing_ok=True)
        return 0

    # Hae käyttäjä ja DM-kanava kerran
    try:
        member = await bot.fetch_user(user_id)
        dm = await member.create_dm()
    except Exception as e:
        log.warning("🗑️ UNOHDAMINUT: DM-kanavaa ei saatu: %s", e)
        path.unlink(missing_ok=True)
        return 0

    # Poista viestit Discordista
    removed = 0
    for msg_id_str in data:
        try:
            msg = await dm.fetch_message(int(msg_id_str))
            await msg.delete()
            removed += 1
        except discord.NotFound:
            pass
        except discord.Forbidden:
            log.info("🗑️ UNOHDAMINUT: Ei oikeutta poistaa viestiä %s.", msg_id_str)
        except Exception as e:
            log.warning("🗑️ UNOHDAMINUT: Viestin poisto epäonnistui (%s): %s", msg_id_str, e)

    # Poista tracking-tiedosto
    path.unlink(missing_ok=True)
    log.info("🗑️ UNOHDAMINUT: DM-historia poistettu (user=%d, %d viestiä).", user_id, removed)
    return removed

# ============================================================
# KÄYTTÄJÄN POISTO (TÄYSI DM-PURKU)
# ============================================================

async def purge_all_dm_messages(bot: discord.Client, user_id: int) -> int:
    """Poista KAIKKI botin lähettämät DM-viestit käyttäjälle.

    Käyttää Discordin bulk-purge-endpointin (100 viestiä/kutsu).
    discord.py hoitaa rate-limitauksen sisäisesti.

    Palauttaa poistettujen viestien määrän.
    """
    try:
        member = await bot.fetch_user(user_id)
        dm = await member.create_dm()
    except Exception as e:
        log.warning("🗑️ DM-purku: käyttäjää/kanavaa ei saatu (user=%d): %s", user_id, e)
        return 0

    try:
        # author=bot.user → poistetaan VAIN botin omat viestit
        # bulk=True → käyttää /bulk-delete endpointia (tehokas)
        # limit=None → ei rajaa, hakee kaiken
        deleted = await dm.purge(
            author=bot.user,
            limit=None,
            bulk=True,
        )
        count = len(deleted)
        log.info("🗑️ DM-purku: %d viestiä poistettu (user=%d).", count, user_id)
        return count
    except discord.Forbidden:
        log.warning("🗑️ DM-purku: Ei oikeuksia poistaa viestejä (user=%d).", user_id)
        return 0
    except Exception as e:
        log.error("🗑️ DM-purku epäonnistui (user=%d): %s", user_id, e)
        return 0


async def purge_user_all(bot: discord.Client, user_id: int) -> int:
    """Täysi poisto: DM-viestit (Discordista) + tracking + asetukset.

    Suoritetaan taustalla. Palauttaa poistettujen viestien määrän.
    """
    # 1) Poista kaikki botin DM-viestit Discordista
    dm_removed = await purge_all_dm_messages(bot, user_id)

    # 2) Poista tracking-tiedosto (varmuuden vuoksi, vaikka purge hoiti)
    path = DM_DIR / f"{user_id}.json"
    path.unlink(missing_ok=True)

    # 3) Poista käyttäjäasetukset
    from user.settings import load_user_data, save_user_data
    data = load_user_data()
    if str(user_id) in data:
        del data[str(user_id)]
        save_user_data(data)
        log.info("🗑️ UNOHDAMINUT: Asetukset poistettu (user=%d).", user_id)

    return dm_removed
