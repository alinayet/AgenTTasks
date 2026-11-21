#!/usr/bin/env python3
"""tasks - a polished, dependency-free TUI task manager.

Data lives in ~/.tasks.json.  Each task: {"text", "done", "ctx"?}
Old files load fine; "ctx" (the context note) is optional.

Usage:
  tasks.py              open the TUI
  tasks.py "some task"  add a task without opening the TUI (a running TUI picks it up live)
"""
import copy
import curses
import json
import locale
import os
import sys
from collections import Counter
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # no file locking available (not an issue on macOS/Linux)
    fcntl = None

PATH = os.path.expanduser("~/.tasks.json")
FILTERS = ("all", "active", "done")

# Mono theme: pure white (#FFFFFF) for borders/emphasis, grey for everything else
ACCENT, OK, DIM, BORDER, WARN, WHITE = 231, 231, 245, 231, 250, 231

# glyphs - swap here if your font renders them oddly
BOX_OPEN, BOX_DONE = "◯", "●"
CTX_MARK = "≡"  # shown after tasks that have context


# ───────────────────────────── storage ─────────────────────────────
def sink_done(tasks):
    """Active tasks first, done tasks last (stable)."""
    return [t for t in tasks if not t["done"]] + [t for t in tasks if t["done"]]


def load(strict=False):
    try:
        with open(PATH, encoding="utf-8") as f:
            data = json.load(f)
        tasks = [
            {
                "text": str(t.get("text", "")),
                "done": bool(t.get("done")),
                "ctx": str(t.get("ctx", "")),
            }
            for t in data
            if isinstance(t, dict)
        ]
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, TypeError):
        if strict:
            raise
        return []
    return sink_done(tasks)


def save(tasks):
    out = [{k: v for k, v in t.items() if k != "ctx" or v.strip()} for t in tasks]
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    os.replace(tmp, PATH)


def file_mtime():
    try:
        return os.stat(PATH).st_mtime_ns
    except FileNotFoundError:
        return None


def task_key(t):
    return (t["text"], t["done"], t["ctx"])


