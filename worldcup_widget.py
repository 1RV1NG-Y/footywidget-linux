#!/usr/bin/env python3
"""
Linux port of the World Cup score widget.

Dependency-free Python/Tk implementation of the original Windows
PowerShell/WinForms app. Data comes from ESPN's public soccer scoreboard API.
"""

from __future__ import annotations

import argparse
import json
import threading
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
import tkinter as tk


API = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
LEAGUES = ("fifa.world",)
POLL_SECONDS = 30
PRE_MATCH_REFRESH_MINUTES = 15
ERROR_RETRY_SECONDS = 300

WIDTH = 430
HEADER_HEIGHT = 52
STATUS_HEIGHT = 19
MAX_HEIGHT = 380
ROW_HEIGHT = 34
ROW_STEP = 38
ROW_X = 12
ROW_WIDTH = 406

THEMES = {
    "Midnight": {
        "Bg": "#0c0c0e",
        "Panel": "#141418",
        "RowLive": "#15151a",
        "RowIdle": "#101013",
        "Fg": "#f2f2f2",
        "Dim": "#888890",
        "Muted": "#5f5f68",
        "Live": "#ff9e3d",
        "Border": "#29292f",
    },
    "Broadcast": {
        "Bg": "#0d0e11",
        "Panel": "#141519",
        "RowLive": "#141519",
        "RowIdle": "#101115",
        "Fg": "#f4f4f6",
        "Dim": "#9a9aa2",
        "Muted": "#74747c",
        "Live": "#e2483c",
        "Border": "#24262c",
    },
    "Aurora": {
        "Bg": "#f5f6f8",
        "Panel": "#ffffff",
        "RowLive": "#ffffff",
        "RowIdle": "#fafafb",
        "Fg": "#1b1c1f",
        "Dim": "#8a8d94",
        "Muted": "#a3a6ad",
        "Live": "#e0563b",
        "Border": "#e4e5ea",
    },
    "Ticker": {
        "Bg": "#0a0a0b",
        "Panel": "#0a0a0b",
        "RowLive": "#0a0a0b",
        "RowIdle": "#0a0a0b",
        "Fg": "#e8e8ea",
        "Dim": "#6b6b70",
        "Muted": "#7a7a80",
        "Live": "#ff9e3d",
        "Border": "#1c1d22",
    },
}

ACTIVE_THEME = "Midnight"
COLORS = THEMES[ACTIVE_THEME]

FONT_TITLE = ("DejaVu Sans", 9, "bold")
FONT_DATE = ("DejaVu Sans", 9)
FONT_BODY = ("DejaVu Sans", 10)
FONT_SCORE = ("DejaVu Sans", 12, "bold")
FONT_SMALL = ("DejaVu Sans", 8)


@dataclass(frozen=True)
class Match:
    id: str
    kickoff: datetime
    home: str
    away: str
    home_score: str
    away_score: str
    state: str
    detail: str
    sort_weight: int


@dataclass(frozen=True)
class RefreshPlan:
    enabled: bool
    delay: timedelta
    label: str


def _team_name(competitor: dict[str, Any] | None) -> str:
    if not competitor:
        return "TBD"
    team = competitor.get("team") or {}
    for prop in ("abbreviation", "shortDisplayName", "displayName", "name"):
        value = team.get(prop)
        if value:
            return str(value)
    return "TBD"


def _side(competitors: list[dict[str, Any]], side: str) -> dict[str, Any] | None:
    for competitor in competitors:
        if competitor and competitor.get("homeAway") == side:
            return competitor
    return None


def _score(competitor: dict[str, Any] | None) -> str:
    if not competitor:
        return ""
    value = competitor.get("score")
    if value is None:
        return ""
    return str(value)


