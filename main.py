#!/usr/bin/env python3
import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import (
    FileCreatedEvent,
    FileMovedEvent,
    FileModifiedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

INBOX_HEADER = "## Inbox"
DAILY_FILENAME_FORMAT = "%Y-%m-%d"  # results in e.g. 2025-08-18.md
MD_EXTS = {".md", ".markdown"}
H1_RE = re.compile(r"^\s*#\s+(.+?)\s*$")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def today_stamp() -> str:
    # Use local time; if you prefer a fixed TZ, set TZ env or use zoneinfo
    return datetime.now().strftime(DAILY_FILENAME_FORMAT)


def daily_note_path(daily_dir: Path) -> Path:
    return daily_dir / f"{today_stamp()}.md"


def ensure_daily_note(daily_dir: Path) -> Path:
    p = daily_note_path(daily_dir)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        content = f"# {today_stamp()}\n\n{INBOX_HEADER}\n\n"
        p.write_text(content, encoding="utf-8")
    else:
        # Make sure the Inbox header exists somewhere
        text = p.read_text(encoding="utf-8")
        if INBOX_HEADER not in text:
            text = text.rstrip() + f"\n\n{INBOX_HEADER}\n\n"
            _atomic_write(p, text)
    return p


def _atomic_write(path: Path, content: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _is_note_from_today(path: Path) -> bool:
    """
    Notes are named YYYYMMDDHHMM.md.
    Return True iff the YYYYMMDD matches today's local date.
    Also tolerates temp prefixes like '.conform.123456.'.
    """
    name = path.name
    # strip temp prefix like ".conform.6798351."
    clean = re.sub(r"^\.conform\.\d+\.", "", name)
    m = re.fullmatch(r"(?P<ymd>\d{8})\d{4}\.md", clean)
    if not m:
        return False
    return m.group("ymd") == datetime.now().strftime("%Y%m%d")


def _normalize_md_link_url(url: str, base_dir: Path) -> str:
    # Ignore web links; they won’t match file paths anyway
    if url.startswith(("http://", "https://")):
        return url
    p = Path(url)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    else:
        p = p.resolve()
    return p.as_posix()


def add_link_under_inbox(daily_note: Path, title: str, link_url: str):
    """
    Insert '- [title](link_url)' under '## Inbox', de-duping by the normalized link target.
    """
    text = daily_note.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Locate '## Inbox'
    header_idx = None
    for i, line in enumerate(lines):
        if line.strip() == INBOX_HEADER:
            header_idx = i
            break
    if header_idx is None:
        lines += ["", INBOX_HEADER, ""]
        header_idx = len(lines) - 2

    # Range of the Inbox section
    next_header_idx = None
    for i in range(header_idx + 1, len(lines)):
        if lines[i].lstrip().startswith("#"):
            next_header_idx = i
            break
    start_idx = header_idx + 1
    end_idx = next_header_idx if next_header_idx is not None else len(lines)

    # Build a set of normalized existing link targets in the Inbox block
    inbox_block = lines[start_idx:end_idx]
    link_re = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    existing_targets = set()
    base_dir = daily_note.parent
    for ln in inbox_block:
        m = link_re.search(ln)
        if not m:
            continue
        existing_targets.add(_normalize_md_link_url(m.group(1).strip(), base_dir))

    new_target = _normalize_md_link_url(link_url, base_dir)
    if new_target in existing_targets:
        return  # already listed; do nothing

    bullet = f"- [{title}]({link_url})"

    # Keep a blank after the header, then insert
    insert_line = start_idx
    if start_idx < len(lines) and lines[start_idx].strip() != "":
        lines.insert(start_idx, "")
        insert_line += 1
        end_idx += 1

    lines.insert(insert_line, bullet)
    new_text = "\n".join(lines).rstrip() + "\n"
    _atomic_write(daily_note, new_text)


def derive_title_from_filename(path: Path) -> str:
    # Simple, predictable title: file stem with spaces instead of hyphens/underscores
    return path.stem.replace("_", " ").replace("-", " ").strip() or path.stem


def extract_h1_title(path: Path) -> str | None:
    """
    Return the first *level-1* Markdown heading (# Title) if present and non-empty.
    Ignore blank '#', ignore '## ...' or deeper.
    """
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = H1_RE.match(line)
                if m:
                    title = m.group(1).strip().strip("#").strip()
                    return title if title else None
    except Exception:
        # keep quiet or log if you added logging earlier
        return None
    return None


def is_markdown_file(path: Path) -> bool:
    return path.suffix.lower() in MD_EXTS


class NewFileHandler(FileSystemEventHandler):
    def __init__(self, watch_root: Path, daily_dir: Path, skip_daily_dir: bool):
        super().__init__()
        self.watch_root = watch_root.resolve()
        self.daily_dir = daily_dir.resolve()
        self.skip_daily_dir = skip_daily_dir

    def _maybe_add(self, new_path_str: str):
        # Guard: only act "today" and only on markdown files
        p = Path(new_path_str)
        if not p.exists() or not p.is_file():
            return
        if not is_markdown_file(p):
            return

        # Skip files inside the daily notes directory if requested
        if self.skip_daily_dir and self._is_in_daily_dir(p):
            return

        # Also don't link the daily note itself
        if p.resolve() == daily_note_path(self.daily_dir).resolve():
            return

        try:
            # Ensure the file is inside the watch root
            p.resolve().relative_to(self.watch_root)
        except ValueError:
            return

        if not _is_note_from_today(p):
            return

        h1_title = extract_h1_title(p)
        if not h1_title:
            return

        # Target daily note for "now"
        daily = ensure_daily_note(self.daily_dir)

        # Links should be relative to daily note directory so they work in editors like Obsidian
        # rel = _posix_relpath(p.resolve(), start=self.daily_dir)
        p_resolved = p.resolve()
        # p_resolved.relative_to(self.watch_root)
        vault_relative = p_resolved.relative_to(self.watch_root).as_posix()
        vault_relative = re.sub(r"\.conform\.\d+\.", "", vault_relative)
        # title = derive_title_from_header(p)

        add_link_under_inbox(daily, h1_title, vault_relative)

    def _is_in_daily_dir(self, p: Path) -> bool:
        try:
            p.resolve().relative_to(self.daily_dir)
            return True
        except ValueError:
            return False

    # New file created
    def on_created(self, event: FileCreatedEvent):
        if not event.is_directory:
            self._maybe_add(event.src_path)

    def on_modified(self, event: FileModifiedEvent):
        if not event.is_directory:
            self._maybe_add(event.src_path)

    # File moved into the tree
    def on_moved(self, event: FileMovedEvent):
        # If destination is within the watched tree, treat as new
        dest = Path(event.dest_path)
        try:
            dest.resolve().relative_to(self.watch_root.resolve())
            self._maybe_add(event.dest_path)
        except ValueError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Watch a directory and add new Markdown files to today's daily note under '## Inbox'."
    )
    parser.add_argument(
        "--watch-dir", required=True, help="Directory to watch (recursively)."
    )
    parser.add_argument(
        "--daily-dir",
        required=True,
        help="Directory where daily notes (YYYY-MM-DD.md) live.",
    )
    parser.add_argument(
        "--include-daily-dir",
        action="store_true",
        help="Allow links for files created inside the daily notes directory (default: skip).",
    )
    args = parser.parse_args()

    watch_root = Path(args.watch_dir).expanduser().resolve()
    daily_dir = Path(args.daily_dir).expanduser().resolve()
    if not watch_root.exists() or not watch_root.is_dir():
        logging.error(
            f"[fatal] watch-dir not found or not a directory: {watch_root}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Make sure today's note exists and has the Inbox
    ensure_daily_note(daily_dir)

    handler = NewFileHandler(
        watch_root, daily_dir, skip_daily_dir=not args.include_daily_dir
    )
    observer = Observer()
    observer.schedule(handler, str(watch_root), recursive=True)
    observer.start()
    logging.info(
        f"[ok] Watching {watch_root} -> daily notes in {daily_dir}. `systemctl --user stop obsidian-watcher.service`  to stop."
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
