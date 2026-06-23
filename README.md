# World Cup Score Widget for Linux

Linux port of the original Windows PowerShell/WinForms widget. It keeps the
same behavior in a Python/Tk app:

- frameless always-on-top score widget
- drag from empty/header/body areas to move
- previous day, today, next day, and close controls
- ESPN World Cup scoreboard data with local kickoff times
- live refresh every 30 seconds only when useful

## Run

```bash
./launch-worldcup-widget.sh
```

or:

```bash
python3 worldcup_widget.py
```

No pip packages are required. If Tk is not installed on another Linux machine,
install the distro package that provides Python Tkinter, usually `python3-tk`.

## Controls

- `<` and `>` move between days.
- `Today` jumps back to today.
- `x`, right-click, or `Esc` closes the widget.
- Drag the widget from any empty/header/body area to move it.

## Checks

```bash
python3 -m py_compile worldcup_widget.py
python3 worldcup_widget.py --test-layout
python3 worldcup_widget.py --test-fetch --date 2026-06-22
python3 worldcup_widget.py --test-schedule --date 2026-06-22
```

## Data Source

The widget reads:

```text
https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=YYYYMMDD
```

No API key is required. If ESPN changes this public endpoint, the fetch logic is
isolated in `get_worldcup_matches` inside `worldcup_widget.py`.
