# AgenTTasks

A minimal TUI task manager in a single Python file. No dependencies, no config, no database.

```
╭─ ◆ TASKS ────────────── all ─ active ─ done ───────────────────╮
│                                                                │
│ ▌ ◯  send invoice                                              │
│   ◯  fix landing page  ≡                                       │
│   ◯  call the client                                           │
│   ●  buy coffee                                                │
│                                                                │
╰───────────────────────────────────────────────────────── 1/4 ──╯
  a add  ·  e edit  ·  c context  ·  space done  ·  d delete  ·  u undo  ·  tab filter  ·  q quit
```

- **Fast capture:** `tt "send invoice"` adds a task without opening the UI, even while the UI is open.
- **Context notes:** attach a multi-line note to any task. It pops up as soon as you move onto it.
- **Plain JSON:** everything lives in `~/.tasks.json`.

## Requirements

- Python 3 (developed and tested on 3.12)
- macOS or Linux (uses `curses`). On Windows, use WSL.
- A font with `◯ ● ≡ ◆` and box-drawing characters. JetBrains Mono works well.

## Install

```bash
git clone https://github.com/alinayet/AgenTTasks.git
cd AgenTTasks
chmod +x tasks.py
```

Then add a shortcut to your shell config (`~/.zshrc` or `~/.bashrc`):

```bash
alias tt="python3 /full/path/to/AgenTTasks/tasks.py"
```

## Usage

```bash
tt                  # open the TUI
tt "send invoice"   # add a task without opening the TUI (quotes optional)
tt --help
```

A running TUI picks up tasks added from the command line within a fraction of a second, keeps your
selection where it was, and shows `+1 added` in the bottom border. New tasks go to the end of the
active list. Added tasks are never lost or undone, even if you're mid-edit when they arrive.

## Keys

| Key | Action |
| --- | --- |
| `j` `k` / arrows | move |
| `g` `G` | jump to top / bottom |
| `PgUp` `PgDn` | page up / down |
| `a` | add a task |
| `e` | edit the task's text |
| `c` | edit the task's context |
| `space` / `enter` | toggle done (done tasks sink to the bottom) |
| `d` | delete |
| `X` | clear all done tasks |
| `u` | undo (up to 100 steps) |
| `tab` / `shift+tab` | cycle `all` / `active` / `done` |
| `J` `K` | move the task down / up (in the `all` view, within active or done) |
| `q` | quit |

**Text input** (add / edit): `enter` saves, `esc` cancels. `ctrl+a` / `ctrl+e` jump to start / end,
`ctrl+u` deletes to the start, `ctrl+w` deletes a word.

**Context editor** (`c`): `enter` adds a new line, `esc` saves and closes, `ctrl+c` discards. Same
editing keys as above, plus up / down between lines. Long lines word-wrap.

## Context notes

Move onto a task that has context and a popup shows it on the right. Tasks with no context show
nothing. Tasks that have a note are marked with a dim `≡` after the title, so you know which ones to
hover. Press `c` to edit.

## Data

Tasks are stored in `~/.tasks.json`:

```json
[
  { "text": "send invoice", "done": false },
  { "text": "fix landing page", "done": false, "ctx": "Client wants it by Friday.\nCheck the mobile layout." },
  { "text": "buy coffee", "done": true }
]
```

`ctx` is optional. Writes are atomic, and the CLI and the TUI share a lock file
(`~/.tasks.json.lock`) so they never overwrite each other. If the file is not valid JSON, `tt "..."`
refuses to touch it.

## Customizing

Everything is constants near the top of `tasks.py`:

- **Colors:** `ACCENT, OK, DIM, BORDER, WARN, WHITE` are 256-color numbers. The default is a mono theme
  (`231` is pure white, `245` is grey).
- **Glyphs:** `BOX_OPEN`, `BOX_DONE` and `CTX_MARK`. Swap them if your font renders them oddly,
  for example `"○"` and `"●"`.

## License

Not specified yet. Add a `LICENSE` file if you want others to reuse it.
