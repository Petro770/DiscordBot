"""SQLite index of attachment fingerprints and channel history progress."""

from contextlib import closing
from dataclasses import dataclass
from heapq import nsmallest
from pathlib import Path
import sqlite3
from typing import BinaryIO

import imagehash
from PIL import Image, ImageOps


@dataclass(frozen=True)
class Fingerprint:
    sha256: bytes
    phash: bytes | None = None
    color_grid: bytes | None = None
    width: int | None = None
    height: int | None = None


def fingerprint(file: BinaryIO, digest: bytes) -> Fingerprint:
    """Read a static image, preserving the exact hash for all file types."""
    try:
        with Image.open(file) as image:
            if getattr(image, "is_animated", False):
                return Fingerprint(digest)
            # Apply EXIF orientation and use a fixed background for transparency.
            oriented = ImageOps.exif_transpose(image).convert("RGBA")
            rgb = Image.new("RGB", oriented.size, "white")
            rgb.paste(oriented, mask=oriented.getchannel("A"))
            phash = bytes.fromhex(str(imagehash.phash(rgb)))
            grid = rgb.resize((4, 4), Image.Resampling.BOX).tobytes()
            return Fingerprint(digest, phash, grid, *rgb.size)
    except (OSError, ValueError, Image.DecompressionBombError):
        return Fingerprint(digest)


@dataclass(frozen=True)
class Match:
    message_id: int
    exact: bool
    bit_distance: int = 0
    color_distance: float = 0


class AttachmentIndex:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS attachments (
                    channel_id INTEGER NOT NULL,
                    attachment_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    sha256 BLOB NOT NULL,
                    phash BLOB,
                    color_grid BLOB,
                    width INTEGER,
                    height INTEGER,
                    PRIMARY KEY (channel_id, attachment_id)
                );
                CREATE INDEX IF NOT EXISTS attachments_by_hash
                    ON attachments (channel_id, sha256, message_id);
                CREATE TABLE IF NOT EXISTS history_progress (
                    channel_id INTEGER PRIMARY KEY,
                    message_id INTEGER NOT NULL
                );
            """)

    def contains(self, channel_id: int, attachment_id: int) -> bool:
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute(
                "SELECT 1 FROM attachments WHERE channel_id = ? AND attachment_id = ?",
                (channel_id, attachment_id),
            ).fetchone() is not None

    def save(self, channel_id: int, message_id: int, attachment_id: int,
             filename: str, image: Fingerprint) -> bool:
        with closing(sqlite3.connect(self.path)) as db, db:
            result = db.execute("""
                INSERT INTO attachments
                    (channel_id, attachment_id, message_id, filename,
                     sha256, phash, color_grid, width, height)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (channel_id, attachment_id) DO NOTHING
            """, (channel_id, attachment_id, message_id, filename, image.sha256,
                  image.phash, image.color_grid, image.width, image.height))
            return result.rowcount == 1

    def history_position(self, channel_id: int) -> int | None:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT message_id FROM history_progress WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()
            return row[0] if row else None

    def advance_history(self, channel_id: int, message_id: int) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""
                INSERT INTO history_progress (channel_id, message_id) VALUES (?, ?)
                ON CONFLICT (channel_id) DO UPDATE SET
                    message_id = MAX(history_progress.message_id, excluded.message_id)
            """, (channel_id, message_id))

    def find(self, channel_id: int, image: Fingerprint) -> list[Match]:
        with closing(sqlite3.connect(self.path)) as db:
            exact = [
                Match(message_id, exact=True)
                for message_id, in db.execute("""
                    SELECT DISTINCT message_id FROM attachments
                    WHERE channel_id = ? AND sha256 = ?
                    ORDER BY message_id DESC LIMIT 10
                """, (channel_id, image.sha256))
            ]
            if image.phash is None or image.color_grid is None or len(exact) == 10:
                return exact

            rows = db.execute("""
                SELECT message_id, phash, color_grid FROM attachments
                WHERE channel_id = ? AND phash IS NOT NULL AND sha256 != ?
            """, (channel_id, image.sha256))
            target_hash = int.from_bytes(image.phash, "big")
            exact_ids = {match.message_id for match in exact}
            best_by_message = {}
            for message_id, phash, grid in rows:
                if message_id in exact_ids:
                    continue
                distance = (target_hash ^ int.from_bytes(phash, "big")).bit_count()
                if distance > 8:
                    continue
                color_distance = sum(abs(a - b) for a, b in zip(image.color_grid, grid)) / len(grid)
                if color_distance > 20:
                    continue
                previous = best_by_message.get(message_id)
                if previous is None or (distance, color_distance) < (
                    previous.bit_distance, previous.color_distance
                ):
                    best_by_message[message_id] = Match(message_id, False, distance, color_distance)

            similar = nsmallest(
                10 - len(exact), best_by_message.values(),
                key=lambda match: (match.bit_distance, match.color_distance, -match.message_id),
            )
            return exact + similar
