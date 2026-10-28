"""The money and tax to-do list in <workspace>/todo.md, shown on the page and by `taxtrace todo`.

An item is `- [ ] text` under a `## Section` heading (`- [x]` once done). Indented `  - text` lines under it are its
notes and indented `  - [ ] text` lines its sub-tasks. Its due date is a leading bold date: `**Wed 10/28**`,
`**Fri 1/15/2027**` or `**Wed 10/28, time TBD**`; an item without one is allowed. A month and day without a year
mean the date within 2 months back to 10 months ahead of today, so a December list can say `**Fri 1/15**` and mean
next January. Other lines (a one-line intro under a heading) are ignored.

Ticking an item changes that line's `[ ]` to `[x]` and nothing else, and refuses if the line isn't what the page
showed any more.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from . import workspace

WEEKDAY = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*"
# a leading bold date, then optionally a note inside the bold: `**Wed 10/28, time TBD**`
LEAD = re.compile(rf"^\*\*{WEEKDAY},? (\d{{1,2}})/(\d{{1,2}})(?:/(\d{{4}}))?([^*]*)\*\*\s*")
ITEM = re.compile(r"^- \[([ xX])\] (.*)$")
SUBTASK = re.compile(r"^\s+- \[([ xX])\] (.*)$")
NOTE = re.compile(r"^\s+- (.*)$")
OPEN = "- [ ] "
GROUPS = ("overdue", "today", "week", "later", "undated")


@dataclass
class Item:
    line: int  # 1-based, in the file
    raw: str  # the whole line, as the page checks it before ticking
    section: str
    text: str  # what to show: the item without its leading date
    due: date | None = None
    time: str = ""  # "time TBD" and the like, from inside the bold date
    notes: list[str] = field(default_factory=list)
    subtasks: list[dict] = field(default_factory=list)  # [{"text", "done"}]


def today() -> date:
    return datetime.now().astimezone().date()


def path() -> Path:
    return workspace.home() / workspace.TODO


def add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def infer(month: int, day: int, year: int | None, on: date) -> date | None:
    """The date for M/D (with the year, if written); with none, the one from 2 months back to 10 months ahead of
    `on`, else the nearest to it. None for a day that doesn't exist."""
    if year:
        try:
            return date(year, month, day)
        except ValueError:
            return None
    found = []
    for y in (on.year - 1, on.year, on.year + 1):
        try:
            found.append(date(y, month, day))
        except ValueError:
            pass  # February 29 in a common year
    low, high = add_months(on, -2), add_months(on, 10)
    pool = [d for d in found if low <= d <= high] or found
    return min(pool, key=lambda d: abs((d - on).days)) if pool else None


def split_due(text: str, on: date) -> tuple[date | None, str, str]:
    """(the due date or None, a time note like "time TBD", the text to show) for an item's text."""
    m = LEAD.match(text)
    if m:
        due = infer(int(m[1]), int(m[2]), int(m[3]) if m[3] else None, on)
        note = m[4].strip()
        if due and (not note or note.startswith(",")):
            return due, note.lstrip(", ").strip(), text[m.end():]
    return None, "", text


def parse(md: str, on: date) -> list[Item]:
    """The open items in file order. Done ones, and any line that isn't an item, a sub-task or a note, are skipped."""
    items: list[Item] = []
    section, current = "", None
    for n, line in enumerate(md.splitlines(), 1):
        if line.startswith("## "):
            section, current = line[3:].strip(), None
            continue
        top = ITEM.match(line)
        if top:
            current = None
            if top[1] == " " and section:
                due, time, shown = split_due(top[2], on)
                current = Item(n, line, section, shown, due, time)
                items.append(current)
            continue
        if current is None:
            continue
        sub, note = SUBTASK.match(line), NOTE.match(line)
        if sub:
            current.subtasks.append({"text": sub[2], "done": sub[1] != " "})
        elif note:
            current.notes.append(note[1])
    return items


def load(on: date | None = None) -> list[Item] | None:
    """The workspace's open items, or None when there's no todo.md."""
    file = path()
    if not file.is_file():
        return None
    return parse(file.read_text(encoding="utf-8"), on or today())


def ordered(items: list[Item]) -> list[Item]:
    """Soonest first, undated last; file order breaks ties."""
    return sorted(items, key=lambda i: (i.due is None, i.due or date.max, i.line))


def due_within(items: list[Item], on: date, days: int = 7) -> list[Item]:
    """The overdue items and those due in the next `days` days, soonest first."""
    end = on + timedelta(days=days)
    return [i for i in ordered(items) if i.due and i.due <= end]


def group(item: Item, on: date) -> str:
    """Which of GROUPS the item falls in: "week" is tomorrow through 7 days out."""
    if item.due is None:
        return "undated"
    if item.due < on:
        return "overdue"
    if item.due == on:
        return "today"
    return "week" if (item.due - on).days <= 7 else "later"


def to_json(items: list[Item], on: date) -> list[dict]:
    """The items for the page, soonest first."""
    return [{"line": i.line, "raw": i.raw, "section": i.section, "text": i.text, "time": i.time, "notes": i.notes,
             "subtasks": i.subtasks, "due": i.due.isoformat() if i.due else None,
             "days": (i.due - on).days if i.due else None, "group": group(i, on)} for i in ordered(items)]


def mark_done(file: Path, line: int, expect: str) -> None:
    """Change `[ ]` to `[x]` on one line, nothing else (its line ending, and a missing final newline, stay).
    ValueError if the line isn't exactly `expect` any more, with nothing written."""
    with open(file, newline="", encoding="utf-8") as f:
        lines = f.read().splitlines(keepends=True)
    if not 1 <= line <= len(lines):
        raise ValueError("todo.md changed: that line is gone. Reload the page.")
    body = lines[line - 1].rstrip("\r\n")
    if body != expect or not body.startswith(OPEN):
        raise ValueError("todo.md changed since the page loaded; nothing written. Reload the page.")
    lines[line - 1] = "- [x] " + lines[line - 1][len(OPEN):]
    with open(file, "w", newline="", encoding="utf-8") as f:
        f.write("".join(lines))


def row(item: Item) -> str:
    """One line for the terminal: the due date, the section, the text."""
    due = item.due
    when = "no date" if due is None else f"{due.strftime('%a')} {due.month}/{due.day}/{due.year}"
    return f"{when:<18} [{item.section}] {item.text}"
