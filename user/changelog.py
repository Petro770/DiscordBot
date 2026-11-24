"""Changelog-seuranta ja DM-kysely."""
import json
import os
import asyncio
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
    if not CHANGELOG_FILE.exists():
        log.warning("changelog.json puuttuu!")
        return []
    with open(CHANGELOG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = [
        ChangelogEntry(
            version=v["version"],
            date=v.get("date", ""),
            changes=v.get("changes", []),
        )
        for v in data.get("versions", [])
    ]
    return entries

# ============================================================
# VERSIOLAJITTELU
# ============================================================

def parse_version(v: str) -> tuple[int, ...]:
    """'1.2.3' → (1, 2, 3)"""
    parts = v.lstrip("v").split(".")
    return tuple(int(p) for p in parts if p.isdigit())

def version_is_newer(current: str, stored: str) -> bool:
    """Palauttaa True jos current on uudempi kuin stored."""
    try:
        return parse_version(current) > parse_version(stored)
    except (ValueError, TypeError):
        return False

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

async def check_and_notify_user(bot: discord.Client,user_id: int,username: str,):
    """Tarkista käyttäjän versio ja lähetä changelog-DM jos tarpeen."""
    current_version = get_bot_version()
    entries = load_changelog()

    if not entries:
        return

    users = load_user_data()
    stored = users.get(str(user_id), {})
    stored_version = stored.get("version", "0.0.0")

    now_iso = datetime.now(timezone.utc).isoformat()
    users[str(user_id)] = {
        "version": current_version,
        "last_seen": now_iso,
        "settings": stored.get("settings", {}),  # säilytä asetukset
    }
    save_user_data(users)

    if not version_is_newer(current_version, stored_version):
        return

    message_text = format_changelog_since(stored_version, current_version, entries)
    if not message_text:
        return

    try:
        member = await bot.fetch_user(user_id)
        dm_channel = await member.create_dm()
        await dm_channel.send(message_text)
        log.info("📬 Changelog-DM lähetetty: %s (v%s → v%s)", username, stored_version, current_version)
    except discord.Forbidden:
        log.info("📬 Changelog-DM estetty: %s", username)
    except discord.HTTPException as e:
        log.warning("📬 Changelog-DM epäonnistui: %s – %s", username, e)

