"""Safe Git operations for the desktop updater."""
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteBranch:
    name: str
    commit: str
    date: str
    author: str
    subject: str


class GitUpdate:
    def __init__(self, directory: Path):
        self.directory = directory

    def git(self, *arguments: str, allowed: tuple[int, ...] = (0,)) -> str:
        try:
            result = subprocess.run(
                ("git", *arguments), cwd=self.directory, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError(f"Git-komento epäonnistui: {exc}") from exc
        if result.returncode not in allowed:
            raise UpdateError(result.stderr.strip() or "Git-komento epäonnistui.")
        return result.stdout.strip()

    def current(self) -> tuple[str, str]:
        if Path(self.git("rev-parse", "--show-toplevel")).resolve() != self.directory.resolve():
            raise UpdateError("Hallintapaneeli pitää käynnistää projektin Git-kansiosta.")
        return self.git("branch", "--show-current"), self.git("rev-parse", "--short", "HEAD")

    def branches(self) -> list[RemoteBranch]:
        prefix = "refs/remotes/origin/"
        fields = "%(refname)%00%(objectname)%00%(symref)%00%(committerdate:short)%00%(authorname)%00%(subject)"
        refs = self.git("for-each-ref", "--sort=-committerdate", f"--format={fields}", prefix)
        branches = []
        for line in refs.split("\n") if refs else ():
            ref, commit, symbolic, date, author, subject = line.split("\0")
            if not symbolic:
                branches.append(RemoteBranch(ref.removeprefix(prefix), commit, date, author, subject))
        return branches

    def check(self, branch: str, commit: str) -> bool:
        current, _ = self.current()
        remote_commit = self.git(
            "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", allowed=(0, 1),
        )
        if remote_commit != commit:
            raise UpdateError("Etähaara muuttui tarkistuksen jälkeen. Tarkista versio uudelleen.")
        if self.git("status", "--porcelain", "--untracked-files=normal"):
            raise UpdateError("Projektissa on paikallisia muutoksia. Tallenna ne ennen päivitystä.")
        for state in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
            path = Path(self.git("rev-parse", "--git-path", state))
            if (self.directory / path).exists():
                raise UpdateError("Gitissä on keskeneräinen operaatio. Viimeistele se ennen päivitystä.")
        try:
            self.git("cat-file", "-e", f"{commit}:gui_launcher.py")
        except UpdateError as exc:
            raise UpdateError("Valitusta haarasta puuttuu hallintapaneelin käynnistystiedosto.") from exc
        ref = f"refs/heads/{branch}"
        local = self.git("rev-parse", "--verify", "--quiet", ref, allowed=(0, 1))
        if local and self.git("merge-base", local, commit, allowed=(0, 1)) != local:
            raise UpdateError(f"Haarassa {branch} on paikallisia committeja. Yhdistä ne Gitillä ennen päivitystä.")
        return current != branch or local != commit

    def apply(self, branch: str, commit: str):
        if not self.check(branch, commit):
            return
        local = self.git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", allowed=(0, 1))
        if local:
            self.git("switch", "--no-guess", "--no-overwrite-ignore", "--", branch)
            if local != commit:
                self.git("merge", "--ff-only", "--no-overwrite-ignore", commit)
        else:
            self.git("switch", "--no-overwrite-ignore", "--create", branch, "--track", f"origin/{branch}")
