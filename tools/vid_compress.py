"""Videokompressio Discordin tiedostorajaan."""
import json
import os
import subprocess


def get_media_info(input_path: str) -> tuple[float, int]:
    """Hakee videon keston ja ääniraidan bittivirran ffprobella."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", input_path,
    ]
    # ffprobe tuottaa UTF-8:aa, mutta Windowsin oletus-encoding voi olla
    # cp1252. Määritä encoding eksplisiittisesti, jotta subprocessin
    # reader-thread ei kaadu dekoodausvirheeseen.
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    if not result.stdout or not result.stdout.strip():
        raise RuntimeError("ffprobe ei palauttanut mediatietoja.")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe palautti virheellisen JSON-vastauksen.") from exc

    duration = float(data["format"]["duration"])
    audio_bitrate = 128_000

    for stream in data["streams"]:
        if stream["codec_type"] == "audio" and "bit_rate" in stream:
            audio_bitrate = int(stream["bit_rate"])
            break

    return duration, audio_bitrate


def compress_to_720p(input_path: str, output_path: str, target_size_mb: float = 9.2) -> str:
    """Kompressoi videon 720p-resoluutioon ja target-kokoon.

    Palauttaa tulostiedoston polun. Heittää Exception jos epäonnistuu.
    """
    duration, audio_bitrate = get_media_info(input_path)

    target_total_bits = target_size_mb * 8 * 1024 * 1024
    total_bitrate = target_total_bits / duration
    video_bitrate = int(total_bitrate - audio_bitrate)

    if video_bitrate < 100_000:
        raise ValueError(
            "Video on liian pitkä mahtuakseen rajalle edes minimilaadulla."
        )

    pass1_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", "scale=-2:720",
        "-c:v", "libx264", "-b:v", str(video_bitrate),
        "-pass", "1", "-an", "-f", "mp4", os.devnull,
    ]
    pass2_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", "scale=-2:720",
        "-c:v", "libx264", "-b:v", str(video_bitrate),
        "-pass", "2",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]

    subprocess.run(pass1_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    subprocess.run(pass2_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    return output_path


__all__ = ["compress_to_720p", "get_media_info"]
