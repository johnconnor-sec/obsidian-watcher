# Obsidian Daily Note Watcher

A bespoke

> [!note]
> This is meant to be a simple background script to add some automation to a user of **CLI** based note-making applications like `obsidian.nvim`, `zk`, `vimwiki`, and others.
> This functionality is most likely achievable within the Obsidian application, and possibly within some of the CLI based applications.

Watches a vault directory for new Markdown notes.  
When a new note is created on the same day as the current daily note, its H1 heading is linked under the `## Inbox` section of that daily note.  
Notes must be named `YYYYMMDDHHMM.md`. Daily notes must be named `YYYY-MM-DD.md`.

## Requirements

- Python 3.9+
- watchdog (`uv add watchdog`)
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

{{...SNIP...}}

ExecStart=%h/path/to/obsidian-watcher/.venv/bin/python3.13 %h/path/to/obsidian-watcher/main.py --watch-dir ${WATCH_DIR} --daily-dir ${DAILY_DIR}
```

`WATCH_DIR` is the vault root.  
`DAILY_DIR` is the directory where daily notes are stored.
`ExecStart` is the path to your installation

> [!NOTE]
> The `%h` is there to tell systemd "start at the user's home directory".
> Do not paste your full path unless you install in a location other than `/home/$USER`

## Installation

1. Clone the repo: `git clone https://github.com/johnconnor-sec/obsidian-watcher`.
2. Run: `uv sync`.
3. Copy the path from your home directory to your cloned repo and replace `/patn/to` with it in the example below:
   `ExecStart=%h/path/to/obsidian-watcher/.venv/bin/python3.13 %h/path/to/obsidian-watcher/main.py --watch-dir ${WATCH_DIR} --daily-dir ${DAILY_DIR}` .
4. Place `obsidian-watcher.service` into `~/.config/systemd/user/`.
5. Reload systemd: `systemctl --user daemon-reload`
6. Enable service at login: `systemctl --user enable obsidian-watcher.service`

### Service Management

- Start: `systemctl --user start obsidian-watcher.service`
- Stop: `systemctl --user stop obsidian-watcher.service`
- Reload: `systemctl --user reload obsidian-watcher.service`
- Logs: `journalctl --user -u obsidian-watcher.service -f`

## Notes

- If a note is created without a valid H1 heading, it will not be linked until the heading is added and the file is saved.
- Only notes created on the same day as the daily note are considered.
