"""Changelog-seuranta ja DM-kysely."""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import discord
import config

from core.logging import log

# ============================================================
# TIEDOSTOT
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
CHANGELOG_FILE = BASE_DIR / "changelog.json"

from user.settings import load_user_data, save_user_data

# ============================================================
# DATA
# ============================================================

CHANGE_TYPE_ICONS = {
    "feat": "✨",
    "fix": "🐛",
    "improve": "⚡",
    "break": "⚠️",
    "meta": "📝",
}

CHANGE_TYPE_LABELS = {
    "feat": "Uusi",
    "fix": "Korjaus",
    "improve": "Parannus",
    "break": "Iso muutos",
    "meta": "Sisäinen",
}

@dataclass
class ChangelogEntry:
    version: str
    date: str
    changes: list[dict]

# ============================================================
# LATAUS
# ============================================================

def load_changelog() -> list[ChangelogEntry]:
    """Lataa changelog JSON:ista. Palauttaa listan uusin → vanhin."""
    try:
        with CHANGELOG_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("versions", []), list):
            raise ValueError("Virheellinen versiolista")
    except (OSError, ValueError) as exc:
        log.warning("Changelogin lukeminen epäonnistui: %s", exc)
        return []
    entries = [
        ChangelogEntry(
            version=v["version"],
            date=v.get("date", ""),
            changes=v.get("changes", []),
        )
        for v in data.get("versions", [])
        if isinstance(v, dict) and isinstance(v.get("version"), str) and isinstance(v.get("changes", []), list)
    ]
    return entries

# ============================================================
# VERSIOLAJITTELU
# ============================================================

def parse_version(v: str) -> tuple[int, ...]:
    """'1.2.3' → (1, 2, 3)"""
    if not isinstance(v, str):
        return ()
    parts = v.strip().removeprefix("v").split(".")
    if not all(part.isascii() and part.isdecimal() for part in parts):
        return ()
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return ()

def version_is_newer(current: str, stored: str) -> bool:
    """Palauttaa True jos current on uudempi kuin stored."""
    current_parts, stored_parts = parse_version(current), parse_version(stored)
    return bool(current_parts and stored_parts and current_parts > stored_parts)

# ============================================================
# CHANGLOGIN MUOTOILU
# ============================================================

def format_changelog_since(user_version: str,current_version: str,entries: list[ChangelogEntry],) -> str | None:
    """Muodosta Discord-viesti käyttäjän vanhasta versiosta nykyiseen."""
    user_ver = parse_version(user_version)
    relevant = [e for e in entries if parse_version(e.version) > user_ver]

    if not relevant:
        return None

    relevant.reverse()

    lines: list[str] = []
    lines.append("🛸 **Botin päivitykset**")
    lines.append(f"*(versio {user_version} → {current_version})*")
    lines.append("")

    for entry in relevant:
        lines.append(f"**v{entry.version}**" + (f"  *{entry.date}*" if entry.date else ""))
        for change in entry.changes:
            if not isinstance(change, dict):
                continue
            ctype = change.get("type", "meta")
            text = change.get("text", "")
            if ctype == "meta":
                continue
            icon = CHANGE_TYPE_ICONS.get(ctype, "•")
            lines.append(f"  {icon} {text}")
        lines.append("")

    result = "\n".join(lines)

    if len(result) > 1990:
        result = result[:1987] + "…"

    return result

# ============================================================
# PÄÄTOIMINTO: TARKISTA + DM
# ============================================================

def get_bot_version() -> str:
    return config.BOT_VERSION

_notifications_in_flight: set[int] = set()


async def check_and_notify_user(bot: discord.Client, user_id: int, username: str,
                                source: discord.Message | None = None):
    """Send an update notice once per user and version."""
    if user_id in _notifications_in_flight:
        return
    _notifications_in_flight.add(user_id)
    try:
        current_version = get_bot_version()
        entries = load_changelog()
        if not entries:
            return
        key = str(user_id)
        initial = load_user_data().get(key, {})
        stored_version = initial.get("version", "0.0.0")
        acknowledged_version = stored_version
        if version_is_newer(current_version, stored_version):
            text = format_changelog_since(stored_version, current_version, entries)
            if not text or await _deliver_update(bot, user_id, username, text, source):
                acknowledged_version = current_version

        users = load_user_data()
        if initial and key not in users:
            return  # Käyttäjä ehti poistaa tietonsa ilmoituksen aikana.
        entry = users.setdefault(key, {})
        if version_is_newer(acknowledged_version, entry.get("version", "0.0.0")):
            entry["version"] = acknowledged_version
        entry["last_seen"] = datetime.now(timezone.utc).isoformat()
        save_user_data(users)
    finally:
        _notifications_in_flight.discard(user_id)


async def _deliver_update(bot, user_id, username, text, source):
    mentions = discord.AllowedMentions.none()
    try:
        member = await bot.fetch_user(user_id)
        dm_channel = await member.create_dm()
        await dm_channel.send(text, allowed_mentions=mentions)
    except discord.HTTPException as exc:
        log.warning("Changelog-DM epäonnistui käyttäjälle %s (HTTP %s)", username, exc.status)
    else:
        log.info("Changelog-DM lähetetty käyttäjälle %s", username)
        return True

    if source is None or source.guild is None:
        return False
    try:
        await source.reply(
            f"Botista on saatavilla päivitystiedot (v{get_bot_version()}). "
            "Yksityisviestiä ei voitu toimittaa.",
            mention_author=False, allowed_mentions=mentions, silent=True,
        )
    except discord.HTTPException as exc:
        log.warning("Changelog-kanavailmoitus epäonnistui (HTTP %s)", exc.status)
        return False
    log.info("Changelog-ilmoitus lähetetty kanavalle %s", source.channel.id)
    return True