@contextmanager
def locked():
    """Cross-process lock so the CLI and the TUI never write at the same time."""
    if fcntl is None:
        yield
        return
    with open(PATH + ".lock", "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def cli_add(text):
    text = text.strip()
    if not text:
        print('usage: tt "task text"', file=sys.stderr)
        return 1
    with locked():
        try:
            tasks = load(strict=True)
        except (json.JSONDecodeError, TypeError):
            print(f"error: {PATH} is not valid JSON, refusing to overwrite it", file=sys.stderr)
            return 1
        tasks.insert(sum(not t["done"] for t in tasks), {"text": text, "done": False, "ctx": ""})
        save(tasks)
    print(f"+ {text}")
    return 0


def fit(s, n):
    if n <= 0:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


# ───────────────────── word-wrap + multiline editor ─────────────────────
def wrap_ranges(line, w):
    """Split one logical line into contiguous (start, end) index ranges <= w wide."""
    if not line:
        return [(0, 0)]
    out, i, n = [], 0, len(line)
    while i < n:
        if n - i <= w:
            out.append((i, n))
            break
        j = i + w
        k = line.rfind(" ", i + 1, j + 1)
        e = k + 1 if k > i else j
        out.append((i, e))
        i = e
    return out


def layout(lines, w):
    return [(r, s, e) for r, line in enumerate(lines) for s, e in wrap_ranges(line, w)]


def cursor_visual(vis, r, c):
    best = 0
    for idx, (rr, s, _e) in enumerate(vis):
        if rr == r and s <= c:
            best = idx
    return best, c - vis[best][1]


class Editor:
    def __init__(self, text):
        self.lines = text.split("\n") if text else [""]
        self.r = len(self.lines) - 1
        self.c = len(self.lines[-1])
        self.top = 0
        self.w = 30

    def text(self):
        return "\n".join(self.lines).strip()

    def insert(self, s):
        ln = self.lines[self.r]
        self.lines[self.r] = ln[: self.c] + s + ln[self.c :]
        self.c += len(s)

    def newline(self):
        ln = self.lines[self.r]
        self.lines[self.r] = ln[: self.c]
        self.lines.insert(self.r + 1, ln[self.c :])
        self.r += 1
        self.c = 0

    def backspace(self):
        if self.c > 0:
            ln = self.lines[self.r]
            self.lines[self.r] = ln[: self.c - 1] + ln[self.c :]
            self.c -= 1
        elif self.r > 0:
            prev = self.lines[self.r - 1]
            self.c = len(prev)
            self.lines[self.r - 1] = prev + self.lines[self.r]
            del self.lines[self.r]
            self.r -= 1

    def delete(self):
        ln = self.lines[self.r]
        if self.c < len(ln):
            self.lines[self.r] = ln[: self.c] + ln[self.c + 1 :]
        elif self.r < len(self.lines) - 1:
            self.lines[self.r] = ln + self.lines[self.r + 1]
            del self.lines[self.r + 1]

    def left(self):
        if self.c > 0:
            self.c -= 1
        elif self.r > 0:
            self.r -= 1
            self.c = len(self.lines[self.r])

    def right(self):
        if self.c < len(self.lines[self.r]):
            self.c += 1
        elif self.r < len(self.lines) - 1:
            self.r += 1
            self.c = 0

    def home(self):
        self.c = 0

    def end(self):
        self.c = len(self.lines[self.r])

    def kill_to_start(self):
        self.lines[self.r] = self.lines[self.r][self.c :]
        self.c = 0

    def kill_word(self):
        ln, j = self.lines[self.r], self.c
        while j > 0 and ln[j - 1] == " ":
            j -= 1
        while j > 0 and ln[j - 1] != " ":
            j -= 1
        self.lines[self.r] = ln[:j] + ln[self.c :]
        self.c = j

    def move_v(self, dy):
        vis = layout(self.lines, self.w)
        idx, dc = cursor_visual(vis, self.r, self.c)
        ni = idx + dy
        if not 0 <= ni < len(vis):
            return
        rr, s, e = vis[ni]
        is_last = ni + 1 == len(vis) or vis[ni + 1][0] != rr
        self.r = rr
        self.c = min(s + dc, e if is_last else max(s, e - 1))


def hint_width(hs):
    return sum(len(k) + 1 + len(l) for k, l in hs) + 5 * (len(hs) - 1)


# ─────────────────────────────── app ───────────────────────────────
class App:
    def __init__(self, scr):
        self.scr = scr
        self.tasks = load()
        self.base = copy.deepcopy(self.tasks)  # last state we know is on disk
        self.mtime = file_mtime()
        self.sel = 0
        self.top = 0
        self.filter = 0
        self.history = []
        self.msg = ""
        self.list_h = 10
        self.pairs = {}
        self.init_colors()

    # ---- colours -----------------------------------------------------
    def init_colors(self):
        curses.start_color()
        try:
            curses.use_default_colors()
            self.fg = self.bg = -1
        except curses.error:
            self.fg, self.bg = curses.COLOR_WHITE, curses.COLOR_BLACK
        hi = curses.COLORS >= 256
        self.c = dict(
            accent=ACCENT if hi else curses.COLOR_WHITE,
            ok=OK if hi else curses.COLOR_WHITE,
            dim=DIM if hi else curses.COLOR_WHITE,
            border=BORDER if hi else curses.COLOR_WHITE,
            warn=WARN if hi else curses.COLOR_WHITE,
            white=WHITE if hi else curses.COLOR_WHITE,
        )
        self.dim_extra = 0 if hi else curses.A_DIM

    def cp(self, fg, bg=None):
        bg = self.bg if bg is None else bg
        key = (fg, bg)
        if key not in self.pairs:
            n = len(self.pairs) + 1
            curses.init_pair(n, fg, bg)
            self.pairs[key] = n
        return curses.color_pair(self.pairs[key])

    @property
    def dim(self):
        return self.cp(self.c["dim"]) | self.dim_extra

    # ---- drawing helpers ---------------------------------------------
    def put(self, y, x, s, attr=0):
        H, W = self.scr.getmaxyx()
        if y < 0 or y >= H or x < 0 or x >= W:
            return
        try:
            self.scr.addstr(y, x, s[: W - x], attr)
        except curses.error:
            pass

    def view(self):
        f = FILTERS[self.filter]
        return [
            i
            for i, t in enumerate(self.tasks)
            if f == "all" or (f == "active" and not t["done"]) or (f == "done" and t["done"])
        ]

    def current(self):
        v = self.view()
        return v[self.sel] if v and 0 <= self.sel < len(v) else None

    def hint_bar(self, y, hints, x0, pw):
        accent = self.cp(self.c["accent"]) | curses.A_BOLD
        sep = self.dim
        x = x0 + max(0, (pw - hint_width(hints)) // 2)
        for i, (k, l) in enumerate(hints):
            self.put(y, x, k, accent)
            self.put(y, x + len(k) + 1, l, self.dim)
            x += len(k) + 1 + len(l)
            if i < len(hints) - 1:
                self.put(y, x, "  ·  ", sep)
                x += 5

    def draw(self, prompt=None, editor=None):
        scr, c = self.scr, self.c
        scr.erase()
        H, W = scr.getmaxyx()
        if H < 8 or W < 34:
            self.put(0, 0, "terminal too small", self.dim)
            scr.refresh()
            return

        pw, ph = W, H - 2            # full width; last row is the hint bar
        x0, y0 = 0, 0
        iw = pw - 2
        list_h = ph - 4              # border, pad, ...rows..., pad, border
        self.list_h = list_h
        bd = self.cp(c["border"])
        accent = self.cp(c["accent"])
        white = self.cp(c["white"])
        cursor = None

        # frame (single rounded border, no inner separators)
        self.put(y0, x0, "╭" + "─" * iw + "╮", bd)
        for y in range(y0 + 1, y0 + ph - 1):
            self.put(y, x0, "│", bd)
            self.put(y, x0 + pw - 1, "│", bd)
        self.put(y0 + ph - 1, x0, "╰" + "─" * iw + "╯", bd)

        # title (left) + filter tabs (centered), both in the top border
        self.put(y0, x0 + 2, " ◆ TASKS ", white | curses.A_BOLD)
        tabs_w = sum(len(n) + 2 for n in FILTERS) + len(FILTERS) - 1
        if pw >= tabs_w + 26:
            x = x0 + (pw - tabs_w) // 2
            for i, name in enumerate(FILTERS):
                s = f" {name} "
                self.put(y0, x, s, white if i == self.filter else self.dim)
                x += len(s) + 1

        # selection / scrolling
        view = self.view()
        n = len(view)
        self.sel = max(0, min(self.sel, n - 1)) if n else 0
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + list_h:
            self.top = self.sel - list_h + 1
        self.top = max(0, min(self.top, max(0, n - list_h)))

        # context popup geometry: only for a task that has context (or while editing)
        cur = self.current()
        ctx = self.tasks[cur]["ctx"] if cur is not None else ""
        pop = None
        if prompt is None and (editor is not None or ctx.strip()):
            pop_w = min(min(max(28, pw * 36 // 100), 64), pw - 8)
            pop_h = min(max(7, ph * 60 // 100), ph - 2)
            if pop_w >= 16 and pop_h >= 4:
                py = max(1, min(ph * 20 // 100, ph - 1 - pop_h))
                pop = (x0 + pw - 6 - pop_w, y0 + py, pop_w, pop_h)

        if n == 0:
            title, hint = {
                "all": ("Nothing to do.", "press  a  to add a task"),
                "active": ("No active tasks.", "everything is done"),
                "done": ("Nothing completed yet.", "press  space  on a task"),
            }[FILTERS[self.filter]]
            cy = y0 + 2 + list_h // 2 - 1
            self.put(cy, (pw - len(title)) // 2, title, white)
            self.put(cy + 1, (pw - len(hint)) // 2, hint, self.dim)

        # list
        for r in range(list_h):
            idx = self.top + r
            if idx >= n:
                break
            t = self.tasks[view[idx]]
            y = y0 + 2 + r
            if idx == self.sel:
                self.put(y, x0 + 2, "▌", accent | curses.A_BOLD)
            if t["done"]:
                self.put(y, x0 + 4, BOX_DONE, white)
                tattr = self.dim
            else:
                self.put(y, x0 + 4, BOX_OPEN, accent)
                tattr = self.cp(self.fg)
            tx = x0 + 7
            text_w = pw - 11
            if pop and pop[1] <= y < pop[1] + pop[3]:
                text_w = min(text_w, pop[0] - 2 - tx)
            has_ctx = bool(t.get("ctx", "").strip())
            shown = fit(t["text"], text_w - (3 if has_ctx else 0))
            self.put(y, tx, shown, tattr)
            if has_ctx:
                self.put(y, tx + len(shown) + 2, CTX_MARK, self.dim)

        # scrollbar (only when the list overflows)
        if n > list_h:
            th = max(1, list_h * list_h // n)
            tt = (list_h - th) * self.top // max(1, n - list_h)
            for r in range(th):
                self.put(y0 + 2 + tt + r, x0 + pw - 1, "┃", accent)

        # bottom border: message left, done/total right
        by = y0 + ph - 1
        if self.msg:
            self.put(by, x0 + 3, f" {self.msg} ", self.cp(c["warn"]))
        total = len(self.tasks)
        done = sum(t["done"] for t in self.tasks)
        if total:
            cnt = f" {done}/{total} "
            col = self.cp(c["ok"]) if done == total else self.dim
            self.put(by, x0 + pw - 3 - len(cnt), cnt, col)

        # context popup (preview on hover, editor on "c")
        if pop:
            px, py, qw, qh = pop
            tw, th = qw - 4, qh - 2
            pb = accent
            for yy in range(py, py + qh):
                self.put(yy, px, " " * qw)
            self.put(py, px, "╭" + "─" * (qw - 2) + "╮", pb)
            for yy in range(py + 1, py + qh - 1):
                self.put(yy, px, "│", pb)
                self.put(yy, px + qw - 1, "│", pb)
            self.put(py + qh - 1, px, "╰" + "─" * (qw - 2) + "╯", pb)
            self.put(py, px + 2, " context ", white | curses.A_BOLD)
            if editor is not None:
                editor.w = tw
                vis = layout(editor.lines, tw)
                vi, dc = cursor_visual(vis, editor.r, editor.c)
                if vi < editor.top:
                    editor.top = vi
                if vi >= editor.top + th:
                    editor.top = vi - th + 1
                for k in range(th):
                    j = editor.top + k
                    if j >= len(vis):
                        break
                    rr, s, e = vis[j]
                    self.put(py + 1 + k, px + 2, editor.lines[rr][s:e].rstrip(), white)
                cursor = (py + 1 + vi - editor.top, px + 2 + min(dc, tw))
            else:
                vis = layout(ctx.strip("\n").split("\n"), tw)
                lines = ctx.strip("\n").split("\n")
                for k in range(min(th, len(vis))):
                    rr, s, e = vis[k]
                    self.put(py + 1 + k, px + 2, lines[rr][s:e].rstrip(), white)
                bb = py + qh - 1
                self.put(bb, px + 2, " c edit ", self.dim)
                self.put(bb, px + 3, "c", accent | curses.A_BOLD)
                if len(vis) > th:
                    more = f" +{len(vis) - th} more "
                    self.put(bb, px + qw - 2 - len(more), more, self.dim)

        # hint bar, or the input prompt
        fy = H - 1
        if prompt:
            label, buf, pos = prompt
            self.put(fy, x0 + 1, f" {label} ", white | curses.A_BOLD)
            tx = x0 + len(label) + 4
            avail = max(5, pw - tx - 1)
            start = max(0, pos - avail + 1)
            text = "".join(buf)
            self.put(fy, tx, text[start : start + avail], white)
            cursor = (fy, tx + pos - start)
            hint = "enter save  ·  esc cancel"
            if len(text) + 2 + len(hint) <= avail:
                self.put(fy, x0 + pw - 1 - len(hint), hint, self.dim)
        elif editor is not None:
            self.hint_bar(fy, [("esc", "save"), ("enter", "new line"), ("ctrl+c", "discard")], x0, pw)
        else:
            full = [("a", "add"), ("e", "edit"), ("c", "context"), ("space", "done"),
                    ("d", "delete"), ("u", "undo"), ("tab", "filter"), ("q", "quit")]
            short = [("a", "add"), ("c", "context"), ("space", "done"), ("q", "quit")]
            self.hint_bar(fy, full if hint_width(full) <= pw else short, x0, pw)

        try:
            curses.curs_set(1 if cursor else 0)
        except curses.error:
            pass
        if cursor:
            scr.move(*cursor)
        scr.refresh()

    # ---- single-line input (task titles) ------------------------------
    def read_line(self, label, text=""):
        buf, pos = list(text), len(text)
        while True:
            self.draw(prompt=(label, buf, pos))
            try:
                k = self.scr.get_wch()
            except KeyboardInterrupt:
                return None
            except curses.error:
                continue
            if isinstance(k, str):
                if k in ("\n", "\r"):
                    return "".join(buf).strip()
                if k == "\x1b":
                    return None
                if k in ("\x7f", "\b"):
                    if pos:
                        del buf[pos - 1]
                        pos -= 1
                elif k == "\x01":
                    pos = 0
                elif k == "\x05":
                    pos = len(buf)
                elif k == "\x15":
                    del buf[:pos]
                    pos = 0
                elif k == "\x17":
                    j = pos
                    while j > 0 and buf[j - 1] == " ":
                        j -= 1
                    while j > 0 and buf[j - 1] != " ":
                        j -= 1
                    del buf[j:pos]
                    pos = j
                elif k.isprintable():
                    buf.insert(pos, k)
                    pos += 1
            else:
                if k == curses.KEY_BACKSPACE:
                    if pos:
                        del buf[pos - 1]
                        pos -= 1
                elif k == curses.KEY_LEFT:
                    pos = max(0, pos - 1)
                elif k == curses.KEY_RIGHT:
                    pos = min(len(buf), pos + 1)
                elif k == curses.KEY_HOME:
                    pos = 0
                elif k == curses.KEY_END:
                    pos = len(buf)
                elif k == curses.KEY_DC and pos < len(buf):
                    del buf[pos]
                elif k == curses.KEY_ENTER:
                    return "".join(buf).strip()

    # ---- multiline context editor -------------------------------------
    def edit_context(self, i):
        ed = Editor(self.tasks[i]["ctx"])
        while True:
            self.draw(editor=ed)
            try:
                k = self.scr.get_wch()
            except KeyboardInterrupt:
                return  # discard
            except curses.error:
                continue
            if isinstance(k, str):
                if k == "\x1b":
                    break  # save
                if k in ("\n", "\r"):
                    ed.newline()
                elif k in ("\x7f", "\b"):
                    ed.backspace()
                elif k == "\x01":
                    ed.home()
                elif k == "\x05":
                    ed.end()
                elif k == "\x15":
                    ed.kill_to_start()
                elif k == "\x17":
                    ed.kill_word()
                elif k == "\t":
                    ed.insert("  ")
                elif k.isprintable():
                    ed.insert(k)
            else:
                if k == curses.KEY_BACKSPACE:
                    ed.backspace()
                elif k == curses.KEY_LEFT:
                    ed.left()
                elif k == curses.KEY_RIGHT:
                    ed.right()
                elif k == curses.KEY_UP:
                    ed.move_v(-1)
                elif k == curses.KEY_DOWN:
                    ed.move_v(1)
                elif k == curses.KEY_HOME:
                    ed.home()
                elif k == curses.KEY_END:
                    ed.end()
                elif k == curses.KEY_DC:
                    ed.delete()
                elif k == curses.KEY_ENTER:
                    ed.newline()
        new = ed.text()
        if new != self.tasks[i]["ctx"].strip():
            self.snapshot()
            self.tasks[i]["ctx"] = new
            self.commit()

    # ---- state changes -----------------------------------------------
    def snapshot(self):
        self.history.append(copy.deepcopy(self.tasks))
        del self.history[:-100]

    def commit(self):
        with locked():
            self.sync_external()  # never overwrite tasks added from the CLI meanwhile
            save(self.tasks)
            self.mtime = file_mtime()
            self.base = copy.deepcopy(self.tasks)

    def sync_external(self):
        """Merge tasks added to the file by another process (e.g. `tt "..."`)."""
        m = file_mtime()
        if m == self.mtime:
            return
        self.mtime = m
        disk = load()
        known = Counter(map(task_key, self.base))
        added = []
        for t in disk:
            k = task_key(t)
            if known[k] > 0:
                known[k] -= 1
            else:
                added.append(t)
        if not added:
            return
        cur = self.current()
        keep = self.tasks[cur] if cur is not None else None
        for t in added:
            for lst in [self.tasks, *self.history]:  # additions are not undoable
                lst.insert(sum(not x["done"] for x in lst), copy.deepcopy(t) if lst is not self.tasks else t)
        if keep is not None:
            for vi, ti in enumerate(self.view()):
                if self.tasks[ti] is keep:
                    self.sel = vi
                    break
        self.base = copy.deepcopy(disk)
        if not self.msg:
            self.msg = f"+{len(added)} added"

    def handle(self, k):
        n = len(self.view())
        if k in ("q", "\x03"):
            return False
        elif k in ("j", curses.KEY_DOWN):
            self.sel = min(self.sel + 1, max(0, n - 1))
        elif k in ("k", curses.KEY_UP):
            self.sel = max(self.sel - 1, 0)
        elif k in ("g", curses.KEY_HOME):
            self.sel = 0
        elif k in ("G", curses.KEY_END):
            self.sel = max(0, n - 1)
        elif k == curses.KEY_NPAGE:
            self.sel = min(self.sel + self.list_h, max(0, n - 1))
        elif k == curses.KEY_PPAGE:
            self.sel = max(self.sel - self.list_h, 0)
        elif k in ("a", "n"):
            text = self.read_line("NEW")
            if text:
                self.snapshot()
                if FILTERS[self.filter] == "done":
                    self.filter = 0
                pos = sum(not t["done"] for t in self.tasks)  # end of the active group
                self.tasks.insert(pos, {"text": text, "done": False, "ctx": ""})
                self.sel = self.view().index(pos)
                self.commit()
        elif k in ("e", "r"):
            i = self.current()
            if i is not None:
                text = self.read_line("EDIT", self.tasks[i]["text"])
                if text and text != self.tasks[i]["text"]:
                    self.snapshot()
                    self.tasks[i]["text"] = text
                    self.commit()
        elif k == "c":
            i = self.current()
            if i is not None:
                self.edit_context(i)
        elif k in (" ", "\n", "\r", curses.KEY_ENTER):
            i = self.current()
            if i is not None:
                self.snapshot()
                t = self.tasks.pop(i)
                t["done"] = not t["done"]
                if t["done"]:
                    self.tasks.append(t)  # sink to the bottom
                else:
                    self.tasks.insert(sum(not x["done"] for x in self.tasks), t)
                self.commit()
        elif k in ("d", "x", curses.KEY_DC):
            i = self.current()
            if i is not None:
                self.snapshot()
                del self.tasks[i]
                self.msg = "deleted · u to undo"
                self.commit()
        elif k == "X":
            cnt = sum(t["done"] for t in self.tasks)
            if cnt:
                self.snapshot()
                self.tasks = [t for t in self.tasks if not t["done"]]
                self.msg = f"cleared {cnt} · u to undo"
                self.commit()
        elif k == "u":
            if self.history:
                self.tasks = self.history.pop()
                self.msg = "undone"
                self.commit()
            else:
                self.msg = "nothing to undo"
        elif k in ("\t", "f"):
            self.filter = (self.filter + 1) % len(FILTERS)
            self.sel = self.top = 0
        elif k == curses.KEY_BTAB:
            self.filter = (self.filter - 1) % len(FILTERS)
            self.sel = self.top = 0
        elif k in ("J", "K") and FILTERS[self.filter] == "all" and n:
            j = self.sel + (1 if k == "J" else -1)
            # reorder only within the same group (active/done) so done tasks stay at the bottom
            if 0 <= j < len(self.tasks) and self.tasks[j]["done"] == self.tasks[self.sel]["done"]:
                self.snapshot()
                self.tasks[self.sel], self.tasks[j] = self.tasks[j], self.tasks[self.sel]
                self.sel = j
                self.commit()
        return True

    def run(self):
        self.scr.keypad(True)
        self.scr.timeout(300)  # wake up regularly to pick up tasks added from the CLI
        while True:
            self.sync_external()
            self.draw()
            try:
                k = self.scr.get_wch()
            except KeyboardInterrupt:
                break
            except curses.error:
                continue
            self.msg = ""
            if not self.handle(k):
                break


def main(scr):
    App(scr).run()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        if args[0] in ("-h", "--help"):
            print('usage: tt            open the task manager\n       tt "task"     add a task without opening it')
            sys.exit(0)
        sys.exit(cli_add(" ".join(args)))
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(main)
