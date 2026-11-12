"""Yhteiset dataclassit bottin käyttöön."""
import re
import random
from dataclasses import dataclass, field
from collections import Counter

class NonRetryableError(Exception):
    """Virhe josta ei ole hyötyä uudelleenyrityksellä (private, poistettu jne.)."""

    def __init__(self, message: str, user_facing: str = ""):
        super().__init__(message)
        self.user_facing = user_facing or message


# ============================================================
# HASHTAGIEN KÄSITTELY
# ============================================================

_HASHTAG_RE = re.compile(r"#(\w+)")

def extract_hashtags(*texts: str) -> list[str]:
    """Poimii uniikit hashtagit teksteistä säilyttäen järjestyksen."""
    seen: set[str] = set()
    tags: list[str] = []
    for text in texts:
        for match in _HASHTAG_RE.finditer(text):
            tag = f"#{match.group(1)}"
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags

def strip_hashtags(text: str) -> str:
    """Poistaa hashtagit tekstistä ja siivoo jäljelle jäävät välilyönnit."""
    cleaned = _HASHTAG_RE.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


# ============================================================
# SPÄMMI / TOISTUVA SISÄLTÖ
# ============================================================

def poista_toistuvat_paikat(text: str, max_chunk_len: int = 20) -> str:
    """Poistaa peräkkäin toistuvat merkkijonot.

    Esimerkkejä:
        "abcabc"       → "abc"
        "testitesti"   → "testi"
        "###"          → "#"
        "aabaab"       → "aab"
    """
    pattern = r'(.{1,' + str(max_chunk_len) + r'})\1+'
    return re.sub(pattern, r'\1', text)

def poista_rivispaami(text: str, max_line_len: int = 3, min_repeat: int = 3) -> str:
    """Poistaa lyhyet rivit jotka toistuvat useita kertoja (spämmi).

    Esimerkki:
        "Call of duty : .\n.\n.\n.\n.\n."  →  "Call of duty : ."

    Parametrit:
        max_line_len: kuinka pitkää riviä pidetään "spämmikehyttynä" (default 3)
        min_repeat:  kuinka monta kertaa pitää toistua jotta se poistetaan (default 3)
    """
    lines = text.split("\n")

    # Lasketaan lyhyiden rivien esiintymät (stripattu versio)
    short_lines = [l.strip() for l in lines if len(l.strip()) <= max_line_len]
    counts = Counter(short_lines)

    # Spämmi = lyhyt rivi joka esiintyy ≥ min_repeat kertaa
    spam = {line for line, count in counts.items() if count >= min_repeat}

    # Suodata pois
    cleaned = [l for l in lines if l.strip() not in spam]

    # Siivoa peräkkäiset tyhjät rivit + alku/päätteet
    result = re.sub(r"\n{2,}", "\n", "\n".join(cleaned)).strip()
    return result

# ============================================================
# EMBED-ESTO
# ============================================================

_URL_RE = re.compile(r"(?<!<)(https?://[^\s<>\"'\[\]()]+)(?!>)")

def _disable_embeds(text: str) -> str:
    """Wrappaa raaka-URL:t < > -merkkeihin, jotta Discord ei embedoi niitä."""
    return _URL_RE.sub(r"<\1>", text)


# ============================================================
# VIDEOINFO
# ============================================================

@dataclass
class VideoInfo:
    """Videon tiedot + metadata Discord-viestiin."""
    filepath: str
    filename: str
    title: str = ""
    uploader: str = ""
    description: str = ""
    source_url: str = ""
    is_video: bool = True

    def format_message(self, max_desc_len: int = 300, max_tags: int = 15) -> str:
        """Muodosta Discord-viestin sisältö metadatalle.

        Discordin viestiraja on 2000 merkkiä – jätä tilaa tiedostolle.
        """
        parts: list[str] = []

        link_terms = ["Linkki", "Original", "OG", "Alkuperäinen",
            "Lähde", "Alkuperäinen linkki", "Avaruuslähde",
            "Glorpattu linkki", "Alkuperäinen signaali",
            "Kotiplaneetan data", "Madonreikä", "Emäaluksen arkisto",
            "Valovuosilinkki", "Kosminen url", "Telepatialinkki",
            "Sädehoitolähde"]

        ufo_emojis = ["🛸", "👽", "📡", "🪐", "☄️", "🔋", "🚀", "🔗"]

        # --- Otsikko ---
        clean_title = strip_hashtags(self.title)
        if clean_title:
            parts.append(f"**{clean_title}**")

        # --- Julkaisija ---
        if self.uploader:
            parts.append(f"👤 {self.uploader}")

        # --- Kuvaus (siivottu + spämmifiltterit) ---
        clean_desc = strip_hashtags(self.description)
        if clean_desc:
            clean_desc = poista_toistuvat_paikat(clean_desc)
            clean_desc = poista_rivispaami(clean_desc)
            clean_desc = re.sub(r"\s{2,}", " ", clean_desc).strip()
            if clean_desc:
                if len(clean_desc) > max_desc_len:
                    clean_desc = clean_desc[:max_desc_len - 1] + "…"
                parts.append(f"💬 {_disable_embeds(clean_desc)}")

        # --- Hashtagit ---
        tags = extract_hashtags(self.title, self.description)
        if tags:
            tag_str = " ".join(tags[:max_tags])
            if len(tags) > max_tags:
                tag_str += f" +{len(tags) - max_tags}"
            parts.append(f"🏷️ {tag_str}")

        # --- Linkki ---
        random_term = random.choice(link_terms)
        random_emoji = random.choice(ufo_emojis)
        if self.source_url:
            parts.append(f"{random_emoji} [{random_term}]({_disable_embeds(self.source_url)})")

        result = "\n".join(parts) if parts else ""

        if len(result) > 1980:
            result = result[:1977] + "…"
        return result

