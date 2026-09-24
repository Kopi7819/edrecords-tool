import math
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from config import JOURNAL_DIR, AUTO_REFRESH_MS, EDASTRO_CACHE_MAX_AGE_DAYS
from current_system import build_current_system_rows, build_records_rows
from type_independent_records import build_type_independent_rows, build_system_records_rows
from own_records import load_own_records, build_or_update_own_records, rebuild_own_records
from journal_parser import JournalAccessError
from record_status import annotate_rows, parse_number, STATUS_NEW_PERSONAL_BEST, STATUS_BEATS_GLOBAL, STATUS_NORMAL
from voice_announcer import speak
from data_loader import refresh_all_cached_attributes
from settings import load_settings, save_settings
from type_stats import build_type_crosstab, compute_margins, count_primary_stars, count_all_stars
from update_bio_reference import update_bio_reference
from bio_reference import (
    GENUS_SPECIES_TOTALS,
    SPECIES_VARIANT_TOTALS,
    GENUS_VARIANT_TOTALS,
    TOTAL_KNOWN_GENERA,
    TOTAL_KNOWN_SPECIES,
    TOTAL_KNOWN_VARIANTS,
)

APP_NAME = "ED Records Tool"
APP_VERSION = "0.1.0"

# Elite Dangerous inspired color palette
BG_COLOR = "#000000"
PANEL_COLOR = "#0a0a0a"
ORANGE = "#ff8c00"
ORANGE_BRIGHT = "#ffa733"
ORANGE_DIM = "#8a5000"
GREEN = "#39d17a"
GOLD = "#ffd700"
FONT_FAMILY = "Eurostile"
FALLBACK_FONT = "Consolas"

STATUS_LABELS = {
    STATUS_NEW_PERSONAL_BEST: "NEW BEST",
    STATUS_BEATS_GLOBAL: "BEATS GLOBAL",
    STATUS_NORMAL: "",
}


def resolve_font(root: tk.Tk) -> str:
    import tkinter.font as tkfont
    available = tkfont.families(root)
    return FONT_FAMILY if FONT_FAMILY in available else FALLBACK_FONT


def short_body_label(body_name: str, system_name: str = None) -> str:
    """
    Strips the leading system name from a body name (since the system is
    already shown in the header), leaving just the body's own designator,
    e.g. "Shaulai BQ-P d5-60 3 a" + "Shaulai BQ-P d5-60" -> "3 a".
    Falls back to the full body name if it doesn't start with the system
    name (shouldn't normally happen, but keeps this safe either way).
    """
    if system_name and body_name.startswith(system_name):
        suffix = body_name[len(system_name):].strip()
        return suffix if suffix else body_name
    return body_name


def format_value(value) -> str:
    """Formats a number for display, with thousands separators and up to 3 decimals."""
    num = parse_number(value)
    if num is None:
        return "—"
    if num == int(num):
        return f"{int(num):,}"
    return f"{num:,.3f}".rstrip("0").rstrip(".")