def _event_datetime(raw_date: Any) -> datetime | None:
    if not raw_date:
        return None
    try:
        value = str(raw_date).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def _date_token(day: date) -> str:
    return day.strftime("%Y%m%d")


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def get_worldcup_matches(match_date: date, leagues: tuple[str, ...] = LEAGUES) -> list[Match]:
    events_by_id: dict[str, dict[str, Any]] = {}

    for league in leagues:
        for offset in (-1, 0, 1):
            query_date = match_date + timedelta(days=offset)
            params = urllib.parse.urlencode({"dates": _date_token(query_date)})
            url = f"{API.format(league=league)}?{params}"
            try:
                data = _fetch_json(url)
            except Exception as exc:
                raise RuntimeError(f"Could not reach ESPN for {_date_token(query_date)}. {exc}") from exc

            for event in data.get("events") or []:
                event_id = str(event.get("id") or "")
                if event_id and event_id not in events_by_id:
                    events_by_id[event_id] = event

    matches: list[Match] = []
    for event in events_by_id.values():
        competitions = event.get("competitions") or []
        competition = competitions[0] if competitions else None
        if not competition:
            continue

        competitors = list(competition.get("competitors") or [])
        home_side = _side(competitors, "home")
        away_side = _side(competitors, "away")
        if home_side is None or away_side is None:
            if len(competitors) < 2:
                continue
            home_side = competitors[0]
            away_side = competitors[1]

        kickoff = _event_datetime(event.get("date"))
        if kickoff is None or kickoff.date() != match_date:
            continue

        status_type = ((event.get("status") or {}).get("type") or {})
        state = str(status_type.get("state") or "pre")
        detail = str(status_type.get("shortDetail") or status_type.get("detail") or "")
        sort_weight = {"in": 0, "pre": 1, "post": 2}.get(state, 3)

        matches.append(
            Match(
                id=str(event.get("id") or ""),
                kickoff=kickoff,
                home=_team_name(home_side),
                away=_team_name(away_side),
                home_score=_score(home_side),
                away_score=_score(away_side),
                state=state,
                detail=detail,
                sort_weight=sort_weight,
            )
        )

    return sorted(matches, key=lambda match: (match.kickoff, match.sort_weight))


def get_refresh_plan(
    matches: list[Match],
    had_error: bool = False,
    now: datetime | None = None,
) -> RefreshPlan:
    if had_error:
        return RefreshPlan(
            enabled=True,
            delay=timedelta(seconds=ERROR_RETRY_SECONDS),
            label=f"retry in {(ERROR_RETRY_SECONDS + 59) // 60} min",
        )

    now = now or datetime.now().astimezone()
    if any(match.state == "in" for match in matches):
        return RefreshPlan(enabled=True, delay=timedelta(seconds=POLL_SECONDS), label="live refresh")

    watch_window = timedelta(minutes=PRE_MATCH_REFRESH_MINUTES)
    upcoming = sorted(
        (
            match
            for match in matches
            if match.state != "post" and match.kickoff >= now - timedelta(hours=2)
        ),
        key=lambda match: match.kickoff,
    )

    for fixture in upcoming:
        watch_start = fixture.kickoff - watch_window
        if watch_start <= now:
            return RefreshPlan(enabled=True, delay=timedelta(seconds=POLL_SECONDS), label="starting soon")
        return RefreshPlan(
            enabled=True,
            delay=watch_start - now,
            label=f"next refresh {watch_start:%H:%M}",
        )

    return RefreshPlan(enabled=False, delay=timedelta(0), label="refresh paused")


def _serializable_match(match: Match) -> dict[str, Any]:
    payload = asdict(match)
    payload["kickoff"] = match.kickoff.isoformat()
    return payload


def _format_widget_date(value: date) -> str:
    return f"{value:%a}, {value:%b} {value.day}"


def _format_duration_seconds(delay: timedelta) -> int:
    seconds = int(delay.total_seconds())
    return max(1, seconds)


