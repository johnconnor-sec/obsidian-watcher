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
SAVED_ARTICLES_HEADER = "### Saved Articles"
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


def _header_level(line: str) -> int | None:
    s = line.lstrip()
    if not s.startswith("#"):
        return None
    return len(s) - len(s.lstrip("#"))


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


def add_link_under_inbox(
    daily_note: Path, title: str, link_url: str, sub_header: str | None = None
):
    """
    Insert '- [title](link_url)' under '## Inbox'. If sub_header is provided (e.g., '### Saved Articles'),
    insert under that sub-section (creating it if missing). De-duplicate by normalized link target within
    the chosen block. Inbox ends only at the next header of level <= 2. The sub-section ends at the next
    header of level <= the sub-section level.
    """
    text = daily_note.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 1) Locate or create '## Inbox'
    inbox_idx = None
    for i, line in enumerate(lines):
        if line.strip() == INBOX_HEADER:
            inbox_idx = i
            break
    if inbox_idx is None:
        lines += ["", INBOX_HEADER, ""]
        inbox_idx = len(lines) - 2

    # Compute Inbox block: from after '## Inbox' until next header with level <= 2
    inbox_start = inbox_idx + 1
    inbox_end = len(lines)
    for i in range(inbox_start, len(lines)):
        lvl = _header_level(lines[i])
        if lvl is not None and lvl <= 2:
            inbox_end = i
            break

    # 2) If a sub_header is requested, locate/create it inside the Inbox block
    block_start, block_end = inbox_start, inbox_end
    if sub_header:
        # Determine the sub_header level (count '#')
        sub_level = _header_level(sub_header) or 3  # '### Saved Articles' -> 3

        # Find existing sub_header within the Inbox range
        sub_idx = None
        for i in range(inbox_start, inbox_end):
            if lines[i].strip() == sub_header:
                sub_idx = i
                break

        if sub_idx is None:
            # Ensure a blank immediately after '## Inbox'
            insert_at = inbox_start
            if insert_at < len(lines) and lines[insert_at].strip() != "":
                lines.insert(insert_at, "")
                insert_at += 1
                inbox_end += 1  # shift end since we inserted inside Inbox

            # Insert the sub_header and a following blank
            lines.insert(insert_at, sub_header)
            lines.insert(insert_at + 1, "")
            sub_idx = insert_at
            inbox_end += 2  # account for the two inserted lines

        # Sub-block runs until next header with level <= sub_level or end of Inbox block
        block_start = sub_idx + 1
        block_end = inbox_end
        for i in range(block_start, inbox_end):
            lvl = _header_level(lines[i])
            if lvl is not None and lvl <= sub_level:
                block_end = i
                break

    # 3) De-duplicate by normalized link target inside the chosen block
    inbox_block = lines[block_start:block_end]
    link_re = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    existing_targets = set()
    base_dir = daily_note.parent
    for ln in inbox_block:
        m = link_re.search(ln)
        if m:
            existing_targets.add(_normalize_md_link_url(m.group(1).strip(), base_dir))

    new_target = _normalize_md_link_url(link_url, base_dir)
    if new_target in existing_targets:
        return  # already present in this block

    bullet = f"- [{title}]({link_url})"

    # Keep a blank line at the start of the chosen block for readability
    insert_line = block_start
    if insert_line < len(lines) and lines[insert_line].strip() != "":
        lines.insert(insert_line, "")
        insert_line += 1
        # Adjust block_end since we inserted within it
        block_end += 1
        if sub_header is None:
            inbox_end += 1

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
        p_resolved = p.resolve()
        vault_relative = p_resolved.relative_to(self.watch_root).as_posix()
        vault_relative = re.sub(r"\.conform\.\d+\.", "", vault_relative)
        # title = derive_title_from_header(p)

        # Decide destination: RSS files go under '### Saved Articles' inside Inbox
        rel_from_vault = p_resolved.relative_to(self.watch_root).as_posix()
        is_rss = rel_from_vault.startswith("Inbox/RSS_Feed/")

        sub_header = SAVED_ARTICLES_HEADER if is_rss else None
        add_link_under_inbox(daily, h1_title, vault_relative, sub_header=sub_header)

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
        f"[ok] Watching {watch_root} -> daily notes in {daily_dir}. `systemctl --user stop obsidian-watcher.service` to stop."
    )
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