def make_autohide_grid_scrollbar(scrollbar, grid_kwargs):
    """
    Returns a scrollcommand callback that shows the scrollbar (via the given
    grid() kwargs) only when the content actually overflows the visible
    area, and hides it (grid_remove) otherwise. grid_remove is used instead
    of pack_forget/pack because it preserves the widget's original grid
    position when shown again.
    """
    def set_and_autohide(first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            scrollbar.grid_remove()
        else:
            scrollbar.grid(**grid_kwargs)
        scrollbar.set(first, last)
    return set_and_autohide


def natural_sort_key(text: str):
    """
    Splits text into alternating non-digit/digit chunks, converting the digit
    chunks to int, so e.g. "Body 10" sorts after "Body 9" instead of before
    "Body 2" (plain string comparison would compare "1" vs "9" character by
    character and put "10" first).
    """
    return [int(chunk) if chunk.isdigit() else chunk.lower() for chunk in re.split(r"(\d+)", text)]


SYSTEM_METRIC_LABELS = [
    ("bodyCount", "Body Count"),
    ("numStars", "Stars"),
    ("numPlanets", "Planets"),
    ("numELW", "ELW"),
    ("numWW", "WW"),
    ("numAW", "AW"),
    ("numTerra", "Terraform candidates"),
]


def build_system_stats_parts(current_values: dict, system_records: dict) -> list[tuple[str, bool]]:
    """
    Builds the "Body Count: 20 (best: 63)   Stars: 3 (best: 5)   ..." summary
    as a list of (text, is_record) tuples -- one per metric -- so the caller
    can render each metric in a different color without affecting the rest
    of the line (own-side ties count as a record, same as elsewhere).
    """
    parts = []
    for metric_key, label in SYSTEM_METRIC_LABELS:
        current_value = current_values.get(metric_key)
        best_entry = system_records.get(metric_key, {}).get("max")
        best_value = best_entry["value"] if best_entry else None

        is_record = current_value is not None and best_value is not None and current_value >= best_value
        marker = "\u2605 " if is_record else ""

        current_str = current_value if current_value is not None else "\u2014"
        best_str = f" (best: {best_value})" if best_value is not None else ""
        parts.append((f"{marker}{label}: {current_str}{best_str}", is_record))

    return parts


class RecordsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ED Records Tool")
        self.geometry("1150x650")
        self.configure(bg=BG_COLOR)

        self.font_family = resolve_font(self)
        self.apply_theme()
        self.build_menu()

        # --- Global status bar: always visible, regardless of active tab.
        # Used for cross-cutting status (rebuilds, EDAstro refreshes, errors)
        # rather than reusing the Current System tab's own header for this.
        status_bar = ttk.Frame(self, style="Dark.TFrame")
        status_bar.pack(fill="x", padx=12, pady=(6, 4))
        self.global_status_label = ttk.Label(status_bar, text="", style="Dark.TLabel", font=(self.font_family, 9))
        self.global_status_label.pack(side="left")
        self.last_updated_label = ttk.Label(status_bar, text="", style="Dark.TLabel", font=(self.font_family, 9))
        self.last_updated_label.pack(side="right")

        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.refresh_job_id = None
        self._refresh_in_progress = False
        auto_check = tk.Checkbutton(
            status_bar,
            text="Live auto-refresh",
            variable=self.auto_refresh_var,
            command=self.on_auto_refresh_toggle,
            bg=BG_COLOR,
            fg=ORANGE,
            selectcolor=PANEL_COLOR,
            activebackground=BG_COLOR,
            activeforeground=ORANGE_BRIGHT,
            font=(self.font_family, 9),
            highlightthickness=0,
        )
        auto_check.pack(side="right", padx=12)

        self.voice_var = tk.BooleanVar(value=True)
        voice_check = tk.Checkbutton(
            status_bar,
            text="Voice alerts",
            variable=self.voice_var,
            bg=BG_COLOR,
            fg=ORANGE,
            selectcolor=PANEL_COLOR,
            activebackground=BG_COLOR,
            activeforeground=ORANGE_BRIGHT,
            font=(self.font_family, 9),
            highlightthickness=0,
        )
        voice_check.pack(side="right", padx=12)

        self.notebook = ttk.Notebook(self, style="Dark.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.current_system_tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.records_tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.statistics_tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.bioscan_tab = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(self.current_system_tab, text="Current System")
        self.notebook.add(self.records_tab, text="Body Records")
        self.notebook.add(self.statistics_tab, text="Body Matrix")
        self.notebook.add(self.bioscan_tab, text="Bioscan Stats")

        tab = self.current_system_tab

        # --- Header ---
        header = ttk.Frame(tab, style="Dark.TFrame")
        header.pack(fill="x", padx=12, pady=10)

        self.system_label = ttk.Label(header, text="", style="Dark.TLabel", font=(self.font_family, 15, "bold"))
        self.system_label.pack(side="left")

        self.info_label = ttk.Label(header, text="", style="Dark.TLabel")
        self.info_label.pack(side="left", padx=16)

        self.row_holders = {}
        self.tooltip_window = None
        self.previous_statuses = {}
        self.first_refresh_done = False

        self.filter_var = tk.BooleanVar(value=False)
        filter_check = tk.Checkbutton(
            header,
            text="Only show records",
            variable=self.filter_var,
            command=self.refresh,
            bg=BG_COLOR,
            fg=ORANGE,
            selectcolor=PANEL_COLOR,
            activebackground=BG_COLOR,
            activeforeground=ORANGE_BRIGHT,
            font=(self.font_family, 10),
            highlightthickness=0,
        )
        filter_check.pack(side="right", padx=12)

        # --- Legend ---
        legend = ttk.Frame(tab, style="Dark.TFrame")
        legend.pack(fill="x", padx=12)
        tk.Label(legend, text="\u2605 new personal best", bg=BG_COLOR, fg=GREEN, font=(self.font_family, 9)).pack(side="left")
        tk.Label(legend, text="   \u25c6 beats global record", bg=BG_COLOR, fg=GOLD, font=(self.font_family, 9)).pack(side="left")

        # --- System-level stats ---
        self.system_stats_text = tk.Text(
            tab,
            height=2,
            bg=BG_COLOR,
            fg=ORANGE,
            font=(self.font_family, 10),
            wrap="word",
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=4,
            cursor="arrow",
        )
        self.system_stats_text.tag_configure("record", foreground=GREEN)
        self.system_stats_text.tag_configure("normal", foreground=ORANGE)
        self.system_stats_text.config(state="disabled")
        self.system_stats_text.pack(fill="x")

        # --- Tree ---
        tree_frame = ttk.Frame(tab, style="Dark.TFrame")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(6, 12))

        columns = ("current", "global_max", "global_min", "own_max", "own_min", "status")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", style="Dark.Treeview")
        self.tree.heading("#0", text="BODY / PARAMETER")
        self.tree.column("#0", width=280, anchor="w")
        headings = {
            "current": "CURRENT",
            "global_max": "GLOBAL MAX",
            "global_min": "GLOBAL MIN",
            "own_max": "OWN MAX",
            "own_min": "OWN MIN",
            "status": "STATUS",
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=130, anchor="w")

        self.tree.tag_configure("param_normal", foreground=ORANGE)
        self.tree.tag_configure("param_best", foreground=GREEN)
        self.tree.tag_configure("param_global", foreground=GOLD)
        self.tree.tag_configure("body_normal", foreground=ORANGE_BRIGHT, font=(self.font_family, 10, "bold"))
        self.tree.tag_configure("body_best", foreground=GREEN, font=(self.font_family, 10, "bold"))
        self.tree.tag_configure("body_global", foreground=GOLD, font=(self.font_family, 10, "bold"))

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(
            yscrollcommand=make_autohide_grid_scrollbar(scrollbar, {"row": 0, "column": 1, "sticky": "ns"})
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.tree.bind("<Motion>", self.on_tree_motion)
        self.tree.bind("<Leave>", lambda event: self.hide_tooltip())

        self.build_statistics_tab()
        self.build_records_tab()
        self.build_bioscan_tab()

        self.refresh()

    def build_statistics_tab(self):
        tab = self.statistics_tab

        top_row = ttk.Frame(tab, style="Dark.TFrame")
        top_row.pack(fill="x", padx=12, pady=10)
        ttk.Label(
            top_row,
            text="Star type \u00d7 planet type: how many of each you've found",
            style="Dark.TLabel",
            font=(self.font_family, 11, "bold"),
        ).pack(side="left")

        self.stats_landable_var = tk.BooleanVar(value=False)
        landable_check = tk.Checkbutton(
            top_row,
            text="Landable only",
            variable=self.stats_landable_var,
            command=self.render_statistics,
            bg=BG_COLOR,
            fg=ORANGE,
            selectcolor=PANEL_COLOR,
            activebackground=BG_COLOR,
            activeforeground=ORANGE_BRIGHT,
            font=(self.font_family, 10),
            highlightthickness=0,
        )
        landable_check.pack(side="left", padx=(24, 0))

        self.stats_terraformable_var = tk.BooleanVar(value=False)
        terraformable_check = tk.Checkbutton(
            top_row,
            text="Terraformable only",
            variable=self.stats_terraformable_var,
            command=self.render_statistics,
            bg=BG_COLOR,
            fg=ORANGE,
            selectcolor=PANEL_COLOR,
            activebackground=BG_COLOR,
            activeforeground=ORANGE_BRIGHT,
            font=(self.font_family, 10),
            highlightthickness=0,
        )
        terraformable_check.pack(side="left", padx=(12, 0))

        self.stats_summary_label = ttk.Label(tab, text="", style="Dark.TLabel", font=(self.font_family, 9))
        self.stats_summary_label.pack(fill="x", padx=12, pady=(0, 6))

        canvas_frame = ttk.Frame(tab, style="Dark.TFrame")
        canvas_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.stats_canvas = tk.Canvas(canvas_frame, bg=BG_COLOR, highlightthickness=0)
        v_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.stats_canvas.yview)
        h_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.stats_canvas.xview)

        self.stats_canvas.configure(
            yscrollcommand=make_autohide_grid_scrollbar(v_scroll, {"row": 0, "column": 1, "sticky": "ns"}),
            xscrollcommand=make_autohide_grid_scrollbar(h_scroll, {"row": 1, "column": 0, "sticky": "ew"}),
        )

        self.stats_canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self._stats_resize_job = None
        self.bind("<Configure>", self.on_app_resize)

    def on_app_resize(self, event):
        # Only react to resizes of the main window itself (Configure events
        # bubble up from many child widgets in tkinter).
        if event.widget is not self:
            return
        if self._stats_resize_job is not None:
            self.after_cancel(self._stats_resize_job)
        self._stats_resize_job = self.after(150, self._render_statistics_at_current_size)

    def _render_statistics_at_current_size(self):
        # Force tkinter to finish applying the new layout right now, so the
        # width we read back is the real, final one -- rather than guessing
        # it from the window size minus estimated padding/scrollbar widths,
        # which was off by enough to leave a column cut off.
        self.update_idletasks()
        self.render_statistics(canvas_width=self.stats_canvas.winfo_width())

    def on_tab_changed(self, event):
        if self.notebook.select() == str(self.statistics_tab):
            self.render_statistics()
        elif self.notebook.select() == str(self.records_tab):
            if not self.records_loaded:
                self.render_records()
        elif self.notebook.select() == str(self.bioscan_tab):
            self.render_bioscan()

    def render_statistics(self, canvas_width: int | None = None):
        # Preserve scroll position across a live redraw, so it doesn't jump
        # back to the top every few seconds while you're looking at it.
        scroll_y = self.stats_canvas.yview()
        scroll_x = self.stats_canvas.xview()

        self.stats_canvas.delete("all")

        data = load_own_records()
        star_counts = count_primary_stars(data["system_bodies"])
        total_systems = sum(star_counts.values())
        total_stars = count_all_stars(data["system_bodies"])

        crosstab = build_type_crosstab(
            data["system_bodies"],
            landable_only=self.stats_landable_var.get(),
            terraformable_only=self.stats_terraformable_var.get(),
        )

        if not crosstab:
            self.stats_summary_label.config(
                text=f"Systems: {total_systems}   |   Stars: {total_stars}   |   Planets matching filter: 0"
            )
            self.stats_canvas.create_text(
                20, 20, anchor="nw", text="No data yet -- explore a bit first.", fill=ORANGE, font=(self.font_family, 11)
            )
            self.stats_canvas.configure(scrollregion=(0, 0, 400, 100))
            return

        row_totals, col_totals, grand_total = compute_margins(crosstab)
        self.stats_summary_label.config(
            text=f"Systems: {total_systems}   |   Stars: {total_stars}   |   Planets: {grand_total}"
        )
        star_types = sorted(crosstab.keys(), key=lambda st: -row_totals[st])
        planet_types = sorted(col_totals.keys(), key=lambda pt: -col_totals[pt])
        max_value = max(
            (crosstab[st].get(pt, 0) for st in star_types for pt in planet_types), default=1
        ) or 1

        row_header_w = 200
        col_header_h = 150
        min_cell_w = 32  # keeps 3-4 digit counts readable without capping the fit too early
        cell_h = 30

        n_cols_with_total = len(planet_types) + 1
        available_w = canvas_width if canvas_width is not None else self.stats_canvas.winfo_width()
        if available_w <= 1:
            available_w = 900  # widget not realized/measured yet -- reasonable fallback
        fitted_cell_w = (available_w - row_header_w) / n_cols_with_total
        cell_w = max(min_cell_w, fitted_cell_w)

        def color_for(value):
            if value == 0:
                return PANEL_COLOR
            # Logarithmic scale: without it, a handful of very high counts
            # would push every small value into a nearly identical dark tone.
            ratio = math.log1p(value) / math.log1p(max_value)
            r = int(10 + (255 - 10) * ratio)
            g = int(10 + (167 - 10) * ratio)
            b = int(10 + (51 - 10) * ratio)
            return f"#{r:02x}{g:02x}{b:02x}"

        n_cols = len(planet_types)
        n_rows = len(star_types)
        total_w = row_header_w + cell_w * (n_cols + 1)
        total_h = col_header_h + cell_h * (n_rows + 1)
        self.stats_canvas.configure(scrollregion=(0, 0, total_w, total_h))

        for j, pt in enumerate(planet_types):
            x = row_header_w + j * cell_w + cell_w / 2
            self.stats_canvas.create_text(
                x, col_header_h - 8, text=pt, angle=90, anchor="sw", fill=ORANGE, font=(self.font_family, 9)
            )
        x = row_header_w + n_cols * cell_w + cell_w / 2
        self.stats_canvas.create_text(
            x, col_header_h - 8, text="Total", angle=90, anchor="sw", fill=ORANGE_BRIGHT, font=(self.font_family, 9, "bold")
        )

        for i, st in enumerate(star_types):
            y = col_header_h + i * cell_h
            self.stats_canvas.create_text(
                row_header_w - 10, y + cell_h / 2, text=st, anchor="e", fill=ORANGE, font=(self.font_family, 9)
            )
            for j, pt in enumerate(planet_types):
                value = crosstab[st].get(pt, 0)
                x = row_header_w + j * cell_w
                self.stats_canvas.create_rectangle(
                    x, y, x + cell_w - 2, y + cell_h - 2, fill=color_for(value), outline=BG_COLOR
                )
                if value:
                    log_ratio = math.log1p(value) / math.log1p(max_value)
                    text_color = "#000000" if log_ratio > 0.5 else ORANGE_BRIGHT
                    self.stats_canvas.create_text(
                        x + cell_w / 2, y + cell_h / 2, text=str(value), fill=text_color, font=(self.font_family, 9)
                    )
            x = row_header_w + n_cols * cell_w
            self.stats_canvas.create_rectangle(x, y, x + cell_w - 2, y + cell_h - 2, fill=PANEL_COLOR, outline=BG_COLOR)
            self.stats_canvas.create_text(
                x + cell_w / 2, y + cell_h / 2, text=str(row_totals[st]), fill=ORANGE_BRIGHT, font=(self.font_family, 9, "bold")
            )

        y = col_header_h + n_rows * cell_h
        self.stats_canvas.create_text(
            row_header_w - 10, y + cell_h / 2, text="Total", anchor="e", fill=ORANGE_BRIGHT, font=(self.font_family, 9, "bold")
        )
        for j, pt in enumerate(planet_types):
            x = row_header_w + j * cell_w
            self.stats_canvas.create_rectangle(x, y, x + cell_w - 2, y + cell_h - 2, fill=PANEL_COLOR, outline=BG_COLOR)
            self.stats_canvas.create_text(
                x + cell_w / 2, y + cell_h / 2, text=str(col_totals[pt]), fill=ORANGE_BRIGHT, font=(self.font_family, 9, "bold")
            )
        x = row_header_w + n_cols * cell_w
        self.stats_canvas.create_rectangle(x, y, x + cell_w - 2, y + cell_h - 2, fill=ORANGE_DIM, outline=BG_COLOR)
        self.stats_canvas.create_text(
            x + cell_w / 2, y + cell_h / 2, text=str(grand_total), fill="#000000", font=(self.font_family, 9, "bold")
        )

        self.stats_canvas.yview_moveto(scroll_y[0])
        self.stats_canvas.xview_moveto(scroll_x[0])

    def build_records_tab(self):
        tab = self.records_tab
        self.records_loaded = False
        self.records_row_holders = {}
        self.records_rows_cache = []
        self.type_independent_rows_cache = []
        self.system_records_rows_cache = []

        top_row = ttk.Frame(tab, style="Dark.TFrame")
        top_row.pack(fill="x", padx=12, pady=10)
        ttk.Label(top_row, text="Filter by type:", style="Dark.TLabel", font=(self.font_family, 10)).pack(side="left")

        self.records_filter_var = tk.StringVar()
        self.records_filter_var.trace_add("write", lambda *args: self.display_records_rows())
        filter_entry = tk.Entry(
            top_row,
            textvariable=self.records_filter_var,
            bg=PANEL_COLOR,
            fg=ORANGE_BRIGHT,
            insertbackground=ORANGE_BRIGHT,
            font=(self.font_family, 10),
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=ORANGE_DIM,
            highlightcolor=ORANGE_BRIGHT,
            width=30,
        )
        filter_entry.pack(side="left", padx=8)

        tree_frame = ttk.Frame(tab, style="Dark.TFrame")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        columns = ("global_max", "own_max", "global_min", "own_min")
        self.records_tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", style="Dark.Treeview")
        self.records_tree.heading("#0", text="KIND / TYPE / PARAMETER")
        self.records_tree.column("#0", width=320, anchor="w")
        headings = {
            "global_max": "\u25c6 GLOBAL MAX",
            "own_max": "\u2605 OWN MAX",
            "global_min": "\u25c6 GLOBAL MIN",
            "own_min": "\u2605 OWN MIN",
        }
        for col in columns:
            self.records_tree.heading(col, text=headings[col])
            self.records_tree.column(col, width=160, anchor="w")

        self.records_tree.tag_configure("group", foreground=ORANGE_BRIGHT, font=(self.font_family, 10, "bold"))
        self.records_tree.tag_configure("type_row", foreground=ORANGE_BRIGHT, font=(self.font_family, 10, "bold"))
        self.records_tree.tag_configure("param_row", foreground=ORANGE)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.records_tree.yview)
        self.records_tree.configure(
            yscrollcommand=make_autohide_grid_scrollbar(scrollbar, {"row": 0, "column": 1, "sticky": "ns"})
        )
        self.records_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self.records_tree.bind("<Motion>", self.on_records_tree_motion)
        self.records_tree.bind("<Leave>", lambda event: self.hide_tooltip())

    def render_records(self):
        data = load_own_records()
        self.records_rows_cache = build_records_rows(data)
        self.type_independent_rows_cache = build_type_independent_rows(data)
        self.system_records_rows_cache = build_system_records_rows(data)
        self.records_loaded = True
        self.display_records_rows()

    def display_records_rows(self):
        for item in self.records_tree.get_children():
            self.records_tree.delete(item)
        self.records_row_holders = {}

        filter_text = self.records_filter_var.get().strip().lower()

        # --- "Best overall" groups: Stars and Planets, independent of subtype ---
        if not filter_text:
            for kind in ("star", "planet"):
                group_label = "STARS \u2014 BEST OVERALL (any type)" if kind == "star" else "PLANETS \u2014 BEST OVERALL (any type)"
                group_id = self.records_tree.insert("", "end", text=group_label, tags=("group",), open=False)
                kind_rows = [r for r in self.type_independent_rows_cache if r["kind"] == kind]
                for row in sorted(kind_rows, key=lambda r: r["parameter"]):
                    item_id = self.records_tree.insert(
                        group_id,
                        "end",
                        text=row["parameter"],
                        values=(
                            format_value(row["global_max"]),
                            format_value(row["own_max"]),
                            format_value(row["global_min"]),
                            format_value(row["own_min"]),
                        ),
                        tags=("param_row",),
                    )

                    def holder_with_type(holder, type_name):
                        if not holder:
                            return None
                        return f"{holder} [{type_name}]" if type_name else holder

                    self.records_row_holders[item_id] = {
                        "global_max": holder_with_type(row.get("global_max_holder"), row.get("global_max_type")),
                        "global_min": holder_with_type(row.get("global_min_holder"), row.get("global_min_type")),
                        "own_max": holder_with_type(row.get("own_max_holder"), row.get("own_max_type")),
                        "own_min": holder_with_type(row.get("own_min_holder"), row.get("own_min_type")),
                    }

            # --- Systems group: own records only (no EDAstro global wired up yet) ---
            group_id = self.records_tree.insert("", "end", text="SYSTEMS", tags=("group",), open=False)
            for row in self.system_records_rows_cache:
                item_id = self.records_tree.insert(
                    group_id,
                    "end",
                    text=row["parameter"],
                    values=("\u2014", format_value(row["own_max"]), "\u2014", format_value(row["own_min"])),
                    tags=("param_row",),
                )
                self.records_row_holders[item_id] = {
                    "own_max": row.get("own_max_holder"),
                    "own_min": row.get("own_min_holder"),
                }

        # --- Breakdown by specific type (filterable) ---
        by_kind_type = {}
        for row in self.records_rows_cache:
            if filter_text and filter_text not in row["type"].lower():
                continue
            by_kind_type.setdefault((row["kind"], row["type"]), []).append(row)

        for kind in ("star", "planet"):
            type_keys = sorted(
                (k for k in by_kind_type if k[0] == kind), key=lambda k: natural_sort_key(k[1])
            )
            if not type_keys:
                continue

            group_label = "STARS BY TYPE" if kind == "star" else "PLANETS BY TYPE"
            group_id = self.records_tree.insert(
                "", "end", text=f"{group_label}  ({len(type_keys)} types)", tags=("group",), open=False
            )

            for kind_, type_name in type_keys:
                type_rows = by_kind_type[(kind_, type_name)]
                type_id = self.records_tree.insert(
                    group_id, "end", text=type_name, values=("", "", "", ""), tags=("type_row",), open=False
                )
                for row in sorted(type_rows, key=lambda r: r["parameter"]):
                    item_id = self.records_tree.insert(
                        type_id,
                        "end",
                        text=row["parameter"],
                        values=(
                            format_value(row["global_max"]),
                            format_value(row["own_max"]),
                            format_value(row["global_min"]),
                            format_value(row["own_min"]),
                        ),
                        tags=("param_row",),
                    )
                    self.records_row_holders[item_id] = {
                        "global_max": row.get("global_max_holder"),
                        "global_min": row.get("global_min_holder"),
                        "own_max": row.get("own_max_holder"),
                        "own_min": row.get("own_min_holder"),
                    }

    def on_records_tree_motion(self, event):
        region = self.records_tree.identify_region(event.x, event.y)
        if region != "cell":
            self.hide_tooltip()
            return

        row_id = self.records_tree.identify_row(event.y)
        col_id = self.records_tree.identify_column(event.x)
        col_map = {"#1": "global_max", "#2": "own_max", "#3": "global_min", "#4": "own_min"}
        col_key = col_map.get(col_id)

        if not col_key or row_id not in self.records_row_holders:
            self.hide_tooltip()
            return

        holder = self.records_row_holders[row_id].get(col_key)
        if not holder:
            self.hide_tooltip()
            return

        self.show_tooltip(holder, event.x_root, event.y_root)

    def build_bioscan_tab(self):
        tab = self.bioscan_tab
        self.previous_bio_species_keys = None  # None = not yet initialized, so we don't announce on first load

        top_row = ttk.Frame(tab, style="Dark.TFrame")
        top_row.pack(fill="x", padx=12, pady=10)
        ttk.Label(
            top_row,
            text="Species / subspecies / color variants scanned",
            style="Dark.TLabel",
            font=(self.font_family, 11, "bold"),
        ).pack(side="left")

        self.bioscan_summary_label = ttk.Label(tab, text="", style="Dark.TLabel", font=(self.font_family, 9))
        self.bioscan_summary_label.pack(fill="x", padx=12, pady=(0, 6))

        tree_frame = ttk.Frame(tab, style="Dark.TFrame")
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        columns = ("count", "first_seen", "system")
        self.bioscan_tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", style="Dark.Treeview")
        self.bioscan_tree.heading("#0", text="GENUS / SPECIES / VARIANT")
        self.bioscan_tree.column("#0", width=320, anchor="w")
        headings = {"count": "COUNT", "first_seen": "FIRST SEEN", "system": "SYSTEM"}
        for col in columns:
            self.bioscan_tree.heading(col, text=headings[col])
            self.bioscan_tree.column(col, width=160, anchor="w")

        self.bioscan_tree.tag_configure("genus_row", foreground=ORANGE_BRIGHT, font=(self.font_family, 10, "bold"))
        self.bioscan_tree.tag_configure("species_row", foreground=ORANGE, font=(self.font_family, 10, "bold"))
        self.bioscan_tree.tag_configure("variant_row", foreground=ORANGE)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.bioscan_tree.yview)
        self.bioscan_tree.configure(
            yscrollcommand=make_autohide_grid_scrollbar(scrollbar, {"row": 0, "column": 1, "sticky": "ns"})
        )
        self.bioscan_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

    def check_new_bio_species(self, bio_species: dict) -> set:
        """
        Compares the current set of scanned genus/species/variant combos
        against the last known set, and announces (global status + voice)
        any that are newly discovered. Runs every refresh cycle regardless
        of which tab is active, so you don't have to be looking at the
        Bioscan Stats tab to get notified. Returns the set of newly-added
        keys, so the tree can auto-expand to reveal them.
        """
        current_keys = set(bio_species.keys())
        new_keys = set()
        if self.previous_bio_species_keys is not None:
            new_keys = current_keys - self.previous_bio_species_keys
            for key in new_keys:
                genus, species, variant = key.split("|", 2)
                label = f"{species} \u2014 {variant}" if variant else species
                self.global_status_label.config(text=f"\u2605 New species scanned: {label}")
                if self.voice_var.get():
                    phrase = (
                        f"New species discovered. {species}. {variant}." if variant else f"New species discovered. {species}."
                    )
                    speak(phrase)
        self.previous_bio_species_keys = current_keys
        return new_keys

    def render_bioscan(self, bio_species: dict | None = None, newly_added_keys: set | None = None):
        if bio_species is None:
            bio_species = load_own_records()["bio_species"]
        newly_added_keys = newly_added_keys or set()

        force_open_genus = set()
        force_open_species = set()
        for key in newly_added_keys:
            genus, species, variant = key.split("|", 2)
            force_open_genus.add(genus)
            force_open_species.add((genus, species))

        # Preserve which genus/species nodes were manually expanded, so a live
        # rebuild every few seconds doesn't collapse everything. Uses stable
        # iids (genus/species name only) rather than the displayed label text
        # (which changes whenever a count updates, breaking a text-based match).
        old_open = {}
        for genus_iid in self.bioscan_tree.get_children():
            old_open[genus_iid] = bool(self.bioscan_tree.item(genus_iid, "open"))
            for species_iid in self.bioscan_tree.get_children(genus_iid):
                old_open[species_iid] = bool(self.bioscan_tree.item(species_iid, "open"))

        # --- Build the tree ---
        for item in self.bioscan_tree.get_children():
            self.bioscan_tree.delete(item)

        by_genus = {}
        for key, entry in bio_species.items():
            genus, species, variant = key.split("|", 2)
            by_genus.setdefault(genus, {}).setdefault(species, []).append((variant, entry))

        total_variants = len(bio_species)
        total_species = len({k.split("|", 2)[1] for k in bio_species})
        total_genera = len(by_genus)
        self.bioscan_summary_label.config(
            text=(
                f"Genera: {total_genera}/{TOTAL_KNOWN_GENERA}   |   "
                f"Species: {total_species}/{TOTAL_KNOWN_SPECIES}   |   "
                f"Variants: {total_variants}/{TOTAL_KNOWN_VARIANTS}"
            )
        )

        for genus in sorted(by_genus.keys(), key=natural_sort_key):
            species_map = by_genus[genus]
            genus_variant_count = sum(len(variants) for variants in species_map.values())
            genus_species_total = GENUS_SPECIES_TOTALS.get(genus)
            genus_variant_total = GENUS_VARIANT_TOTALS.get(genus)
            species_part = (
                f"{len(species_map)}/{genus_species_total} species" if genus_species_total else f"{len(species_map)} species"
            )
            variant_part = (
                f"{genus_variant_count}/{genus_variant_total} variants"
                if genus_variant_total
                else f"{genus_variant_count} variants"
            )
            genus_label = f"{genus}  ({species_part}, {variant_part})"
            genus_iid = f"genus::{genus}"
            genus_open = genus in force_open_genus or old_open.get(genus_iid, False)
            genus_id = self.bioscan_tree.insert(
                "", "end", iid=genus_iid, text=genus_label, tags=("genus_row",), open=genus_open
            )
            for species in sorted(species_map.keys(), key=natural_sort_key):
                variants = species_map[species]
                species_variant_total = SPECIES_VARIANT_TOTALS.get(species)
                species_variant_part = (
                    f"{len(variants)}/{species_variant_total} variants"
                    if species_variant_total
                    else f"{len(variants)} variants"
                )
                species_label = f"{species}  ({species_variant_part})"
                species_iid = f"species::{genus}::{species}"
                species_open = (genus, species) in force_open_species or old_open.get(species_iid, False)
                species_id = self.bioscan_tree.insert(
                    genus_id,
                    "end",
                    iid=species_iid,
                    text=species_label,
                    tags=("species_row",),
                    open=species_open,
                )
                for variant, entry in sorted(variants, key=lambda v: natural_sort_key(v[0])):
                    first_seen = (entry.get("first_seen") or "")[:10]  # just the date part
                    self.bioscan_tree.insert(
                        species_id,
                        "end",
                        text=variant or "(no variant)",
                        values=(entry.get("count", 1), first_seen, entry.get("system_name") or "\u2014"),
                        tags=("variant_row",),
                    )

    def apply_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        base_font = (self.font_family, 10)
        header_font = (self.font_family, 10, "bold")

        style.configure("Dark.TFrame", background=BG_COLOR)
        style.configure("Dark.TLabel", background=BG_COLOR, foreground=ORANGE, font=base_font)

        style.configure(
            "Dark.TButton",
            background=PANEL_COLOR,
            foreground=ORANGE,
            bordercolor=ORANGE,
            focusthickness=1,
            focuscolor=ORANGE,
            font=header_font,
            padding=6,
        )
        style.map(
            "Dark.TButton",
            background=[("active", ORANGE_DIM), ("pressed", ORANGE_DIM)],
            foreground=[("active", "#000000"), ("pressed", "#000000")],
        )

        style.configure(
            "Subtle.TButton",
            background=BG_COLOR,
            foreground=ORANGE_DIM,
            bordercolor=ORANGE_DIM,
            focusthickness=0,
            font=base_font,
            padding=4,
        )
        style.map(
            "Subtle.TButton",
            background=[("active", PANEL_COLOR), ("pressed", PANEL_COLOR)],
            foreground=[("active", ORANGE), ("pressed", ORANGE)],
        )

        style.configure("Dark.TNotebook", background=BG_COLOR, bordercolor=ORANGE_DIM)
        style.configure(
            "Dark.TNotebook.Tab",
            background=PANEL_COLOR,
            foreground=ORANGE,
            font=header_font,
            padding=(14, 6),
        )
        style.map(
            "Dark.TNotebook.Tab",
            background=[("selected", ORANGE_DIM)],
            foreground=[("selected", ORANGE_BRIGHT)],
        )

        style.configure(
            "Dark.Treeview",
            background=BG_COLOR,
            fieldbackground=BG_COLOR,
            foreground=ORANGE,
            font=base_font,
            rowheight=24,
            bordercolor=ORANGE_DIM,
            borderwidth=1,
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=PANEL_COLOR,
            foreground=ORANGE_BRIGHT,
            font=header_font,
            relief="flat",
        )
        style.map("Dark.Treeview.Heading", background=[("active", ORANGE_DIM)])
        style.map(
            "Dark.Treeview",
            background=[("selected", ORANGE_DIM)],
            foreground=[("selected", "#000000")],
        )

    def build_menu(self):
        menu_bar_frame = tk.Frame(self, bg=PANEL_COLOR)
        menu_bar_frame.pack(fill="x", side="top")

        actions_button = tk.Menubutton(
            menu_bar_frame,
            text="Actions",
            bg=PANEL_COLOR,
            fg=ORANGE,
            activebackground=ORANGE_DIM,
            activeforeground="#000000",
            font=(self.font_family, 10),
            bd=0,
            padx=10,
            pady=4,
            relief="flat",
        )
        actions_button.pack(side="left")

        actions_menu = tk.Menu(
            actions_button, tearoff=0, bg=PANEL_COLOR, fg=ORANGE, activebackground=ORANGE_DIM, activeforeground="#000000"
        )
        actions_menu.add_command(label="Update from Journal", command=self.on_manual_update)
        actions_menu.add_separator()
        actions_menu.add_command(label="Rebuild Own Records (full)", command=self.on_rebuild_own_records)
        actions_menu.add_command(label="Force EDAstro Refresh", command=self.on_force_edastro_refresh)
        actions_menu.add_command(label="Update Bio Reference Data", command=self.on_update_bio_reference)
        actions_menu.add_separator()
        actions_menu.add_command(label="Settings...", command=self.open_settings_dialog)
        actions_button.config(menu=actions_menu)

        help_button = tk.Menubutton(
            menu_bar_frame,
            text="Help",
            bg=PANEL_COLOR,
            fg=ORANGE,
            activebackground=ORANGE_DIM,
            activeforeground="#000000",
            font=(self.font_family, 10),
            bd=0,
            padx=10,
            pady=4,
            relief="flat",
        )
        help_button.pack(side="left")

        help_menu = tk.Menu(
            help_button, tearoff=0, bg=PANEL_COLOR, fg=ORANGE, activebackground=ORANGE_DIM, activeforeground="#000000"
        )
        help_menu.add_command(label="About", command=self.open_about_dialog)
        help_button.config(menu=help_menu)

    def open_settings_dialog(self):
        current = load_settings()

        dialog = tk.Toplevel(self, bg=BG_COLOR)
        dialog.title("Settings")
        dialog.configure(bg=BG_COLOR)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        label_font = (self.font_family, 10)
        entry_kwargs = dict(
            bg=PANEL_COLOR,
            fg=ORANGE_BRIGHT,
            insertbackground=ORANGE_BRIGHT,
            font=label_font,
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=ORANGE_DIM,
            highlightcolor=ORANGE_BRIGHT,
        )

        pad = dict(padx=12, pady=(10, 0))

        tk.Label(dialog, text="Journal folder:", bg=BG_COLOR, fg=ORANGE, font=label_font).grid(
            row=0, column=0, sticky="w", **pad
        )
        journal_dir_var = tk.StringVar(value=current.get("journal_dir") or JOURNAL_DIR)
        journal_entry = tk.Entry(dialog, textvariable=journal_dir_var, width=48, **entry_kwargs)
        journal_entry.grid(row=1, column=0, columnspan=2, sticky="we", padx=12)

        def browse_folder():
            chosen = filedialog.askdirectory(title="Select journal folder")
            if chosen:
                journal_dir_var.set(chosen)

        ttk.Button(dialog, text="Browse...", command=browse_folder, style="Subtle.TButton").grid(
            row=1, column=2, padx=(6, 12)
        )

        tk.Label(dialog, text="Auto-refresh interval (ms):", bg=BG_COLOR, fg=ORANGE, font=label_font).grid(
            row=2, column=0, sticky="w", **pad
        )
        auto_refresh_var = tk.StringVar(value=str(current.get("auto_refresh_ms") or AUTO_REFRESH_MS))
        tk.Entry(dialog, textvariable=auto_refresh_var, width=12, **entry_kwargs).grid(
            row=3, column=0, sticky="w", padx=12
        )

        tk.Label(dialog, text="EDAstro cache max age (days):", bg=BG_COLOR, fg=ORANGE, font=label_font).grid(
            row=4, column=0, sticky="w", **pad
        )
        cache_age_var = tk.StringVar(
            value=str(current.get("edastro_cache_max_age_days") or EDASTRO_CACHE_MAX_AGE_DAYS)
        )
        tk.Entry(dialog, textvariable=cache_age_var, width=12, **entry_kwargs).grid(
            row=5, column=0, sticky="w", padx=12
        )

        note = tk.Label(
            dialog,
            text="Changes take effect after restarting the app.",
            bg=BG_COLOR,
            fg=ORANGE_DIM,
            font=(self.font_family, 9),
        )
        note.grid(row=6, column=0, columnspan=3, sticky="w", padx=12, pady=(12, 0))

        def on_save():
            try:
                auto_refresh_ms = int(auto_refresh_var.get())
                cache_age_days = int(cache_age_var.get())
            except ValueError:
                messagebox.showerror("Invalid input", "Auto-refresh interval and cache age must be whole numbers.")
                return

            save_settings(
                {
                    "journal_dir": journal_dir_var.get().strip() or None,
                    "auto_refresh_ms": auto_refresh_ms,
                    "edastro_cache_max_age_days": cache_age_days,
                }
            )
            messagebox.showinfo("Settings saved", "Restart the app for the changes to take effect.")
            dialog.destroy()

        button_row = tk.Frame(dialog, bg=BG_COLOR)
        button_row.grid(row=7, column=0, columnspan=3, sticky="e", padx=12, pady=12)
        ttk.Button(button_row, text="Cancel", command=dialog.destroy, style="Subtle.TButton").pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(button_row, text="Save", command=on_save, style="Dark.TButton").pack(side="right")

    def open_about_dialog(self):
        dialog = tk.Toplevel(self, bg=BG_COLOR)
        dialog.title("About")
        dialog.configure(bg=BG_COLOR)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(dialog, text=APP_NAME, bg=BG_COLOR, fg=ORANGE_BRIGHT, font=(self.font_family, 14, "bold")).pack(
            padx=24, pady=(20, 4)
        )
        tk.Label(dialog, text=f"Version {APP_VERSION}", bg=BG_COLOR, fg=ORANGE, font=(self.font_family, 10)).pack()
        tk.Label(
            dialog,
            text="Tracks your Elite Dangerous exploration finds against\nyour own history and EDAstro.com community records.",
            bg=BG_COLOR,
            fg=ORANGE,
            font=(self.font_family, 9),
            justify="center",
        ).pack(padx=24, pady=(10, 4))
        tk.Label(
            dialog,
            text="Data sources: EDAstro.com, Elite Dangerous journal files",
            bg=BG_COLOR,
            fg=ORANGE_DIM,
            font=(self.font_family, 8),
            justify="center",
        ).pack(padx=24, pady=(4, 16))
        ttk.Button(dialog, text="Close", command=dialog.destroy, style="Subtle.TButton").pack(pady=(0, 16))

    def on_manual_update(self):
        self.refresh()
        # Current System, Bioscan Stats, and Body Stats all refresh live
        # every cycle now; only Records deliberately doesn't (browsing a
        # type-filtered list shouldn't get redrawn out from under you), so
        # an explicit manual update should still refresh it if it's active.
        if self.notebook.select() == str(self.records_tab):
            self.render_records()

    def on_rebuild_own_records(self):
        answer = messagebox.askyesno(
            "Rebuild Own Records",
            "This replays your entire journal history from scratch and can take a while. "
            "The window will be unresponsive until it's done. Continue?",
        )
        if not answer:
            return

        def report(msg):
            self.global_status_label.config(text=msg)
            self.update_idletasks()

        self.global_status_label.config(text="Rebuilding own records...")
        self.update_idletasks()
        try:
            rebuild_own_records(JOURNAL_DIR, progress_callback=report)
        except JournalAccessError as exc:
            messagebox.showerror("Error", str(exc))
            return
        self.refresh()

    def on_force_edastro_refresh(self):
        answer = messagebox.askyesno(
            "Force EDAstro Refresh",
            "This re-downloads every tracked EDAstro attribute page, ignoring the 7-day cache. "
            "The window will be unresponsive until it's done. Continue?",
        )
        if not answer:
            return

        def report(msg):
            self.global_status_label.config(text=msg)
            self.update_idletasks()

        self.global_status_label.config(text="Refreshing EDAstro data...")
        self.update_idletasks()
        refresh_all_cached_attributes(progress_callback=report)
        self.refresh()

    def on_update_bio_reference(self):
        answer = messagebox.askyesno(
            "Update Bio Reference Data",
            "This re-downloads the latest genus/species/variant reference data from the "
            "EDMC-BioScan and EDMC-ExploData GitHub projects, in case Frontier has added new "
            "species (like Radicoida in 2026). Requires an internet connection. "
            "The window will be unresponsive until it's done, and the app will need a restart "
            "for the new data to take effect. Continue?",
        )
        if not answer:
            return

        def report(msg):
            self.global_status_label.config(text=msg)
            self.update_idletasks()

        self.global_status_label.config(text="Updating bio reference data...")
        self.update_idletasks()
        try:
            changes = update_bio_reference(progress_callback=report)
        except Exception as exc:
            self.global_status_label.config(text="")
            messagebox.showerror("Update failed", f"Could not update bio reference data:\n{exc}")
            return

        self.global_status_label.config(text="")
        if changes:
            change_text = "\n".join(changes[:30])
            if len(changes) > 30:
                change_text += f"\n... and {len(changes) - 30} more"
            messagebox.showinfo(
                "Bio reference data updated",
                f"{len(changes)} change(s) found and saved:\n\n{change_text}\n\n"
                "Restart the app for the new data to take effect.",
            )
        else:
            messagebox.showinfo("Bio reference data updated", "No changes -- your reference data was already up to date.")

    def on_auto_refresh_toggle(self):
        if self.auto_refresh_var.get():
            self.refresh()
        else:
            if self.refresh_job_id is not None:
                self.after_cancel(self.refresh_job_id)
                self.refresh_job_id = None

    def refresh(self):
        # Cancel any pending auto-refresh job before running, so a manual
        # "Update from Journal" click doesn't leave a duplicate timer scheduled.
        if self.refresh_job_id is not None:
            self.after_cancel(self.refresh_job_id)
            self.refresh_job_id = None

        # Avoid starting a second background refresh while one is still running
        # (e.g. a slow/unreachable network path taking a while to time out).
        if getattr(self, "_refresh_in_progress", False):
            return
        self._refresh_in_progress = True

        # Snapshot own records BEFORE updating them this tick, so a record set
        # just now compares against the previous best (shows up as strictly
        # better) instead of being compared against itself post-update.
        previous_own_records = load_own_records()["records"]

        thread = threading.Thread(target=self._refresh_worker, args=(previous_own_records,), daemon=True)
        thread.start()

    def _refresh_worker(self, previous_own_records: dict):
        """
        Runs on a background thread: does all the potentially slow work (journal
        folder access check, reading/parsing files, EDAstro lookups) without
        touching any tkinter widgets. Hands the result back to the main thread
        via self.after(0, ...), since tkinter isn't thread-safe.
        """
        try:
            data = build_or_update_own_records(JOURNAL_DIR)

            system_name = data["current_system_name"]
            scans = list(data["system_bodies"].get(system_name, {}).values()) if system_name else []
            rows = build_current_system_rows(scans, previous_own_records)
            rows = annotate_rows(rows)

            current_body_count = data["system_body_counts"].get(system_name) if system_name else None
            system_records = data["system_records"]
            current_tally = data["system_tallies"].get(system_name, {}) if system_name else {}
            current_values = {"bodyCount": current_body_count, **current_tally}
            stats_parts = build_system_stats_parts(current_values, system_records)

            result = {
                "ok": True,
                "system_name": system_name,
                "scans": scans,
                "rows": rows,
                "data_version": (data["last_file"], data["last_line"]),
                "stats_parts": stats_parts,
                "bio_species": data["bio_species"],
            }
        except JournalAccessError as exc:
            result = {"ok": False, "kind": "access", "message": str(exc)}
        except Exception as exc:
            result = {"ok": False, "kind": "other", "message": f"{type(exc).__name__}: {exc}"}

        self.after(0, self._apply_refresh_result, result)

    def render_system_stats(self, parts: list[tuple[str, bool]]):
        """Fills the system-stats Text widget with per-metric colored segments."""
        self.system_stats_text.config(state="normal")
        self.system_stats_text.delete("1.0", "end")
        for i, (text, is_record) in enumerate(parts):
            self.system_stats_text.insert("end", text, ("record" if is_record else "normal",))
            if i < len(parts) - 1:
                self.system_stats_text.insert("end", "   |   ", ("normal",))
        self.system_stats_text.config(state="disabled")

    def _apply_refresh_result(self, result: dict):
        self._refresh_in_progress = False

        if not result["ok"]:
            if result["kind"] == "access":
                self.system_label.config(text="(unknown system)")
                self.info_label.config(text="")
                self.global_status_label.config(text=f"\u26a0 Journal folder not reachable: {result['message']}")
                # Auto-disable live auto-refresh so an unreachable network path
                # doesn't get hammered every few seconds -- the user can turn
                # it back on (or click "Update from Journal") once it's back.
                if self.auto_refresh_var.get():
                    self.auto_refresh_var.set(False)
                    messagebox.showwarning(
                        "Journal folder not reachable",
                        f"{result['message']}\n\nLive auto-refresh has been turned off. "
                        "Re-enable it or click \"Update from Journal\" once the folder is reachable again.",
                    )
            else:
                self.system_label.config(text="(unknown system)")
                self.info_label.config(text="")
                self.global_status_label.config(text=f"\u26a0 Error while refreshing: {result['message']}")
            self.last_updated_label.config(text=f"Last attempt: {time.strftime('%H:%M:%S')}")
            self.render_system_stats([])
            if self.auto_refresh_var.get():
                self.refresh_job_id = self.after(AUTO_REFRESH_MS, self.refresh)
            return

        system_name = result["system_name"]
        scans = result["scans"]
        rows = result["rows"]

        self.system_label.config(text=system_name or "(unknown system)")
        self.info_label.config(text=f"{len(scans)} bodies scanned")
        self.global_status_label.config(text="")
        self.last_updated_label.config(text=f"Last updated: {time.strftime('%H:%M:%S')}")
        self.render_system_stats(result["stats_parts"])

        self.announce_new_records(rows)
        new_bio_keys = self.check_new_bio_species(result["bio_species"])
        self.render_bioscan(result["bio_species"], newly_added_keys=new_bio_keys)

        # Remember which body rows the user had manually expanded, so a
        # refresh doesn't collapse everything back to the default state.
        expand_state = {}
        for iid in self.tree.get_children():
            label = self.tree.item(iid, "text")
            expand_state[label] = bool(self.tree.item(iid, "open"))

        self.display_rows(rows, system_name, expand_state)
        self.render_statistics()

        if self.auto_refresh_var.get():
            self.refresh_job_id = self.after(AUTO_REFRESH_MS, self.refresh)

    def announce_new_records(self, rows: list[dict]):
        """
        Speaks a short phrase for any row whose status just became a record
        (new personal best or beats global) since the previous refresh.
        Skips announcing on the very first load, so existing records don't
        all get read out at once on startup.
        """
        current_statuses = {}
        newly_achieved = []

        for row in rows:
            key = (row["body_name"], row["param_slug"])
            status = row["status"]
            current_statuses[key] = status

            if status == STATUS_NORMAL:
                continue

            previous_status = self.previous_statuses.get(key)
            if self.first_refresh_done and previous_status != status:
                newly_achieved.append(row)

        self.previous_statuses = current_statuses
        self.first_refresh_done = True

        if not self.voice_var.get():
            return

        for row in newly_achieved:
            if row["status"] == STATUS_NEW_PERSONAL_BEST:
                phrase = f"New personal best. {row['parameter']}, {row['body_name']}."
            else:
                phrase = f"Global record beaten. {row['parameter']}, {row['body_name']}."
            speak(phrase)

    def on_tree_motion(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region != "cell":
            self.hide_tooltip()
            return

        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        col_map = {"#2": "global_max", "#3": "global_min", "#4": "own_max", "#5": "own_min"}
        col_key = col_map.get(col_id)

        if not col_key or row_id not in self.row_holders:
            self.hide_tooltip()
            return

        holder = self.row_holders[row_id].get(col_key)
        if not holder:
            self.hide_tooltip()
            return

        self.show_tooltip(holder, event.x_root, event.y_root)

    def show_tooltip(self, text: str, x: int, y: int):
        if self.tooltip_window is not None:
            self._tooltip_label.config(text=text)
            self.tooltip_window.wm_geometry(f"+{x + 15}+{y + 10}")
            return

        tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x + 15}+{y + 10}")
        label = tk.Label(
            tw,
            text=text,
            bg=PANEL_COLOR,
            fg=ORANGE_BRIGHT,
            font=(self.font_family, 9),
            bd=1,
            relief="solid",
            padx=6,
            pady=3,
        )
        label.pack()
        self.tooltip_window = tw
        self._tooltip_label = label

    def hide_tooltip(self):
        if self.tooltip_window is not None:
            self.tooltip_window.destroy()
            self.tooltip_window = None

    def display_rows(self, rows: list[dict], system_name: str = None, expand_state: dict = None):
        expand_state = expand_state or {}
        self.hide_tooltip()
        self.row_holders = {}

        for item in self.tree.get_children():
            self.tree.delete(item)

        # Group rows by body_name, preserving first-seen order.
        bodies = {}
        for row in rows:
            bodies.setdefault(row["body_name"], []).append(row)

        only_records = self.filter_var.get()

        for body_name, body_rows in sorted(bodies.items(), key=lambda item: natural_sort_key(item[0])):
            body_type = body_rows[0]["type"]
            statuses = [r["status"] for r in body_rows]
            if STATUS_BEATS_GLOBAL in statuses:
                overall = STATUS_BEATS_GLOBAL
            elif STATUS_NEW_PERSONAL_BEST in statuses:
                overall = STATUS_NEW_PERSONAL_BEST
            else:
                overall = STATUS_NORMAL

            display_rows_for_body = body_rows
            if only_records:
                display_rows_for_body = [r for r in body_rows if r["status"] != STATUS_NORMAL]
                if not display_rows_for_body:
                    continue  # nothing interesting on this body -> hide it entirely

            body_tag = {
                STATUS_NEW_PERSONAL_BEST: "body_best",
                STATUS_BEATS_GLOBAL: "body_global",
                STATUS_NORMAL: "body_normal",
            }[overall]

            label = f"{short_body_label(body_name, system_name)}  \u2014  {body_type}"
            body_id = self.tree.insert(
                "",
                "end",
                text=label,
                values=("", "", "", "", "", STATUS_LABELS[overall]),
                tags=(body_tag,),
                open=expand_state.get(label, False),
            )

            for row in display_rows_for_body:
                marked = {
                    "current": format_value(row["current_value"]),
                    "global_max": format_value(row["global_max"]),
                    "global_min": format_value(row["global_min"]),
                    "own_max": format_value(row["own_max"]),
                    "own_min": format_value(row["own_min"]),
                }
                matched_field = row.get("matched_field")
                if matched_field:
                    symbol = "\u2605" if row["status"] == STATUS_NEW_PERSONAL_BEST else "\u25c6"
                    marked[matched_field] = f"{symbol} {marked[matched_field]}"

                item_id = self.tree.insert(
                    body_id,
                    "end",
                    text=row["parameter"],
                    values=(
                        marked["current"],
                        marked["global_max"],
                        marked["global_min"],
                        marked["own_max"],
                        marked["own_min"],
                        STATUS_LABELS[row["status"]],
                    ),
                    tags=("param_normal",),
                )
                self.row_holders[item_id] = {
                    "global_max": row.get("global_max_holder"),
                    "global_min": row.get("global_min_holder"),
                    "own_max": row.get("own_max_holder"),
                    "own_min": row.get("own_min_holder"),
                }


if __name__ == "__main__":
    app = RecordsApp()
    app.mainloop()