class FlatButton(tk.Label):
    def __init__(self, master: tk.Misc, text: str, command: Any, width: int) -> None:
        super().__init__(
            master,
            text=text,
            bg=COLORS["Bg"],
            fg=COLORS["Fg"],
            font=FONT_SMALL,
            width=1,
            height=1,
            bd=1,
            relief="solid",
            cursor="hand2",
            padx=0,
            pady=0,
        )
        self._command = command
        self._normal_bg = COLORS["Bg"]
        self._hover_bg = COLORS["Panel"]
        self._width = width
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _on_enter(self, _event: tk.Event) -> None:
        self.configure(bg=self._hover_bg)

    def _on_leave(self, _event: tk.Event) -> None:
        self.configure(bg=self._normal_bg)

    def _on_click(self, _event: tk.Event) -> str:
        self._command()
        return "break"


class Widget(tk.Tk):
    def __init__(self, selected_date: date | None = None, auto_refresh: bool = True) -> None:
        super().__init__()
        self.title("World Cup Scores")
        self.configure(bg=COLORS["Bg"], padx=1, pady=0)
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)

        self.selected_date = selected_date or date.today()
        self.is_refreshing = False
        self._drag_start: tuple[int, int] | None = None
        self._window_start: tuple[int, int] | None = None
        self._refresh_after_id: str | None = None
        self._scrollable = False

        self._build_layout()
        self._resize_for_count(1)
        self.update_idletasks()
        self._position_top_right()

        if auto_refresh:
            self.after(50, self.refresh)

    def _build_layout(self) -> None:
        self.header = tk.Frame(self, bg=COLORS["Bg"], height=HEADER_HEIGHT, width=WIDTH)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.title_label = tk.Label(
            self.header,
            text="WORLD CUP",
            bg=COLORS["Bg"],
            fg=COLORS["Dim"],
            font=FONT_TITLE,
            anchor="w",
        )
        self.title_label.place(x=12, y=6, width=120, height=18)

        self.date_label = tk.Label(
            self.header,
            text="",
            bg=COLORS["Bg"],
            fg=COLORS["Fg"],
            font=FONT_DATE,
            anchor="w",
        )
        self.date_label.place(x=12, y=25, width=220, height=22)

        self.prev_button = FlatButton(self.header, "<", lambda: self._change_date(-1), 30)
        self.today_button = FlatButton(self.header, "Today", self._go_today, 58)
        self.next_button = FlatButton(self.header, ">", lambda: self._change_date(1), 30)
        self.close_button = FlatButton(self.header, "x", self.destroy, 28)
        self.prev_button.place(x=256, y=13, width=30, height=24)
        self.today_button.place(x=291, y=13, width=58, height=24)
        self.next_button.place(x=354, y=13, width=30, height=24)
        self.close_button.place(x=390, y=13, width=28, height=24)

        self.body = tk.Frame(self, bg=COLORS["Bg"], width=WIDTH)
        self.body.pack(fill="both", expand=True)
        self.body.pack_propagate(False)

        self.canvas = tk.Canvas(
            self.body,
            bg=COLORS["Bg"],
            bd=0,
            highlightthickness=0,
            width=WIDTH,
        )
        self.canvas.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            self,
            textvariable=self.status_var,
            bg=COLORS["Bg"],
            fg=COLORS["Muted"],
            font=FONT_SMALL,
            anchor="w",
            padx=12,
        )
        self.status_label.pack(fill="x", side="bottom")
        self.status_label.configure(height=1)

        for control in (
            self,
            self.header,
            self.title_label,
            self.date_label,
            self.body,
            self.canvas,
            self.status_label,
        ):
            control.bind("<Button-1>", self._start_drag)
            control.bind("<B1-Motion>", self._drag)
            control.bind("<ButtonRelease-1>", self._end_drag)
            control.bind("<Button-3>", lambda _event: self.destroy())

        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda event: self._scroll(-1))
        self.canvas.bind("<Button-5>", lambda event: self._scroll(1))
        self.bind("<Escape>", lambda _event: self.destroy())

    def _position_top_right(self) -> None:
        x = max(0, self.winfo_screenwidth() - WIDTH - 18)
        self.geometry(f"+{x}+42")

    def _start_drag(self, event: tk.Event) -> None:
        self._drag_start = (event.x_root, event.y_root)
        self._window_start = (self.winfo_x(), self.winfo_y())

    def _drag(self, event: tk.Event) -> None:
        if self._drag_start is None or self._window_start is None:
            return
        dx = event.x_root - self._drag_start[0]
        dy = event.y_root - self._drag_start[1]
        self.geometry(f"+{self._window_start[0] + dx}+{self._window_start[1] + dy}")

    def _end_drag(self, _event: tk.Event) -> None:
        self._drag_start = None
        self._window_start = None

    def _change_date(self, days: int) -> None:
        self.selected_date = self.selected_date + timedelta(days=days)
        self.refresh()

    def _go_today(self) -> None:
        self.selected_date = date.today()
        self.refresh()

    def _cancel_refresh_timer(self) -> None:
        if self._refresh_after_id is None:
            return
        try:
            self.after_cancel(self._refresh_after_id)
        except tk.TclError:
            pass
        self._refresh_after_id = None

    def refresh(self) -> None:
        if self.is_refreshing:
            return

        self.is_refreshing = True
        self._cancel_refresh_timer()
        fetch_date = self.selected_date
        self.date_label.configure(text=_format_widget_date(fetch_date))
        self.status_var.set("Refreshing...")
        thread = threading.Thread(target=self._fetch_worker, args=(fetch_date,), daemon=True)
        thread.start()

    def _fetch_worker(self, fetch_date: date) -> None:
        try:
            matches = get_worldcup_matches(fetch_date)
            self.after(0, lambda: self._finish_refresh(fetch_date, matches, ""))
        except Exception as exc:
            self.after(0, lambda: self._finish_refresh(fetch_date, [], str(exc)))

    def _finish_refresh(self, fetch_date: date, matches: list[Match], error: str) -> None:
        if fetch_date != self.selected_date:
            self.is_refreshing = False
            self.refresh()
            return

        if error:
            self._render([], error)
            plan = get_refresh_plan([], had_error=True)
            self.status_var.set(f"Load failed - {plan.label}")
        else:
            self._render(matches)
            plan = get_refresh_plan(matches)
            self.status_var.set(f"Updated {datetime.now():%H:%M:%S} - {plan.label}")

        self._schedule_refresh(plan)
        self.is_refreshing = False

    def _schedule_refresh(self, plan: RefreshPlan) -> None:
        self._cancel_refresh_timer()
        if not plan.enabled:
            return
        milliseconds = _format_duration_seconds(plan.delay) * 1000
        self._refresh_after_id = self.after(milliseconds, self.refresh)

    def _resize_for_count(self, match_count: int) -> int:
        row_space = max(58, match_count * ROW_STEP + 16)
        total_height = min(MAX_HEIGHT, HEADER_HEIGHT + STATUS_HEIGHT + row_space)
        body_height = total_height - HEADER_HEIGHT - STATUS_HEIGHT
        self.geometry(f"{WIDTH}x{total_height}")
        self.body.configure(height=body_height)
        self.canvas.configure(height=body_height)
        return body_height

    def _render(self, matches: list[Match], error: str = "") -> None:
        self.canvas.delete("all")
        self.date_label.configure(text=_format_widget_date(self.selected_date))

        if error:
            body_height = self._resize_for_count(1)
            self._draw_message(error)
            self._set_scrollregion(body_height)
            return

        if not matches:
            body_height = self._resize_for_count(1)
            self._draw_message("No World Cup matches")
            self._set_scrollregion(body_height)
            return

        body_height = self._resize_for_count(len(matches))
        y = 8
        for match in matches:
            self._draw_match_row(match, y)
            y += ROW_STEP

        self._set_scrollregion(max(body_height, y + 8))

    def _set_scrollregion(self, content_height: int) -> None:
        body_height = int(self.canvas.cget("height") or 0)
        self._scrollable = content_height > body_height
        self.canvas.configure(scrollregion=(0, 0, WIDTH, content_height))
        if not self._scrollable:
            self.canvas.yview_moveto(0)

    def _draw_message(self, message: str) -> None:
        self.canvas.create_text(
            12,
            28,
            text=message,
            fill=COLORS["Dim"],
            font=FONT_BODY,
            anchor="w",
            width=390,
        )

    def _draw_match_row(self, match: Match, y: int) -> None:
        is_live = match.state == "in"
        is_post = match.state == "post"
        row_color = COLORS["RowLive"] if is_live else COLORS["RowIdle"]
        line_color = COLORS["Dim"] if is_post else COLORS["Fg"]
        score_color = COLORS["Dim"] if is_post else COLORS["Fg"]
        status_color = COLORS["Dim"]
        score_text = "v"

        if is_live:
            status_text = match.detail or "LIVE"
            status_color = COLORS["Live"]
            score_text = f"{match.home_score}-{match.away_score}"
        elif is_post:
            status_text = "FT"
            score_text = f"{match.home_score}-{match.away_score}"
        else:
            status_text = match.kickoff.strftime("%H:%M")
            score_color = COLORS["Muted"]

        x = ROW_X
        self._rounded_rect(x, y, x + ROW_WIDTH, y + ROW_HEIGHT, 8, row_color)
        if is_live:
            self.canvas.create_oval(x + 14, y + 14, x + 20, y + 20, fill=COLORS["Live"], outline="")

        self.canvas.create_text(
            x + 24,
            y + 17,
            text=status_text,
            fill=status_color,
            font=FONT_SMALL,
            anchor="w",
        )
        self.canvas.create_text(
            x + 166,
            y + 17,
            text=match.home,
            fill=line_color,
            font=FONT_BODY,
            anchor="e",
            width=110,
        )
        self.canvas.create_text(
            x + 191,
            y + 17,
            text=score_text,
            fill=score_color,
            font=FONT_SCORE,
            anchor="center",
            width=50,
        )
        self.canvas.create_text(
            x + 216,
            y + 17,
            text=match.away,
            fill=line_color,
            font=FONT_BODY,
            anchor="w",
            width=166,
        )

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, fill: str) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.canvas.create_polygon(points, smooth=True, splinesteps=12, fill=fill, outline="")

    def _on_mousewheel(self, event: tk.Event) -> str:
        if not self._scrollable:
            return "break"
        if event.delta > 0:
            self._scroll(-1)
        elif event.delta < 0:
            self._scroll(1)
        return "break"

    def _scroll(self, units: int) -> str:
        if self._scrollable:
            self.canvas.yview_scroll(units, "units")
        return "break"


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Linux World Cup score widget")
    parser.add_argument("--date", type=parse_date, default=date.today(), help="match date, YYYY-MM-DD")
    parser.add_argument("--test-fetch", action="store_true", help="fetch matches and print JSON")
    parser.add_argument("--test-layout", action="store_true", help="construct the widget and exit")
    parser.add_argument("--test-render", action="store_true", help="fetch, render once, and exit")
    parser.add_argument("--test-schedule", action="store_true", help="print the refresh schedule JSON")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.test_fetch:
        matches = get_worldcup_matches(args.date)
        print(json.dumps([_serializable_match(match) for match in matches], indent=2))
        return 0

    if args.test_schedule:
        matches = get_worldcup_matches(args.date)
        plan = get_refresh_plan(matches)
        print(
            json.dumps(
                {
                    "match_count": len(matches),
                    "timer_enabled": plan.enabled,
                    "delay_seconds": round(plan.delay.total_seconds()),
                    "label": plan.label,
                },
                indent=2,
            )
        )
        return 0

    if args.test_layout:
        widget = Widget(selected_date=args.date, auto_refresh=False)
        widget.update_idletasks()
        print("layout ok")
        widget.destroy()
        return 0

    if args.test_render:
        matches = get_worldcup_matches(args.date)
        widget = Widget(selected_date=args.date, auto_refresh=False)
        widget._render(matches)
        widget.update_idletasks()
        print(f"rendered {len(matches)} matches")
        widget.destroy()
        return 0

    Widget(selected_date=args.date).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
