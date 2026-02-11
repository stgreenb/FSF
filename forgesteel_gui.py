"""
Forgesteel to Foundry VTT Converter - GUI
Launch with: python forgesteel_gui.py
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import logging
import json
from pathlib import Path

from converter.loader import load_forgesteel_character, load_compendium_items
from converter.mapper import convert_character
from converter.writer import write_foundry_character

# ---------------------------------------------------------------------------
# Color palette & style constants
# ---------------------------------------------------------------------------
BG_DARK = "#1a1b26"
BG_MID = "#24283b"
BG_CARD = "#2f3349"
BG_INPUT = "#1e2030"
FG_PRIMARY = "#c0caf5"
FG_DIM = "#6b7089"
FG_ACCENT = "#7aa2f7"
FG_SUCCESS = "#9ece6a"
FG_ERROR = "#f7768e"
FG_WARN = "#e0af68"
BORDER = "#3b4261"
ACCENT_BTN = "#7aa2f7"
ACCENT_BTN_HOVER = "#89b4fa"
ACCENT_BTN_PRESS = "#5d7ec7"
HELP_BTN = "#bb9af7"
HELP_BTN_HOVER = "#cba6ff"


def _resolve_fonts():
    """Pick the first available font families, falling back to universal defaults."""
    try:
        import tkinter.font as tkfont
        _probe = tk.Tk()
        _probe.withdraw()
        available = set(tkfont.families())
        _probe.destroy()
    except Exception:
        available = set()

    ui = "TkDefaultFont"
    for candidate in ("Segoe UI", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"):
        if candidate in available:
            ui = candidate
            break

    mono = "TkFixedFont"
    for candidate in ("Consolas", "SF Mono", "DejaVu Sans Mono", "Liberation Mono", "Courier New"):
        if candidate in available:
            mono = candidate
            break

    return ui, mono


FONT_FAMILY, MONO_FAMILY = _resolve_fonts()
FONT = (FONT_FAMILY, 10)
FONT_SM = (FONT_FAMILY, 9)
FONT_LG = (FONT_FAMILY, 12)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_BOLD_SM = (FONT_FAMILY, 9, "bold")
FONT_BOLD_LG = (FONT_FAMILY, 11, "bold")
FONT_BOLD_XL = (FONT_FAMILY, 14, "bold")
FONT_HEADER = (FONT_FAMILY, 18, "bold")
MONO = (MONO_FAMILY, 10)
MONO_SM = (MONO_FAMILY, 9)


class TextHandler(logging.Handler):
    """Route log records into a Tkinter Text widget."""

    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text = text_widget
        self._color_map = {
            "DEBUG": FG_DIM,
            "INFO": FG_PRIMARY,
            "WARNING": FG_WARN,
            "ERROR": FG_ERROR,
            "CRITICAL": FG_ERROR,
        }

    def emit(self, record):
        msg = self.format(record) + "\n"
        color = self._color_map.get(record.levelname, FG_PRIMARY)
        tag = f"level_{record.levelname}"

        def _append():
            self.text.configure(state="normal")
            self.text.tag_configure(tag, foreground=color)
            self.text.insert(tk.END, msg, tag)
            self.text.see(tk.END)
            self.text.configure(state="disabled")

        self.text.after(0, _append)


class HoverButton(tk.Canvas):
    """Flat button drawn on a Canvas with hover / press states."""

    def __init__(
        self,
        parent,
        text="",
        command=None,
        bg=ACCENT_BTN,
        hover=ACCENT_BTN_HOVER,
        press=ACCENT_BTN_PRESS,
        fg="#1a1b26",
        canvas_bg=None,
        width=160,
        height=38,
        radius=8,
        font=FONT_BOLD,
        **kw,
    ):
        # Resolve parent background: try tk widget key, fall back to default
        if canvas_bg is None:
            try:
                canvas_bg = parent.cget("background")
            except Exception:
                canvas_bg = BG_DARK
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=canvas_bg,
            highlightthickness=0,
            **kw,
        )
        self._bg = bg
        self._hover = hover
        self._press = press
        self._fg = fg
        self._cmd = command
        self._bw = width
        self._bh = height
        self._r = radius
        self._font = font
        self._text = text
        self._disabled = False
        self._draw(bg)
        self.bind("<Enter>", lambda e: self._draw(self._hover) if not self._disabled else None)
        self.bind("<Leave>", lambda e: self._draw(self._bg) if not self._disabled else None)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kw)

    def _draw(self, fill):
        self.delete("all")
        self._rounded_rect(0, 0, self._bw, self._bh, self._r, fill=fill, outline="")
        txt_color = self._fg if not self._disabled else FG_DIM
        self.create_text(
            self._bw // 2,
            self._bh // 2,
            text=self._text,
            fill=txt_color,
            font=self._font,
        )

    def _on_press(self, _event):
        if not self._disabled:
            self._draw(self._press)

    def _on_release(self, _event):
        if not self._disabled:
            self._draw(self._hover)
            if self._cmd:
                self._cmd()

    def set_disabled(self, state: bool):
        self._disabled = state
        self._draw(BORDER if state else self._bg)

    def set_text(self, text: str):
        self._text = text
        self._draw(self._bg)


class ForgesteelGUI(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.title("Forgesteel \u2192 Foundry VTT Converter")
        self.configure(bg=BG_DARK)
        self.minsize(720, 620)
        self.geometry("780x680")
        self.resizable(True, True)

        # Try setting icon if available
        try:
            self.iconbitmap(default="")
        except Exception:
            # Some platforms or environments may not support setting a window icon;
            # ignore these non-critical errors and proceed with the default icon.
            pass

        self._build_styles()
        self._build_ui()
        self._attach_logger()

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------
    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=BG_DARK, foreground=FG_PRIMARY, fieldbackground=BG_INPUT)
        style.configure("TFrame", background=BG_DARK)
        style.configure("Card.TFrame", background=BG_CARD)
        style.configure("TLabel", background=BG_DARK, foreground=FG_PRIMARY, font=FONT)
        style.configure("Card.TLabel", background=BG_CARD, foreground=FG_PRIMARY, font=FONT)
        style.configure("Header.TLabel", background=BG_DARK, foreground=FG_ACCENT, font=FONT_HEADER)
        style.configure("Sub.TLabel", background=BG_DARK, foreground=FG_DIM, font=FONT_SM)
        style.configure("Section.TLabel", background=BG_DARK, foreground=FG_ACCENT, font=FONT_BOLD_LG)
        style.configure(
            "TCheckbutton",
            background=BG_CARD,
            foreground=FG_PRIMARY,
            font=FONT,
            indicatorcolor=BG_INPUT,
        )
        style.map(
            "TCheckbutton",
            background=[("active", BG_CARD)],
            indicatorcolor=[("selected", FG_ACCENT)],
        )
        style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG_PRIMARY, insertcolor=FG_PRIMARY)

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = ttk.Frame(self, padding=24)
        outer.pack(fill="both", expand=True)

        # ---- Header row (title + help button) ----
        hdr_row = ttk.Frame(outer)
        hdr_row.pack(fill="x")

        ttk.Label(hdr_row, text="Forgesteel \u2192 Foundry VTT", style="Header.TLabel").pack(side="left")

        self.help_btn = HoverButton(
            hdr_row,
            text="?",
            command=self._show_help,
            bg=HELP_BTN,
            hover=HELP_BTN_HOVER,
            press="#9d7cd8",
            fg="#1a1b26",
            canvas_bg=BG_DARK,
            width=36,
            height=36,
            radius=18,
            font=FONT_BOLD_XL,
        )
        self.help_btn.pack(side="right")

        ttk.Label(outer, text="Convert Draw Steel character files for Foundry VTT import", style="Sub.TLabel").pack(
            anchor="w", pady=(2, 16)
        )

        # ---- File selection card ----
        ttk.Label(outer, text="FILES", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        file_card = ttk.Frame(outer, style="Card.TFrame", padding=16)
        file_card.pack(fill="x", pady=(0, 16))
        file_card.columnconfigure(1, weight=1)

        # Input row
        ttk.Label(file_card, text="Input file", style="Card.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.input_var = tk.StringVar()
        inp_entry = ttk.Entry(file_card, textvariable=self.input_var, font=MONO)
        inp_entry.grid(row=0, column=1, sticky="ew", ipady=4)
        inp_browse = HoverButton(
            file_card, text="Browse\u2026", command=self._browse_input, canvas_bg=BG_CARD,
            width=90, height=32, radius=6, font=FONT_SM,
        )
        inp_browse.grid(row=0, column=2, padx=(8, 0))

        ext_lbl = ttk.Label(file_card, text=".ds-hero", style="Card.TLabel", foreground=FG_DIM,
                            font=MONO_SM)
        ext_lbl.grid(row=1, column=1, sticky="w", pady=(2, 8))

        # Output row
        ttk.Label(file_card, text="Output file", style="Card.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 12))
        self.output_var = tk.StringVar()
        out_entry = ttk.Entry(file_card, textvariable=self.output_var, font=MONO)
        out_entry.grid(row=2, column=1, sticky="ew", ipady=4)
        out_browse = HoverButton(
            file_card, text="Browse\u2026", command=self._browse_output, canvas_bg=BG_CARD,
            width=90, height=32, radius=6, font=FONT_SM,
        )
        out_browse.grid(row=2, column=2, padx=(8, 0))

        ext_lbl2 = ttk.Label(file_card, text=".json", style="Card.TLabel", foreground=FG_DIM,
                             font=MONO_SM)
        ext_lbl2.grid(row=3, column=1, sticky="w", pady=(2, 0))

        # ---- Options card ----
        ttk.Label(outer, text="OPTIONS", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        opt_card = ttk.Frame(outer, style="Card.TFrame", padding=16)
        opt_card.pack(fill="x", pady=(0, 16))
        opt_card.columnconfigure(1, weight=1)

        self.verbose_var = tk.BooleanVar()
        self.strict_var = tk.BooleanVar()
        self.update_var = tk.BooleanVar()
        self.compendium_var = tk.StringVar(value="draw_steel_repo/src/packs")

        row = 0
        ttk.Checkbutton(opt_card, text="Verbose logging", variable=self.verbose_var).grid(
            row=row, column=0, sticky="w", pady=2
        )
        ttk.Checkbutton(opt_card, text="Strict mode (fail on missing items)", variable=self.strict_var).grid(
            row=row, column=1, sticky="w", pady=2, padx=(16, 0)
        )
        row += 1
        ttk.Checkbutton(opt_card, text="Force-update compendium from GitHub", variable=self.update_var).grid(
            row=row, column=0, columnspan=2, sticky="w", pady=2
        )

        row += 1
        sep = ttk.Frame(opt_card, height=1, style="Card.TFrame")
        sep.grid(row=row, column=0, columnspan=3, sticky="ew", pady=8)

        row += 1
        ttk.Label(opt_card, text="Compendium path", style="Card.TLabel").grid(
            row=row, column=0, sticky="w", padx=(0, 12)
        )
        comp_entry = ttk.Entry(opt_card, textvariable=self.compendium_var, font=MONO)
        comp_entry.grid(row=row, column=1, sticky="ew", ipady=4)
        comp_browse = HoverButton(
            opt_card, text="Browse\u2026", command=self._browse_compendium, canvas_bg=BG_CARD,
            width=90, height=32, radius=6, font=FONT_SM,
        )
        comp_browse.grid(row=row, column=2, padx=(8, 0))

        # ---- Convert button ----
        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(0, 12))

        self.convert_btn = HoverButton(
            btn_row,
            text="\u2728  Convert",
            canvas_bg=BG_DARK,
            command=self._run_conversion,
            width=180,
            height=42,
            radius=10,
            font=FONT_LG,
        )
        self.convert_btn.pack(side="left")

        self.status_lbl = ttk.Label(btn_row, text="", style="Sub.TLabel")
        self.status_lbl.pack(side="left", padx=(16, 0))

        # ---- Log output ----
        ttk.Label(outer, text="LOG", style="Section.TLabel").pack(anchor="w", pady=(0, 4))

        log_frame = tk.Frame(outer, bg=BORDER, bd=0)
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(
            log_frame,
            bg=BG_INPUT,
            fg=FG_PRIMARY,
            insertbackground=FG_PRIMARY,
            font=MONO_SM,
            wrap="word",
            state="disabled",
            borderwidth=0,
            padx=10,
            pady=8,
            relief="flat",
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=(0, 1), pady=1)
        self.log_text.pack(side="left", fill="both", expand=True, padx=1, pady=1)

    # ------------------------------------------------------------------
    # Logger
    # ------------------------------------------------------------------
    def _attach_logger(self):
        root_logger = logging.getLogger()

        # Remove any existing TextHandler instances to avoid duplicate log messages
        root_logger.handlers = [
            h for h in root_logger.handlers if not isinstance(h, TextHandler)
        ]

        handler = TextHandler(self.log_text)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)

    # ------------------------------------------------------------------
    # File dialogs
    # ------------------------------------------------------------------
    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select Forgesteel character file",
            filetypes=[("Forgesteel Hero", "*.ds-hero")],
        )
        if path:
            self.input_var.set(path)
            # Auto-fill output if empty
            if not self.output_var.get():
                out = str(Path(path).with_suffix(".json"))
                self.output_var.set(out)

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save Foundry VTT JSON as",
            defaultextension=".json",
            filetypes=[("JSON file", "*.json")],
        )
        if path:
            self.output_var.set(path)

    def _browse_compendium(self):
        path = filedialog.askdirectory(title="Select compendium packs directory")
        if path:
            self.compendium_var.set(path)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_paths(self) -> bool:
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()

        if not input_path:
            messagebox.showerror("Missing input", "Please select an input .ds-hero file.")
            return False

        if not input_path.lower().endswith(".ds-hero"):
            messagebox.showerror(
                "Invalid input file",
                "The input file must have a .ds-hero extension.",
            )
            return False

        if not Path(input_path).exists():
            messagebox.showerror("File not found", f"Input file does not exist:\n{input_path}")
            return False

        if not output_path:
            messagebox.showerror("Missing output", "Please specify an output .json file path.")
            return False

        if not output_path.lower().endswith(".json"):
            messagebox.showerror(
                "Invalid output file",
                "The output file must have a .json extension.",
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Conversion (runs in background thread)
    # ------------------------------------------------------------------
    def _run_conversion(self):
        if not self._validate_paths():
            return

        self.convert_btn.set_disabled(True)
        self.convert_btn.set_text("Converting\u2026")
        self.status_lbl.configure(text="Working\u2026", foreground=FG_ACCENT)

        # Clear log
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

        if self.verbose_var.get():
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            logging.getLogger().setLevel(logging.INFO)

        thread = threading.Thread(target=self._conversion_worker, daemon=True)
        thread.start()

    def _conversion_worker(self):
        logger = logging.getLogger("forgesteel_gui")
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        compendium = self.compendium_var.get().strip()
        strict = self.strict_var.get()
        verbose = self.verbose_var.get()
        force_update = self.update_var.get()

        try:
            logger.info(f"Loading character from {Path(input_path).name}...")
            forgesteel_char = load_forgesteel_character(input_path)
            char_name = forgesteel_char.get("name", "Unknown")
            logger.info(f"Character loaded: {char_name}")

            logger.info("Loading compendium items...")
            target_types = ["ability", "ancestry", "career", "culture", "class", "perk", "project"]
            compendium_items = load_compendium_items(
                compendium, verbose=verbose, force_update=force_update, target_types=target_types
            )
            logger.info(f"Loaded {len(compendium_items)} compendium items")

            logger.info("Converting character...")
            foundry_char = convert_character(forgesteel_char, compendium_items, strict=strict, verbose=verbose)

            if not foundry_char:
                logger.error("Conversion failed - no data returned")
                self._finish(False)
                return

            item_count = len(foundry_char.get("items", []))
            logger.info(f"Writing {item_count} items to {Path(output_path).name}...")
            write_foundry_character(foundry_char, output_path)

            logger.info(f"Successfully converted '{char_name}' with {item_count} items")
            self._finish(True, char_name, item_count)

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in input file: {e}")
            self._finish(False)
        except Exception as e:
            logger.error(f"Error: {e}")
            if verbose:
                import traceback
                logger.debug(traceback.format_exc())
            self._finish(False)

    def _finish(self, success: bool, name: str = "", items: int = 0):
        def _update():
            self.convert_btn.set_disabled(False)
            self.convert_btn.set_text("\u2728  Convert")
            if success:
                self.status_lbl.configure(
                    text=f"Done \u2014 {name} ({items} items)",
                    foreground=FG_SUCCESS,
                )
            else:
                self.status_lbl.configure(text="Conversion failed", foreground=FG_ERROR)

        self.after(0, _update)

    # ------------------------------------------------------------------
    # Help dialog
    # ------------------------------------------------------------------
    def _show_help(self):
        win = tk.Toplevel(self)
        win.title("Help & Tips")
        win.configure(bg=BG_DARK)
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        pad = ttk.Frame(win, padding=24)
        pad.pack(fill="both", expand=True)

        ttk.Label(pad, text="Help & Tips", style="Header.TLabel").pack(anchor="w")
        ttk.Label(pad, text="Everything you need to know", style="Sub.TLabel").pack(anchor="w", pady=(2, 16))

        txt = tk.Text(
            pad,
            bg=BG_MID,
            fg=FG_PRIMARY,
            font=FONT,
            wrap="word",
            borderwidth=0,
            padx=14,
            pady=12,
            relief="flat",
            cursor="arrow",
            spacing1=2,
            spacing3=2,
        )
        txt.pack(fill="x")

        txt.tag_configure("heading", foreground=FG_ACCENT, font=FONT_BOLD_LG, spacing1=10)
        txt.tag_configure("body", foreground=FG_PRIMARY, font=FONT)
        txt.tag_configure("dim", foreground=FG_DIM, font=FONT_SM)
        txt.tag_configure("warn", foreground=FG_WARN, font=FONT)

        sections = [
            ("heading", "Quick Start\n"),
            ("body", "1.  Click "),
            ("warn", "Browse\u2026"),
            ("body", " next to Input file and select your .ds-hero file.\n"),
            ("body", "2.  The output path auto-fills. Change it if needed.\n"),
            ("body", "3.  Press "),
            ("warn", "Convert"),
            ("body", " and wait for the log to report success.\n"),
            ("body", "4.  Import the resulting .json in Foundry VTT.\n\n"),

            ("heading", "Input File (.ds-hero)\n"),
            ("body", "Export your character from the Forgesteel app. The file "),
            ("body", "must have the "),
            ("warn", ".ds-hero"),
            ("body", " extension \u2014 no other formats are accepted.\n\n"),

            ("heading", "Output File (.json)\n"),
            ("body", "The converted file is saved as standard JSON compatible "),
            ("body", "with Foundry VTT\u2019s Draw Steel system module. Only the "),
            ("warn", ".json"),
            ("body", " extension is allowed.\n\n"),

            ("heading", "Options\n"),
            ("body", "\u2022 Verbose logging \u2013 shows detailed debug output.\n"),
            ("body", "\u2022 Strict mode \u2013 the conversion will fail if any "),
            ("body", "compendium item is missing instead of creating a "),
            ("body", "placeholder.\n"),
            ("body", "\u2022 Force-update compendium \u2013 re-download the latest "),
            ("body", "Draw Steel data from GitHub even if a cache exists.\n"),
            ("body", "\u2022 Compendium path \u2013 point to a local clone of the "),
            ("body", "draw-steel repo (src/packs folder) for offline use.\n\n"),

            ("heading", "Compendium Sources\n"),
            ("body", "The converter searches for data in this order:\n"),
            ("body", "  1. Local directory (compendium path)\n"),
            ("body", "  2. Cached files (~/.cache/forgesteel-converter/)\n"),
            ("body", "  3. GitHub (MetaMorphic-Digital/draw-steel)\n\n"),

            ("heading", "GitHub Rate Limits\n"),
            ("body", "Unauthenticated requests are limited to 60/hour. Set a "),
            ("warn", "GITHUB_TOKEN"),
            ("body", " environment variable for 5 000/hour.\n\n"),

            ("heading", "Importing into Foundry VTT\n"),
            ("body", "In Foundry, open the Actors tab \u2192 right-click the "),
            ("body", "folder \u2192 Import Data \u2192 select the .json file.\n\n"),

            ("heading", "Troubleshooting\n"),
            ("body", "\u2022 If conversion fails, enable "),
            ("warn", "Verbose logging"),
            ("body", " and check the log output for details.\n"),
            ("body", "\u2022 Encoding errors usually mean the .ds-hero file was "),
            ("body", "saved with non-UTF-8 encoding.\n"),
            ("body", "\u2022 Missing items may be resolved by using "),
            ("warn", "Force-update compendium"),
            ("body", " to fetch the latest data.\n"),
        ]

        for tag, content in sections:
            txt.insert(tk.END, content, tag)

        txt.configure(state="disabled")

        close_frame = ttk.Frame(pad)
        close_frame.pack(fill="x", pady=(12, 0))
        close_btn = HoverButton(
            close_frame, text="Got it", command=win.destroy, canvas_bg=BG_DARK,
            width=100, height=34, radius=8, font=FONT_BOLD,
        )
        close_btn.pack(side="right")

        # Let geometry calculate, then size the window to fit all content
        # capped to 90% of screen height so it stays usable on small displays.
        win.update_idletasks()
        content_h = txt.count("1.0", "end", "ypixels")[0] + int(txt.cget("pady")) * 2
        txt.configure(height=1)  # reset line-based height so pixel height governs
        txt.configure(height=0)

        win.update_idletasks()
        # Total height = header/subtitle + text content + button + padding
        chrome_h = win.winfo_reqheight() - txt.winfo_reqheight()
        desired_h = chrome_h + content_h + 8
        max_h = int(win.winfo_screenheight() * 0.9)
        final_h = min(desired_h, max_h)

        win.geometry(f"560x{final_h}")


def main():
    app = ForgesteelGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
