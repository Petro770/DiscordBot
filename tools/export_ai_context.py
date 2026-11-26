"""Export selected project sources as one plain-text AI context file."""

import argparse
from fnmatch import fnmatchcase
from pathlib import Path
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
COMMON = ("AGENTS.md", "config.py", "example.env", "requirements.txt")
PROFILES = {
    "ollama": ("bot/ollama*.py", "bot/client.py", "instructions/discord-assistant.md", "tools/ai_monitor.py"),
    "gui": ("gui_launcher.py", "launch.ps1", "install.ps1", "tools/*dialog.py", "tools/env_editor.py",
            "tools/git_update.py", "tools/ai_monitor.py", "tools/clipboard_download.py",
            "tools/download_progress*.py", "tools/notification_sounds.py", "tools/soundcloud_video_preview.py"),
    "media": ("downloaders/*.py", "scrapers/*.py", "printer/*.py", "bot/handlers.py",
              "tools/clipboard_download.py", "tools/soundcloud*.py", "tools/vid_compress.py"),
    "all": ("*.py", "*.ps1", "README.md", "instructions/discord-assistant.md", "changelog.json"),
}


def tracked_files() -> set[str]:
    result = subprocess.run(
        ("git", "ls-files", "-z"), cwd=PROJECT, check=True, capture_output=True,
    )
    return {name for name in result.stdout.decode("utf-8").split("\0") if name}


def export(profile: str, include: list[str], with_tests: bool) -> str:
    tracked = tracked_files()
    patterns = (*COMMON, *PROFILES[profile])
    selected = {
        name for name in tracked
        if not name.startswith("tests/") and any(fnmatchcase(name, pattern) for pattern in patterns)
    }
    if with_tests:
        selected.update(name for name in tracked if name.startswith("tests/") and name.endswith(".py"))
    for name in include:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or path.as_posix() not in tracked:
            raise ValueError(f"Tiedoston pitää olla Gitissä seurattu projektitiedosto: {name}")
        selected.add(path.as_posix())

    sections = [f"DiscordBot · lähdekoodikooste · {profile}", *sorted(selected)]
    for name in sorted(selected):
        path = PROJECT / name
        if path.resolve() != path or not path.is_file():
            raise ValueError(f"Koontiin voi lisätä vain tavallisia projektitiedostoja: {name}")
        sections.append(f"\n===== {name} =====\n{path.read_text(encoding='utf-8-sig').rstrip()}")
    return "\n".join(sections) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", choices=PROFILES, default="ollama")
    parser.add_argument("--include", action="append", default=[], metavar="FILE")
    parser.add_argument("--with-tests", action="store_true")
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        bundle = export(args.profile, args.include, args.with_tests)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as file:
            file.write(bundle)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{args.output} ({len(bundle):,} merkkiä)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
