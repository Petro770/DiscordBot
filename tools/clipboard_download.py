"""GUI:n leikepöytälatausten taustaprosessi."""
import asyncio
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

MAX_FILE_BYTES = 150_000_000
MEDIA_HOSTS = (
    "youtube.com", "youtu.be", "instagram.com", "x.com", "twitter.com", "fxtwitter.com",
    "t.co", "tiktok.com", "twitch.tv", "soundcloud.com", "soundcloud.app.goo.gl", "snd.sc",
)


def clipboard_url(text: str) -> str | None:
    url = text.strip()
    if not url or any(char.isspace() or ord(char) < 32 or char == "\\" for char in url):
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme not in {"http", "https"} or parts.username is not None:
            return None
    except ValueError:
        return None
    if any(host == domain or host.endswith("." + domain) for domain in MEDIA_HOSTS):
        return url
    return None


async def download_media(url: str, destination: Path, soundcloud_video: bool = True) -> Path:
    if clipboard_url(url) != url:
        raise ValueError("Kopioi tuettu medialinkki.")

    from downloaders import (
        download_instagram, download_tiktok, download_twitch, download_video, download_x,
        is_instagram, is_tiktok, is_twitch, is_x, is_youtube,
    )
    from downloaders.soundcloud import download_soundcloud, is_soundcloud

    routes = (
        (is_youtube, download_video), (is_instagram, download_instagram),
        (is_x, download_x), (is_tiktok, download_tiktok), (is_twitch, download_twitch),
        (is_soundcloud, download_soundcloud),
    )
    loader = next((download for matches, download in routes if matches(url)), None)
    if loader is None:
        raise ValueError("Linkistä ei tunnistettu tuettua mediaa.")
    media = await loader(url)
    if media is None:
        raise ValueError("Mediaa ei saatu ladattua.")

    original = Path(media.filepath)
    rendered = None
    try:
        if is_soundcloud(url) and soundcloud_video:
            from tools.soundcloud_video import make_soundcloud_video

            video_path = await make_soundcloud_video(
                str(original), media.artwork_url, media.title, media.uploader, MAX_FILE_BYTES,
            )
            if video_path is None:
                raise ValueError("SoundCloud-aaltomuotovideon luonti epäonnistui.")
            rendered = Path(video_path)
        with TemporaryDirectory(prefix="clipboard-") as folder:
            source = rendered or original
            if source.stat().st_size > MAX_FILE_BYTES and media.is_video:
                from tools.vid_compress import compress_to_720p

                source = Path(folder) / "compressed.mp4"
                compress_to_720p(
                    str(original.resolve()), str(source), target_size_mb=140,
                    passlog_prefix=str(Path(folder) / "ffmpeg2pass"),
                )
            if not 0 < source.stat().st_size <= MAX_FILE_BYTES:
                raise ValueError("Tiedosto on tyhjä tai ylittää 150 MB:n rajan.")
            destination.mkdir(parents=True)
            output = destination / f"media{source.suffix}"
            shutil.move(source, output)
            return output
    finally:
        original.unlink(missing_ok=True)
        if rendered is not None:
            rendered.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        asyncio.run(download_media(
            sys.argv[1], Path(sys.argv[2]), soundcloud_video="--soundcloud-mp3" not in sys.argv[3:],
        ))
    except Exception as error:
        print(f"LATAUSVIRHE={getattr(error, 'user_facing', '') or str(error)}", file=sys.stderr)
        sys.exit(1)
