# AgenTTasks

A polished, dependency-free TUI task manager in a single Python file.

Tasks live in `~/.tasks.json`. No packages to install, no database, no config —
just Python's standard library and a terminal.

```
╭──────────────────────────────────────────╮
│  ◯  write the readme                     │
│  ◯  ship it                          ≡    │
│  ●  buy coffee                           │
╰──────────────────────────────────────────╯
```

## Requirements

- Python 3.8+
- A terminal with `curses` (macOS and Linux out of the box)
- On Windows: `pip install windows-curses`

## Install

```bash
git clone git@github.com:alinayet/AgenTTasks.git
cd AgenTTasks
chmod +x tasks.py
```

Then put it somewhere on your `PATH`. For example:

```bash
ln -s "$PWD/tasks.py" ~/.local/bin/tt
```

## Usage

```bash
tt              # open the TUI
tt "some task"  # add a task without opening the TUI
tt --help
```

Adding from the CLI is safe while the TUI is running — a live TUI picks up new
tasks within a fraction of a second and merges them without losing your place.
File locking keeps the CLI and the TUI from writing over each other.

## Keys

### List

| Key | Action |
| --- | --- |
| `a` / `n` | add a task |
| `e` / `r` | edit the selected task's text |
| `c` | edit the selected task's context note |
| `space` / `enter` | toggle done |
| `d` / `x` / `del` | delete task |
| `X` | clear all done tasks |
| `u` | undo |
| `tab` / `f` | cycle filter (all → active → done) |
| `shift+tab` | cycle filter backwards |
| `j` / `k` / arrows | move selection |
| `g` / `G` / home / end | jump to top / bottom |
| `pgup` / `pgdn` | page up / down |
| `J` / `K` | reorder within the active or done group |
| `q` / `ctrl+c` | quit |

### Context editor

Each task can carry a free-form multi-line context note, shown as `≡` next to
the task and previewed on hover.

| Key | Action |
| --- | --- |
| `esc` | save and close |
| `enter` | new line |
| `ctrl+c` | discard |

## Behaviour worth knowing

- **Done tasks sink.** Active tasks stay on top; completing a task moves it to
  the bottom group. Order within each group is preserved.
- **Undo is 100 tasks deep.** Every mutation snapshots state first.
- **External additions are merged**, not overwritten, so `tt "..."` from another
  pane never clobbers an open TUI's work.
- **Corrupt data is protected.** If `~/.tasks.json` isn't valid JSON, the CLI
  refuses to write rather than silently destroying it.
- **Atomic saves.** Writes go to a temp file and are `os.replace`d into place.

## Data format

`~/.tasks.json` is a plain JSON array:

```json
[
  { "text": "write the readme", "done": false },
  { "text": "ship it", "done": false, "ctx": "needs a tag first" },
  { "text": "buy coffee", "done": true }
]
```

`ctx` is optional and omitted when empty. Older files without `ctx` load fine,
so the format stays backward compatible.

## License

MIT
