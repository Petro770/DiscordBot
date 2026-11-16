"""Viestien seuranta ja automaattinen poisto.

Tallentaa botin lähettämien viestien ID:t ja poistoaikataulun
kanavakohtaisiin JSON-tiedostoihin (DM/ ja Channels/ kansioissa).

Taustatehtävä skannaa tiedostot säännöllisesti ja poistaa
vanhentuneet viestit Discordista.
"""
import json
import os
import time
import math
import asyncio
from pathlib import Path

import discord

from config import (
    CLEANUP_INTERVAL,
    MESSAGE_RETENTION_DAYS,
    UNTRACKED_BOT_MESSAGE_CHANNEL_ID,
    UNTRACKED_BOT_MESSAGE_CLEANUP_MODE,
    UNTRACKED_BOT_MESSAGE_RETENTION_HOURS,
)
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


def _load_data(path: Path, *, strict: bool = False) -> dict:
    """Lataa JSON-tiedosto. Palauttaa tyhjän dict jos ei ole olemassa."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("JSONin juuren pitää olla objekti")
            return data
    except (ValueError, OSError) as e:
        if strict:
            raise
        log.warning("message_tracker: luku epäonnistui (%s): %s", path.name, e)
        return {}


def _save_data(path: Path, data: dict) -> None:
    """Tallenna JSON-tiedosto. Poista tiedosto jos tyhjä."""
    try:
        if not data:
            if path.exists():
                path.unlink()
            return
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(path)
    except OSError:
        log.exception("message_tracker: kirjoitus epäonnistui (%s)", path.name)
        raise


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
    now = time.time()
    try:
        data = _load_data(path, strict=True)
        data[str(message.id)] = {"delete_at": now + lifetime_seconds, "created_at": now}
        _save_data(path, data)
    except (OSError, ValueError):
        log.exception("Viestin %s poistoajan tallennus epäonnistui", message.id)
        return
    log.debug("Viesti rekisteröity: kanava=%s, viesti=%s, säilytys=%.2f pv",
              message.channel.id, message.id, lifetime_seconds / 86400)


def _has_delete_at(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    value = entry.get("delete_at")
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _fallback_schedule(message: discord.Message) -> dict[str, float]:
    created_at = message.created_at.timestamp()
    return {
        "created_at": created_at,
        "delete_at": created_at + UNTRACKED_BOT_MESSAGE_RETENTION_HOURS * 3600,
    }


def track_unscheduled_message(bot: discord.Client, message: discord.Message) -> None:
    if (UNTRACKED_BOT_MESSAGE_CLEANUP_MODE != "delete"
            or message.guild is None
            or message.channel.id != UNTRACKED_BOT_MESSAGE_CHANNEL_ID
            or bot.user is None
            or message.author.id != bot.user.id):
        return
    path = _get_file_path(message.channel)
    try:
        data = _load_data(path, strict=True)
        key = str(message.id)
        if not _has_delete_at(data.get(key)):
            data[key] = _fallback_schedule(message)
            _save_data(path, data)
            log.debug("Viestisiivous: botin uusi viesti ajastettu, kanava=%s, viesti=%s",
                      message.channel.id, message.id)
    except (OSError, ValueError):
        log.exception("Viestisiivous: viestin %s ajastus epäonnistui", message.id)


async def _discover_unscheduled(bot: discord.Client) -> None:
    mode = UNTRACKED_BOT_MESSAGE_CLEANUP_MODE
    channel_id = UNTRACKED_BOT_MESSAGE_CHANNEL_ID
    if mode == "off" or channel_id is None or bot.user is None:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        log.warning("Viestisiivous: kanava %s ei ole palvelimen tekstikanava tai ketju", channel_id)
        return

    tracker_path = _get_file_path(channel)
    cursor_path = CHANNELS_DIR / f"cleanup-{mode}-{channel_id}.json"
    cursor = _load_data(cursor_path, strict=True).get("last_message_id")
    data = _load_data(tracker_path, strict=True)
    after = discord.Object(id=cursor) if cursor else None
    candidates = {}
    last_id = cursor
    checked = 0
    async for message in channel.history(limit=500, after=after, oldest_first=True):
        last_id = message.id
        checked += 1
        if message.author.id == bot.user.id and not _has_delete_at(data.get(str(message.id))):
            candidates[str(message.id)] = _fallback_schedule(message)

    # A live event may have registered messages while Discord history was loading.
    if candidates:
        latest = _load_data(tracker_path, strict=True)
        candidates = {key: entry for key, entry in candidates.items() if not _has_delete_at(latest.get(key))}
        if mode == "delete" and candidates:
            latest.update(candidates)
            _save_data(tracker_path, latest)
    if last_id != cursor:
        _save_data(cursor_path, {"last_message_id": last_id})
    if checked:
        due = [key for key, entry in candidates.items() if entry["delete_at"] <= time.time()]
        log.info("Viestisiivous (%s): kanava=%s, tarkistettu=%d, ajastamattomia=%d, erääntyneitä=%d",
                 mode, channel_id, checked, len(candidates), len(due))
        if due:
            log.info("Viestisiivous (%s): erääntyneet viestit, kanava=%s, viestit=%s",
                     mode, channel_id, ", ".join(due))


# ============================================================
# SIIVOUS
# ============================================================

async def _cleanup_one_file(bot: discord.Client, path: Path, channel_id: int) -> int:
    """Siivoa yksi tiedosto. Palauttaa poistettujen viestien määrän."""
    data = _load_data(path, strict=True)
    now = time.time()
    expired = {
        key: entry for key, entry in data.items()
        if _has_delete_at(entry) and now >= entry["delete_at"]
    }
    if not expired or bot.user is None:
        return 0

    try:
        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)
    except discord.NotFound:
        # The channel is gone, so the tracked messages are gone as well.
        channel = None
    except discord.HTTPException:
        log.exception("Viestisiivous: kanavan %s haku epäonnistui, yritetään myöhemmin", channel_id)
        return 0

    handled = {}
    for key, entry in expired.items():
        if channel is not None:
            try:
                msg = await channel.fetch_message(int(key))
                if msg.author.id != bot.user.id:
                    log.warning("Viestisiivous: ohitettiin toisen lähettäjän viesti %s", key)
                elif _load_data(path, strict=True).get(key) == entry:
                    await msg.delete()
                else:
                    continue
            except discord.NotFound:
                pass
            except discord.HTTPException:
                log.exception("Viestisiivous: viestin %s poisto epäonnistui, yritetään myöhemmin", key)
                continue

        handled[key] = entry
        log.debug("Viestisiivous: käsitelty kanava=%s, viesti=%s", channel_id, key)

    current = _load_data(path, strict=True)
    removed = 0
    for key, entry in handled.items():
        if current.get(key) == entry:
            del current[key]
            removed += 1
    if removed:
        _save_data(path, current)
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
            try:
                await _discover_unscheduled(bot)
            except Exception:
                log.exception("Viestisiivous: ajastamattomien viestien haku epäonnistui")
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
