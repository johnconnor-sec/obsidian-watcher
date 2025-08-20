# Obsidian Daily Note Watcher

Watches a vault directory for new Markdown notes.  
When a new note is created on the same day as the current daily note, its H1 heading is linked under the `## Inbox` section of that daily note.  
Notes must be named `YYYYMMDDHHMM.md`. Daily notes must be named `YYYY-MM-DD.md`.

## Requirements

- Python 3.9+
- watchdog (`pip install watchdog`)
- systemd (for running as a background service)

## Behavior

- Only Markdown files (`.md`, `.markdown`) are considered.
- Only notes with a non-empty H1 heading are added.
- Only notes from the same day as the daily note are added.
- Links are relative to the vault root.
- Duplicate links are not added.
- The daily note will be created if it does not exist.  
  `## Inbox` will be added if it is missing.

## Configuration

In `obsidian-watcher.service`:

```

# Edit these two paths to your setup

Environment=WATCH\_DIR=%h/Obsidian\_Vault
Environment=DAILY\_DIR=%h/Obsidian\_Vault/path/to/daily-notes

```

`WATCH_DIR` is the vault root.  
`DAILY_DIR` is the directory where daily notes are stored.

## Installation

1. Copy `main.py` to a stable path, e.g. `~/.local/bin/obsidian-watcher.py`.
2. Make it executable:

```

chmod +x \~/.local/bin/obsidian-watcher.py

```

3. Place `obsidian-watcher.service` into `~/.config/systemd/user/`.
4. Reload systemd:

```

systemctl --user daemon-reload

```

5. Enable service at login:

```

systemctl --user enable obsidian-watcher.service

```

### Service Management

Start:

```

systemctl --user start obsidian-watcher.service

```

Stop:

```

systemctl --user stop obsidian-watcher.service

```

Reload:

```

systemctl --user reload obsidian-watcher.service

```

Logs:

```

journalctl --user -u obsidian-watcher.service -f

```

## Notes

- If a note is created without a valid H1 heading, it will not be linked until the heading is added and the file is saved.
- Only notes created on the same day as the daily note are considered.
