from __future__ import annotations

import copy
import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .credentials import load_api_key, save_api_key
from .docx_reader import ExtractedNovel, extract_docx
from .i18n import tr
from .models import ProjectData, Scene, Subtitle
from .pipeline import process_novel, regenerate_field, regenerate_scene
from .providers import DEFAULTS, ChatProvider
from .settings import load_settings, load_ui_language, save_settings, save_ui_language
from .storage import ensure_project_folders, load_project, save_project
from .validation import validate_project


class BezierPanel(tk.Canvas):
    """Rounded panel sampled from cubic Bézier corner curves."""

    KAPPA = 0.5522847498

    def __init__(self, master, fill="#FFFFFF", radius=22, outline="#D9E8FA", outline_width=1, **kwargs):
        try: background = master.cget("background")
        except tk.TclError:
            style_name = master.cget("style") or master.winfo_class()
            background = ttk.Style(master).lookup(style_name, "background") or master.winfo_toplevel().cget("background")
        super().__init__(master, background=background, highlightthickness=0, borderwidth=0, **kwargs)
        self.fill = fill
        self.radius = radius
        self.outline = outline
        self.outline_width = outline_width
        self.content = tk.Frame(self, background=fill, borderwidth=0, highlightthickness=0)
        self._window = self.create_window((radius // 2, radius // 2), window=self.content, anchor="nw")
        self.bind("<Configure>", self._redraw)

    @staticmethod
    def _curve(p0, p1, p2, p3, steps=9):
        points = []
        for index in range(1, steps + 1):
            t = index / steps; u = 1 - t
            points.extend((u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0],
                           u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]))
        return points

    def _redraw(self, event):
        width, height = max(2, event.width), max(2, event.height)
        radius = min(self.radius, width / 2, height / 2); k = radius * self.KAPPA
        points = [radius, 0, width - radius, 0]
        points += self._curve((width-radius, 0), (width-radius+k, 0), (width, radius-k), (width, radius))
        points += [width, height-radius]
        points += self._curve((width, height-radius), (width, height-radius+k), (width-radius+k, height), (width-radius, height))
        points += [radius, height]
        points += self._curve((radius, height), (radius-k, height), (0, height-radius+k), (0, height-radius))
        points += [0, radius]
        points += self._curve((0, radius), (0, radius-k), (radius-k, 0), (radius, 0))
        self.delete("panel")
        self.create_polygon(points, fill=self.fill, outline=self.outline, width=self.outline_width, tags="panel")
        self.tag_lower("panel")
        inset = max(6, int(radius * 0.42))
        self.coords(self._window, inset, inset)
        self.itemconfigure(self._window, width=max(1, width-2*inset), height=max(1, height-2*inset))


class CurveButton(tk.Canvas):
    """Cubic-Bézier rounded button with consistent cross-platform rendering."""

    def __init__(self, master, text, command=None, variant="secondary", width=142, height=40, **kwargs):
        self.palette = {
            "primary": ("#2F7DF6", "#FFFFFF", "#1E68D2"),
            "secondary": ("#E9F3FF", "#245D99", "#D7E9FF"),
            "ghost": ("#FFFFFF", "#35658F", "#EEF6FF"),
            "danger": ("#FFF0F2", "#B84E5D", "#FFE2E6"),
            "nav": ("#245F9E", "#F4FAFF", "#3374B5"),
            "nav_active": ("#2F7DF6", "#FFFFFF", "#2F7DF6"),
        }
        self.variant, self.label, self.command, self.state = variant, text, command, kwargs.pop("state", "normal")
        try: background = master.cget("background")
        except tk.TclError:
            style_name = master.cget("style") or master.winfo_class()
            background = ttk.Style(master).lookup(style_name, "background") or master.winfo_toplevel().cget("background")
        super().__init__(master, width=width, height=height, background=background, highlightthickness=0, borderwidth=0, cursor="hand2", **kwargs)
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", lambda _event: self._draw(True))
        self.bind("<Leave>", lambda _event: self._draw(False))
        self.bind("<Button-1>", self._click)

    def _click(self, _event):
        if self.state != "disabled" and self.command: self.command()

    def _draw(self, hover=False):
        self.delete("all")
        width, height = max(2, self.winfo_width()), max(2, self.winfo_height())
        fill, foreground, hover_fill = self.palette.get(self.variant, self.palette["secondary"])
        if self.state == "disabled": fill, foreground = "#EAF0F7", "#9AAABD"
        elif hover: fill = hover_fill
        radius = min(18, height / 2); k = radius * BezierPanel.KAPPA
        points = [radius, 0, width-radius, 0]
        points += BezierPanel._curve((width-radius, 0), (width-radius+k, 0), (width, radius-k), (width, radius), 7)
        points += [width, height-radius]
        points += BezierPanel._curve((width, height-radius), (width, height-radius+k), (width-radius+k, height), (width-radius, height), 7)
        points += [radius, height]
        points += BezierPanel._curve((radius, height), (radius-k, height), (0, height-radius+k), (0, height-radius), 7)
        points += [0, radius]
        points += BezierPanel._curve((0, radius), (0, radius-k), (radius-k, 0), (radius, 0), 7)
        self.create_polygon(points, fill=fill, outline="")
        self.create_text(width/2, height/2, text=self.label, fill=foreground, font=("Helvetica Neue", 10, "bold" if self.variant in ("primary", "nav_active") else "normal"))

    def configure(self, cnf=None, **kwargs):
        if "state" in kwargs: self.state = kwargs.pop("state")
        if "style" in kwargs:
            style = kwargs.pop("style"); self.variant = "nav_active" if style == "ActiveNav.TButton" else "nav"
        if "text" in kwargs: self.label = kwargs.pop("text")
        if cnf or kwargs: super().configure(cnf or {}, **kwargs)
        self._draw()

    config = configure


class DramaStudioApp:
    def __init__(self):
        self.root = tk.Tk()
        self.language = load_ui_language()
        self.root.title(self.t("app_title"))
        self.root.geometry("1280x800")
        self.root.minsize(1050, 680)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Command-s>", lambda _event: self.save())
        self.root.bind("<Control-s>", lambda _event: self.save())
        self.root.bind("<Command-i>", lambda _event: self.import_docx())
        self.root.bind("<Control-i>", lambda _event: self.import_docx())
        self.config = load_settings()
        self.config.api_key = load_api_key(self.config.provider)
        self.project_root: Path | None = None
        self.novel: ExtractedNovel | None = None
        self.project = ProjectData()
        self.selected_scene: int | None = None
        self.busy = False
        self.cancel_event = threading.Event()
        self._style()
        self._build()

    def run(self):
        self.root.mainloop()

    def t(self, key, **values):
        return tr(self.language, key, **values)

    def _style(self):
        style = ttk.Style(self.root)
        # Custom cubic-Bézier controls provide consistent rounding; clam prevents
        # macOS Aqua from injecting gray backing rectangles behind styled widgets.
        if "clam" in style.theme_names(): style.theme_use("clam")
        self.colors = {
            "bg": "#FFFFFF", "surface": "#FFFFFF", "sidebar": "#245F9E", "text": "#173E66",
            "muted": "#68809A", "border": "#D9E8FA", "accent": "#2F7DF6", "accent_dark": "#1E68D2",
            "soft": "#E9F3FF", "success": "#258467", "warning": "#B77A2E", "danger": "#BD5360",
        }
        self.root.configure(background=self.colors["bg"])
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("Surface.TFrame", background=self.colors["surface"])
        style.configure("Title.TLabel", font=("Helvetica Neue", 22, "bold"), foreground=self.colors["text"], background=self.colors["surface"])
        style.configure("PageTitle.TLabel", font=("Helvetica Neue", 18, "bold"), foreground=self.colors["text"], background=self.colors["bg"])
        style.configure("Section.TLabel", font=("Helvetica Neue", 12, "bold"), foreground=self.colors["text"], background=self.colors["surface"])
        style.configure("Body.TLabel", font=("Helvetica Neue", 11), foreground=self.colors["text"], background=self.colors["surface"])
        style.configure("Sub.TLabel", font=("Helvetica Neue", 10), foreground=self.colors["muted"], background=self.colors["surface"])
        style.configure("Status.TLabel", font=("Helvetica Neue", 10), foreground=self.colors["muted"], background=self.colors["bg"])
        style.configure("TButton", font=("Helvetica Neue", 10), padding=(14, 9), relief="flat", borderwidth=0)
        style.configure("Accent.TButton", font=("Helvetica Neue", 10, "bold"), foreground="#FFFFFF", background=self.colors["accent"], borderwidth=0)
        style.map("Accent.TButton", background=[("active", self.colors["accent_dark"]), ("disabled", "#B7B1EE")])
        style.configure("Danger.TButton", foreground=self.colors["danger"], background="#FFF1F1")
        style.configure("Nav.TButton", font=("Helvetica Neue", 11), foreground="#C7C5D0", background=self.colors["sidebar"], anchor="w", padding=(20, 13), borderwidth=0, relief="flat")
        style.map("Nav.TButton", foreground=[("active", "#FFFFFF")], background=[("active", "#2864A8")])
        style.configure("ActiveNav.TButton", font=("Helvetica Neue", 11, "bold"), foreground="#FFFFFF", background="#3476C2", anchor="w", padding=(20, 13), borderwidth=0, relief="flat")
        style.configure("Card.TLabelframe", background=self.colors["surface"], borderwidth=0, relief="flat")
        style.configure("Card.TLabelframe.Label", font=("Helvetica Neue", 11, "bold"), foreground=self.colors["text"], background=self.colors["surface"])
        style.configure("Treeview", font=("Helvetica Neue", 10), rowheight=36, background=self.colors["surface"], fieldbackground=self.colors["surface"], foreground=self.colors["text"], borderwidth=0)
        style.configure("Treeview.Heading", font=("Helvetica Neue", 9, "bold"), foreground=self.colors["muted"], background="#FAF8FB", padding=(9, 10), relief="flat", borderwidth=0)
        style.map("Treeview", background=[("selected", self.colors["soft"])], foreground=[("selected", self.colors["text"])])
        style.configure("TEntry", padding=(10, 8), fieldbackground="#FBFDFF", bordercolor=self.colors["border"], lightcolor=self.colors["border"], darkcolor=self.colors["border"])
        style.configure("TCombobox", padding=(9, 7), fieldbackground="#FBFDFF", bordercolor=self.colors["border"])
        style.configure("TNotebook", background=self.colors["surface"], borderwidth=0)
        style.configure("TPanedwindow", background=self.colors["bg"], sashwidth=8)
        style.configure("TNotebook.Tab", font=("Helvetica Neue", 10, "bold"), padding=(18, 10), background="#EDF5FF", foreground=self.colors["muted"], borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", self.colors["surface"])], foreground=[("selected", self.colors["accent"])])

    def _build(self):
        top = ttk.Frame(self.root, style="Surface.TFrame", padding=(24, 16))
        top.pack(fill="x")
        brand = ttk.Frame(top, style="Surface.TFrame"); brand.pack(side="left")
        ttk.Label(brand, text=self.t("app_title"), style="Title.TLabel").pack(anchor="w")
        ttk.Label(brand, text=self.t("tagline"), style="Sub.TLabel").pack(anchor="w")
        self.provider_label = ttk.Label(top, text=self.t("provider", provider=self.config.provider), style="Sub.TLabel")
        self.provider_label.pack(side="right", padx=(12, 0))
        CurveButton(top, text=self.t("api_settings"), command=self.open_settings, variant="secondary", width=150).pack(side="right")

        setup_panel = BezierPanel(self.root, fill=self.colors["surface"], radius=24, height=138)
        setup_panel.pack(fill="x", padx=20, pady=(16, 12))
        setup = setup_panel.content
        self.folder_var = tk.StringVar(value=str(self.project_root) if self.project_root else self.t("choose_parent"))
        self.novel_var = tk.StringVar(value=self._novel_label())
        project_card = ttk.Frame(setup, style="Surface.TFrame"); project_card.grid(row=0, column=0, sticky="ew", padx=(0, 20))
        ttk.Label(project_card, text=self.t("project_folder"), style="Section.TLabel").pack(anchor="w")
        ttk.Label(project_card, textvariable=self.folder_var, style="Sub.TLabel", wraplength=360).pack(anchor="w", pady=(3, 8))
        CurveButton(project_card, text=self.t("choose_folder"), command=self.choose_folder, variant="secondary", width=132).pack(anchor="w")
        novel_card = ttk.Frame(setup, style="Surface.TFrame"); novel_card.grid(row=0, column=1, sticky="ew", padx=(0, 20))
        ttk.Label(novel_card, text=self.t("word_novel"), style="Section.TLabel").pack(anchor="w")
        ttk.Label(novel_card, textvariable=self.novel_var, style="Sub.TLabel", wraplength=360).pack(anchor="w", pady=(3, 8))
        CurveButton(novel_card, text=self.t("import_docx"), command=self.import_docx, variant="secondary", width=132).pack(anchor="w")
        setup.columnconfigure(0, weight=1); setup.columnconfigure(1, weight=1)
        self.process_btn = CurveButton(setup, text=self.t("create_plan"), command=self.start_processing, variant="primary", width=190, height=54)
        self.process_btn.grid(row=0, column=2, padx=(10, 0), sticky="nsew")
        self.cancel_btn = CurveButton(setup, text=self.t("cancel"), command=self.cancel_processing, state="disabled", variant="secondary", width=96, height=54)
        self.cancel_btn.grid(row=0, column=3, padx=(8, 0), sticky="nsew")

        workspace = tk.Frame(self.root, bg=self.colors["bg"], highlightthickness=0); workspace.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        sidebar_panel = BezierPanel(workspace, fill=self.colors["sidebar"], radius=24, width=200)
        sidebar_panel.pack(side="left", fill="y", padx=(0, 4)); sidebar_panel.pack_propagate(False)
        sidebar = sidebar_panel.content
        tk.Label(sidebar, text=self.t("workspace"), bg=self.colors["sidebar"], fg="#C4DCF3", font=("Helvetica Neue", 9, "bold"), anchor="w", padx=18, pady=16).pack(fill="x")
        self.nav_buttons = {}
        for key, label in (("preview", self.t("novel_preview")), ("summary", self.t("story_cast")), ("scenes", self.t("scene_board"))):
            button = CurveButton(sidebar, text=label, variant="nav", height=44, command=lambda page=key: self._show_page(page))
            button.pack(fill="x", pady=1); self.nav_buttons[key] = button
        tk.Label(sidebar, text=self.t("output"), bg=self.colors["sidebar"], fg="#C4DCF3", font=("Helvetica Neue", 9, "bold"), anchor="w", padx=18, pady=8).pack(fill="x", pady=(20, 0))
        tk.Label(sidebar, text=self.t("output_folders"), bg=self.colors["sidebar"], fg="#E8F3FF", justify="left", anchor="w", padx=18, font=("Helvetica Neue", 10), pady=4).pack(fill="x")
        language_box = tk.Frame(sidebar, bg=self.colors["sidebar"]); language_box.pack(side="bottom", fill="x", padx=10, pady=12)
        tk.Label(language_box, text=self.t("language"), bg=self.colors["sidebar"], fg="#C4DCF3", font=("Helvetica Neue", 9, "bold"), anchor="w").pack(anchor="w", padx=8, pady=(0, 5))
        language_buttons = tk.Frame(language_box, bg=self.colors["sidebar"]); language_buttons.pack(fill="x")
        CurveButton(language_buttons, text="EN", command=lambda: self.switch_language("en"), variant="nav_active" if self.language == "en" else "nav", width=72, height=34).pack(side="left", padx=(0, 4))
        CurveButton(language_buttons, text="中文", command=lambda: self.switch_language("zh"), variant="nav_active" if self.language == "zh" else "nav", width=72, height=34).pack(side="left")

        self.page_container = tk.Frame(workspace, bg=self.colors["bg"], highlightthickness=0); self.page_container.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.preview_tab = tk.Frame(self.page_container, bg=self.colors["bg"], padx=18, pady=14)
        self.summary_tab = tk.Frame(self.page_container, bg=self.colors["bg"], padx=18, pady=14)
        self.scenes_tab = tk.Frame(self.page_container, bg=self.colors["bg"], padx=14, pady=12)
        self.pages = {"preview": self.preview_tab, "summary": self.summary_tab, "scenes": self.scenes_tab}
        for page in self.pages.values(): page.grid(row=0, column=0, sticky="nsew")
        self.page_container.rowconfigure(0, weight=1); self.page_container.columnconfigure(0, weight=1)
        self._build_preview()
        self._build_summary()
        self._build_scenes()
        self._show_page("preview")

        bottom = ttk.Frame(self.root, padding=(22, 2, 22, 14))
        bottom.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, mode="indeterminate", length=160)
        self.progress.pack(side="left")
        self.status_var = tk.StringVar(value=self.t("ready"))
        ttk.Label(bottom, textvariable=self.status_var, style="Status.TLabel").pack(side="left", padx=10)
        CurveButton(bottom, text=self.t("save_changes"), command=self.save, variant="secondary", width=130).pack(side="right")

    def _show_page(self, key):
        self.current_page = key
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items(): button.configure(style="ActiveNav.TButton" if name == key else "Nav.TButton")

    def _novel_label(self):
        if not self.novel: return self.t("no_novel")
        return f"{self.novel.title}.docx — {len(self.novel.chapters)} sections, {len(self.novel.text):,} characters"

    def switch_language(self, language):
        if language == self.language or self.busy: return
        page = getattr(self, "current_page", "preview")
        if self.project_root:
            self.apply_scene(silent=True)
            self._save_project(silent=True)
        self.language = language; save_ui_language(language); self.root.title(self.t("app_title"))
        for child in self.root.winfo_children(): child.destroy()
        self._style(); self._build()
        if self.novel:
            preview = f"{self.novel.title}\n{len(self.novel.chapters)} sections · {len(self.novel.text):,} characters\n\n" + self.novel.text[:50000]
            self._set_text(self.preview_text, preview, readonly=True)
        if self.project.scenes or self.project.characters: self.refresh_all()
        self._show_page(page)

    def _build_preview(self):
        heading = tk.Frame(self.preview_tab, bg=self.colors["bg"], highlightthickness=0); heading.pack(fill="x", pady=(0, 12))
        ttk.Label(heading, text=self.t("preview_title"), style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(heading, text=self.t("preview_help"), style="Status.TLabel").pack(anchor="w", pady=(3, 0))
        card = BezierPanel(self.preview_tab, fill=self.colors["surface"], radius=22); card.pack(fill="both", expand=True)
        self.preview_text = tk.Text(card.content, wrap="word", padx=16, pady=14, undo=False, relief="flat", borderwidth=0, highlightthickness=0, background="#FFFFFF", foreground=self.colors["text"], insertbackground=self.colors["accent"], font=("Helvetica Neue", 11), spacing1=2, spacing3=8)
        scroll = ttk.Scrollbar(card.content, command=self.preview_text.yview); self.preview_text.configure(yscrollcommand=scroll.set)
        self.preview_text.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        self.preview_text.insert("1.0", self.t("preview_empty"))
        self.preview_text.configure(state="disabled")

    def _build_summary(self):
        ttk.Label(self.summary_tab, text=self.t("story_title"), style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(self.summary_tab, text=self.t("story_help"), style="Status.TLabel").pack(anchor="w", pady=(3, 12))
        pane = ttk.Panedwindow(self.summary_tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.LabelFrame(pane, text=self.t("project_direction"), style="Card.TLabelframe", padding=18)
        right = ttk.LabelFrame(pane, text=self.t("recurring_characters"), style="Card.TLabelframe", padding=18)
        pane.add(left, weight=3); pane.add(right, weight=2)
        summary_specs = [
            ("title", self.t("title")), ("main_theme", self.t("main_theme")), ("secondary_themes", self.t("secondary_themes")),
            ("genre", self.t("genre")), ("tone", self.t("tone")), ("visual_style", self.t("visual_style")),
            ("time_period", self.t("time_period")), ("adaptation_direction", self.t("adaptation_direction")),
        ]
        self.summary_fields = {}
        for row, (key, label) in enumerate(summary_specs):
            ttk.Label(left, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 8), pady=5)
            height = 2 if key not in ("title", "genre", "tone", "time_period") else 1
            panel, entry = self._curved_text(left, height, width=45)
            panel.grid(row=row, column=1, sticky="ew", pady=5); self.summary_fields[key] = entry
            entry.bind("<FocusOut>", lambda _event: self._save_project(silent=True))
        left.columnconfigure(1, weight=1)
        self.character_list = tk.Listbox(right, exportselection=False, height=5, relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=self.colors["border"], selectbackground=self.colors["soft"], selectforeground=self.colors["text"], font=("Helvetica Neue", 10))
        self.character_list.pack(fill="x")
        self.character_list.bind("<<ListboxSelect>>", self.show_character)
        CurveButton(right, text=self.t("save_character"), command=self.apply_character, variant="primary", height=42).pack(side="bottom", fill="x", pady=(8, 0))
        character_holder = ttk.Frame(right, style="Surface.TFrame"); character_holder.pack(fill="both", expand=True, pady=(8, 0))
        character_canvas = tk.Canvas(character_holder, highlightthickness=0, height=380, background=self.colors["surface"])
        character_scroll = ttk.Scrollbar(character_holder, orient="vertical", command=character_canvas.yview)
        character_form = ttk.Frame(character_canvas)
        character_form.bind("<Configure>", lambda _event: character_canvas.configure(scrollregion=character_canvas.bbox("all")))
        character_canvas.create_window((0, 0), window=character_form, anchor="nw")
        character_canvas.configure(yscrollcommand=character_scroll.set)
        character_canvas.pack(side="left", fill="both", expand=True); character_scroll.pack(side="right", fill="y")
        char_specs = [
            ("character_id", self.t("character_id")), ("name", self.t("name")), ("importance", self.t("importance")), ("role", self.t("role")),
            ("age", self.t("age")), ("gender", self.t("gender")), ("face", self.t("face")), ("eyes", self.t("eyes")), ("hair", self.t("hair")),
            ("build", self.t("build")), ("distinctive_features", self.t("distinctive_features")), ("default_costume", self.t("default_costume")),
            ("personality", self.t("personality")), ("posture", self.t("posture")), ("walking", self.t("walking")),
            ("gestures", self.t("gestures")), ("eye_behavior", self.t("eye_behavior")), ("emotional_motion", self.t("emotional_motion")),
            ("speech_behavior", self.t("speech_behavior")), ("reference_prompt", self.t("reference_prompt")),
        ]
        self.character_fields = {}
        for row, (key, label) in enumerate(char_specs):
            ttk.Label(character_form, text=label).grid(row=row, column=0, sticky="nw", padx=(0, 6), pady=3)
            entry = ttk.Entry(character_form, width=36)
            entry.grid(row=row, column=1, sticky="ew", pady=3); self.character_fields[key] = entry
        character_form.columnconfigure(1, weight=1)

    def _build_scenes(self):
        top = tk.Frame(self.scenes_tab, bg=self.colors["bg"], highlightthickness=0); top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text=self.t("scene_board_title"), style="PageTitle.TLabel").pack(side="left")
        self.scene_count_var = tk.StringVar(value="0 scenes")
        ttk.Label(top, textvariable=self.scene_count_var, style="Status.TLabel").pack(side="left", padx=12, pady=(5, 0))
        CurveButton(top, text=self.t("add_scene"), command=self.add_scene, variant="secondary", width=120).pack(side="right")
        pane = ttk.Panedwindow(self.scenes_tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left_panel = BezierPanel(pane, fill=self.colors["surface"], radius=20)
        right_panel = BezierPanel(pane, fill=self.colors["surface"], radius=20)
        left, right = left_panel.content, right_panel.content
        pane.add(left_panel, weight=2); pane.add(right_panel, weight=5)
        self.scene_tree = ttk.Treeview(left, columns=("id", "loc", "status"), show="headings", selectmode="browse")
        for column, label, width in (("id", "SCENE", 100), ("loc", "LOCATION", 170), ("status", "STATUS", 90)):
            self.scene_tree.heading(column, text=label); self.scene_tree.column(column, width=width, anchor="w")
        self.scene_tree.pack(fill="both", expand=True)
        self.scene_tree.bind("<<TreeviewSelect>>", self.select_scene)
        buttons = ttk.Frame(left); buttons.pack(fill="x", pady=(8, 0))
        for key, command in (("duplicate", self.duplicate_scene), ("delete", self.delete_scene), ("move_up", lambda: self.move_scene(-1)), ("move_down", lambda: self.move_scene(1))):
            CurveButton(buttons, text=self.t(key), command=command, variant="danger" if key == "delete" else "ghost", width=82, height=34).pack(side="left", padx=(0, 4))
        inspector_head = ttk.Frame(right, style="Surface.TFrame"); inspector_head.pack(fill="x", pady=(0, 8))
        ttk.Label(inspector_head, text=self.t("scene_inspector"), style="Section.TLabel").pack(side="left")
        self.status_combo = ttk.Combobox(inspector_head, values=("draft", "reviewed", "approved"), state="readonly", width=11)
        self.status_combo.pack(side="right")
        tabs = ttk.Notebook(right); tabs.pack(fill="both", expand=True)
        story_tab = ttk.Frame(tabs, style="Surface.TFrame"); craft_tab = ttk.Frame(tabs, style="Surface.TFrame"); generation_tab = ttk.Frame(tabs, style="Surface.TFrame")
        tabs.add(story_tab, text=self.t("story_tab")); tabs.add(craft_tab, text=self.t("craft_tab")); tabs.add(generation_tab, text=self.t("generation_tab"))
        story_form = self._scrollable_form(story_tab); craft_form = self._scrollable_form(craft_tab); generation_form = self._scrollable_form(generation_tab)
        self.fields: dict[str, tk.Widget] = {}
        groups = [
            (story_form, [("prompt_id", self.t("prompt_id"), 1), ("episode", self.t("episode"), 1), ("scene", self.t("scene"), 1), ("plot", self.t("what_happens"), 4), ("location", self.t("location"), 1), ("time_of_day", self.t("time_day"), 1), ("characters", self.t("characters"), 1), ("character_state", self.t("appearance_state"), 3), ("action", self.t("visible_action"), 4), ("duration_seconds", self.t("duration"), 1)]),
            (craft_form, [("subtitles", self.t("subtitles"), 7), ("shot", self.t("camera_shot"), 4), ("continuity", self.t("continuity"), 5)]),
            (generation_form, [("photo_prompt", self.t("photo_prompt"), 7), ("video_prompt", self.t("video_prompt"), 9)]),
        ]
        for form, specs in groups:
            row = 0
            for key, label, height in specs:
                ttk.Label(form, text=label, style="Section.TLabel").grid(row=row, column=0, sticky="nw", pady=(8, 4))
                row += 1
                if height == 1:
                    widget: tk.Widget = ttk.Entry(form, width=62)
                    widget.grid(row=row, column=0, sticky="ew", pady=(0, 3))
                else:
                    panel, widget = self._curved_text(form, height, width=62)
                    panel.grid(row=row, column=0, sticky="ew", pady=(0, 3))
                self.fields[key] = widget; row += 1
                widget.bind("<FocusOut>", lambda _event: self.apply_scene(silent=True))
                if key == "photo_prompt":
                    widget.bind("<KeyRelease>", self.update_photo_count)
                    self.photo_count_var = tk.StringVar(value="0 characters")
                    ttk.Label(form, textvariable=self.photo_count_var, style="Sub.TLabel").grid(row=row, column=0, sticky="e")
                    row += 1
            form.columnconfigure(0, weight=1)
        actions = ttk.Frame(right, style="Surface.TFrame"); actions.pack(fill="x", pady=(10, 0))
        self.regenerate_field_var = tk.StringVar(value="photo_prompt")
        ttk.Combobox(actions, textvariable=self.regenerate_field_var, values=("plot", "action", "shot", "continuity", "photo_prompt", "video_prompt"), state="readonly", width=14).pack(side="left")
        CurveButton(actions, text=self.t("regenerate_field"), command=self.start_field_regeneration, variant="secondary", width=125).pack(side="left", padx=5)
        CurveButton(actions, text=self.t("rewrite_prompts"), command=lambda: self.start_regeneration(True), variant="secondary", width=120).pack(side="left", padx=5)
        CurveButton(actions, text=self.t("rewrite_scene"), command=lambda: self.start_regeneration(False), variant="secondary", width=110).pack(side="left", padx=5)
        CurveButton(actions, text=self.t("save_scene"), command=self.apply_scene, variant="primary", width=105).pack(side="right")

    def _scrollable_form(self, parent):
        canvas = tk.Canvas(parent, highlightthickness=0, background=self.colors["surface"])
        scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        form = ttk.Frame(canvas, style="Surface.TFrame", padding=(14, 8, 14, 14))
        window = canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        return form

    def _curved_text(self, parent, height, width=62):
        panel = BezierPanel(parent, fill="#FBFDFF", radius=14, height=max(42, height * 25 + 12))
        text = tk.Text(panel.content, height=height, width=width, wrap="word", undo=True, relief="flat", borderwidth=0,
                       highlightthickness=0, background="#FBFDFF", foreground=self.colors["text"],
                       insertbackground=self.colors["accent"], font=("Helvetica Neue", 10), padx=5, pady=4)
        text.pack(fill="both", expand=True)
        return panel, text

    def choose_folder(self):
        folder = filedialog.askdirectory(title=self.t("folder_dialog"))
        if not folder: return
        self.project_root = Path(folder)
        ensure_project_folders(self.project_root)
        self.folder_var.set(str(self.project_root))
        plan = self.project_root / "Project Plan" / "Scene Plan.json"
        if plan.exists() and messagebox.askyesno(self.t("existing_project"), self.t("open_existing")):
            try:
                self.project = load_project(self.project_root); self.refresh_all(); self._show_page("scenes"); self.status_var.set(self.t("project_opened"))
            except Exception as exc: messagebox.showerror(self.t("open_project_failed"), str(exc))

    def import_docx(self):
        path = filedialog.askopenfilename(title=self.t("novel_dialog"), filetypes=[(self.t("word_document"), "*.docx")])
        if not path: return
        try: self.novel = extract_docx(path)
        except Exception as exc: messagebox.showerror(self.t("import_failed"), str(exc)); return
        self.novel_var.set(self._novel_label())
        preview = f"TITLE: {self.novel.title}\nCHAPTERS: {len(self.novel.chapters)}\nCHARACTERS: {len(self.novel.text):,}\n\n" + self.novel.text[:50000]
        self._set_text(self.preview_text, preview, readonly=True)
        self._show_page("preview")

    def start_processing(self):
        if self.busy: return
        if not self.project_root: messagebox.showinfo(self.t("choose_project"), self.t("choose_project_first")); return
        if not self.novel: messagebox.showinfo(self.t("import_novel"), self.t("import_novel_first")); return
        if self.config.provider != "Demo" and not self.config.api_key: messagebox.showinfo(self.t("api_required"), self.t("api_required_body")); return
        if self.config.provider != "Demo" and not messagebox.askyesno(self.t("paid_title"), self.t("paid_body", count=len(self.novel.text), provider=self.config.provider)):
            return
        self.busy = True; self.cancel_event.clear(); self.progress.start(12); self.process_btn.configure(state="disabled"); self.cancel_btn.configure(state="normal")
        threading.Thread(target=self._process_worker, daemon=True).start()

    def _process_worker(self):
        try:
            project = process_novel(self.novel, ChatProvider(self.config), lambda m: self.root.after(0, self.status_var.set, m), self.cancel_event.is_set)
            save_project(self.project_root, project)
            self.root.after(0, self._processing_done, project, None)
        except Exception as exc:
            self.root.after(0, self._processing_done, None, exc)

    def _processing_done(self, project, error):
        self.busy = False; self.progress.stop(); self.process_btn.configure(state="normal"); self.cancel_btn.configure(state="disabled")
        if error: self.status_var.set(self.t("processing_failed")); messagebox.showerror(self.t("processing_failed"), str(error)); return
        self.project = project; self.refresh_all(); self._show_page("summary"); self.status_var.set(self.t("created_scenes", count=len(project.scenes)))

    def cancel_processing(self):
        if self.busy:
            self.cancel_event.set()
            self.status_var.set(self.t("cancelling"))

    def start_regeneration(self, prompts_only: bool):
        if self.busy or self.selected_scene is None:
            return
        if self.config.provider != "Demo" and not self.config.api_key:
            messagebox.showinfo(self.t("api_required"), self.t("api_required_body"))
            return
        self.apply_scene()
        index = self.selected_scene
        if index is None:
            return
        self.busy = True; self.progress.start(12); self.status_var.set(self.t("regenerating_prompts" if prompts_only else "regenerating_scene"))
        threading.Thread(target=self._regenerate_worker, args=(index, prompts_only), daemon=True).start()

    def _regenerate_worker(self, index: int, prompts_only: bool):
        try:
            scene = regenerate_scene(self.project, index, ChatProvider(self.config), prompts_only)
            self.root.after(0, self._regeneration_done, index, scene, None)
        except Exception as exc:
            self.root.after(0, self._regeneration_done, index, None, exc)

    def _regeneration_done(self, index, scene, error):
        self.busy = False; self.progress.stop()
        if error:
            self.status_var.set(self.t("regeneration_failed")); messagebox.showerror(self.t("regeneration_failed"), str(error)); return
        self.project.scenes[index] = scene; self.save(); self.refresh_all(); self.scene_tree.selection_set(str(index)); self._show_scene(index)
        self.status_var.set(self.t("regenerated_saved", name=scene.prompt_id))

    def start_field_regeneration(self):
        if self.busy or self.selected_scene is None: return
        if self.config.provider != "Demo" and not self.config.api_key:
            messagebox.showinfo(self.t("api_required"), self.t("api_required_body")); return
        if not self.apply_scene(silent=True): return
        index, field = self.selected_scene, self.regenerate_field_var.get()
        self.busy = True; self.progress.start(12); self.status_var.set(self.t("regenerating_field", name=field))
        threading.Thread(target=self._field_worker, args=(index, field), daemon=True).start()

    def _field_worker(self, index, field):
        try:
            value = regenerate_field(self.project, index, field, ChatProvider(self.config))
            self.root.after(0, self._field_done, index, field, value, None)
        except Exception as exc:
            self.root.after(0, self._field_done, index, field, None, exc)

    def _field_done(self, index, field, value, error):
        self.busy = False; self.progress.stop()
        if error:
            self.status_var.set(self.t("field_failed")); messagebox.showerror(self.t("regeneration_failed"), str(error)); return
        setattr(self.project.scenes[index], field, value); self.project.scenes[index].status = "draft"
        save_project(self.project_root, self.project); self.refresh_all(); self.scene_tree.selection_set(str(index)); self._show_scene(index)
        self.status_var.set(self.t("regenerated_saved", name=field))

    def refresh_all(self):
        for key, widget in self.summary_fields.items():
            value = self.project.project_summary.get(key, "")
            if isinstance(value, list): value = "、".join(str(item) for item in value)
            self._set_widget(widget, str(value))
        self.character_list.delete(0, "end")
        for c in self.project.characters: self.character_list.insert("end", f"{c.get('character_id', '?')} — {c.get('name', '')}")
        self.scene_tree.delete(*self.scene_tree.get_children())
        self.scene_tree.tag_configure("draft", foreground=self.colors["muted"])
        self.scene_tree.tag_configure("reviewed", foreground=self.colors["warning"])
        self.scene_tree.tag_configure("approved", foreground=self.colors["success"])
        for i, s in enumerate(self.project.scenes): self.scene_tree.insert("", "end", iid=str(i), values=(s.prompt_id, s.location, s.status.title()), tags=(s.status,))
        self.scene_count_var.set(self.t("scenes_count", count=len(self.project.scenes)))
        if self.project.scenes:
            self.scene_tree.selection_set("0"); self.scene_tree.focus("0"); self._show_scene(0)

    def show_character(self, _event=None):
        selected = self.character_list.curselection()
        if not selected: return
        character = self.project.characters[selected[0]]
        identity = character.get("identity", {})
        movement = character.get("movement_style", {})
        for key, widget in self.character_fields.items():
            value = character.get(key, identity.get(key, movement.get(key, "")))
            self._set_widget(widget, str(value))

    def apply_character(self):
        selected = self.character_list.curselection()
        if not selected: return
        old = self.project.characters[selected[0]]
        values = {key: self._get_widget(widget).strip() for key, widget in self.character_fields.items()}
        identity_keys = ("age", "gender", "face", "eyes", "hair", "build", "distinctive_features")
        movement_keys = ("posture", "walking", "gestures", "eye_behavior", "emotional_motion", "speech_behavior")
        identity = dict(old.get("identity", {})); movement = dict(old.get("movement_style", {}))
        for key in identity_keys: identity[key] = int(values[key]) if key == "age" and values[key].isdigit() else values[key]
        for key in movement_keys: movement[key] = values[key]
        self.project.characters[selected[0]] = {
            **old,
            **{key: values[key] for key in ("character_id", "name", "importance", "role", "default_costume", "personality", "reference_prompt")},
            "identity": identity, "movement_style": movement,
        }
        self.save(); self.refresh_all()

    def select_scene(self, _event=None):
        selected = self.scene_tree.selection()
        if selected:
            target = int(selected[0])
            if self.selected_scene is not None and target != self.selected_scene:
                self.apply_scene(silent=True)
            self._show_scene(target)

    def _show_scene(self, index: int):
        self.selected_scene = index; scene = self.project.scenes[index]
        data = scene.to_dict(); data["characters"] = ", ".join(scene.characters)
        data["subtitles"] = "\n".join(f"{item.start_seconds:g}-{item.end_seconds:g} | {item.speaker} | {item.text}" for item in scene.subtitles)
        for key, widget in self.fields.items(): self._set_widget(widget, str(data.get(key, "")))
        self.status_combo.set(scene.status)
        self.update_photo_count()

    def apply_scene(self, silent=False):
        if self.selected_scene is None: return False
        try:
            raw = {key: self._get_widget(widget).strip() for key, widget in self.fields.items()}
            raw["episode"] = int(raw["episode"]); raw["scene"] = int(raw["scene"]); raw["duration_seconds"] = int(raw["duration_seconds"])
            raw["characters"] = [x.strip() for x in raw["characters"].split(",") if x.strip()]
            raw["subtitles"] = self._parse_subtitles(raw["subtitles"]); raw["status"] = self.status_combo.get()
            self.project.scenes[self.selected_scene] = Scene.from_dict(raw)
        except (ValueError, json.JSONDecodeError, TypeError) as exc:
            if not silent: messagebox.showerror(self.t("invalid_scene"), str(exc))
            return False
        if silent:
            if self.project_root:
                save_project(self.project_root, self.project)
            return True
        selected = self.selected_scene
        self.save(); self.refresh_all()
        if selected is not None and selected < len(self.project.scenes):
            self.scene_tree.selection_set(str(selected)); self._show_scene(selected)
        self.status_var.set(self.t("scene_saved"))
        return True

    def update_photo_count(self, _event=None):
        widget = self.fields.get("photo_prompt")
        if widget and hasattr(self, "photo_count_var"):
            count = len(self._get_widget(widget).strip())
            self.photo_count_var.set(self.t("char_count_warn" if count > 115 else "char_count", count=count))

    def add_scene(self):
        n = len(self.project.scenes) + 1
        self.project.scenes.append(Scene(f"E001_S{n:03d}", 1, n)); self.refresh_all()

    def duplicate_scene(self):
        if self.selected_scene is None: return
        scene = copy.deepcopy(self.project.scenes[self.selected_scene]); scene.scene += 1; scene.prompt_id += "_COPY"; scene.status = "draft"
        self.project.scenes.insert(self.selected_scene + 1, scene); self.refresh_all()

    def delete_scene(self):
        if self.selected_scene is None or not messagebox.askyesno(self.t("delete_scene"), self.t("delete_confirm")): return
        self.project.scenes.pop(self.selected_scene); self.selected_scene = None; self.refresh_all(); self.save()

    def move_scene(self, delta: int):
        if self.selected_scene is None: return
        target = self.selected_scene + delta
        if target < 0 or target >= len(self.project.scenes): return
        self.project.scenes[self.selected_scene], self.project.scenes[target] = self.project.scenes[target], self.project.scenes[self.selected_scene]
        self.refresh_all(); self.scene_tree.selection_set(str(target)); self._show_scene(target); self.save()

    def save(self):
        return self._save_project(silent=False)

    def _save_project(self, silent=False):
        if not self.project_root: messagebox.showinfo(self.t("choose_project"), self.t("choose_project_first")); return
        try:
            summary = {key: self._get_widget(widget).strip() for key, widget in self.summary_fields.items()}
            summary["secondary_themes"] = [value.strip() for value in summary["secondary_themes"].replace("，", "、").split("、") if value.strip()]
            self.project.project_summary.update(summary)
            warnings = validate_project(self.project)
            save_project(self.project_root, self.project)
            if not silent: self.status_var.set(self.t("project_saved") + (f" — {len(warnings)} warning(s)" if warnings else ""))
            return True
        except Exception as exc:
            if not silent: messagebox.showerror(self.t("could_not_save"), str(exc))
            return False

    def open_settings(self):
        SettingsDialog(self)

    def on_close(self):
        if self.busy and not messagebox.askyesno(self.t("processing_active"), self.t("close_active")):
            return
        self.cancel_event.set()
        if self.project_root:
            self.apply_scene(silent=True)
            if not self._save_project(silent=True):
                if not messagebox.askyesno(self.t("invalid_unsaved"), self.t("close_invalid")):
                    return
        self.root.destroy()

    @staticmethod
    def _parse_subtitles(text: str):
        subtitles = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip(): continue
            parts = [part.strip() for part in line.split("|", 2)]
            if len(parts) != 3 or "-" not in parts[0]:
                raise ValueError(f"Subtitle line {line_number} must use: start-end | speaker | text")
            start, end = [value.strip() for value in parts[0].split("-", 1)]
            subtitles.append({"speaker": parts[1], "text": parts[2], "start_seconds": float(start), "end_seconds": float(end)})
        return subtitles

    @staticmethod
    def _set_text(widget: tk.Text, value: str, readonly: bool = False):
        widget.configure(state="normal"); widget.delete("1.0", "end"); widget.insert("1.0", value)
        if readonly: widget.configure(state="disabled")

    @staticmethod
    def _set_widget(widget, value):
        if isinstance(widget, tk.Text): widget.delete("1.0", "end"); widget.insert("1.0", value)
        else: widget.delete(0, "end"); widget.insert(0, value)

    @staticmethod
    def _get_widget(widget):
        return widget.get("1.0", "end") if isinstance(widget, tk.Text) else widget.get()


class SettingsDialog:
    def __init__(self, app: DramaStudioApp):
        self.app = app; self.win = tk.Toplevel(app.root); self.win.title(app.t("api_title")); self.win.geometry("590x330"); self.win.transient(app.root); self.win.grab_set()
        frame = ttk.Frame(self.win, padding=20); frame.pack(fill="both", expand=True)
        self.provider = tk.StringVar(value=app.config.provider); self.endpoint = tk.StringVar(value=app.config.endpoint); self.model = tk.StringVar(value=app.config.model); self.key = tk.StringVar(value=app.config.api_key)
        ttk.Label(frame, text=app.t("provider", provider="").replace(": ", "")).grid(row=0, column=0, sticky="w", pady=6)
        combo = ttk.Combobox(frame, textvariable=self.provider, values=("Demo", "DeepSeek", "Qwen"), state="readonly"); combo.grid(row=0, column=1, sticky="ew", pady=6); combo.bind("<<ComboboxSelected>>", self.changed)
        for row, (label, variable) in enumerate(((app.t("api_endpoint"), self.endpoint), (app.t("model"), self.model)), 1):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=6); ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text=app.t("api_key")).grid(row=3, column=0, sticky="w", pady=6); ttk.Entry(frame, textvariable=self.key, show="•").grid(row=3, column=1, sticky="ew", pady=6)
        ttk.Label(frame, text=app.t("secure_key"), style="Sub.TLabel").grid(row=4, column=1, sticky="w")
        buttons = ttk.Frame(frame); buttons.grid(row=5, column=1, sticky="e", pady=(22, 0))
        CurveButton(buttons, text=app.t("test_connection"), command=self.test, variant="secondary", width=132).pack(side="left", padx=5)
        CurveButton(buttons, text=app.t("save_settings"), command=self.save, variant="primary", width=125).pack(side="left")
        frame.columnconfigure(1, weight=1)

    def changed(self, _event=None):
        endpoint, model = DEFAULTS[self.provider.get()]; self.endpoint.set(endpoint); self.model.set(model); self.key.set(load_api_key(self.provider.get()))

    def config(self):
        return type(self.app.config)(self.provider.get(), self.endpoint.get().strip(), self.model.get().strip(), self.key.get().strip())

    def test(self):
        config = self.config()
        if config.provider == "Demo": messagebox.showinfo(self.app.t("demo_mode"), self.app.t("demo_ready"), parent=self.win); return
        if not config.endpoint.startswith("https://"):
            messagebox.showerror(self.app.t("unsafe_endpoint"), self.app.t("https_required"), parent=self.win); return
        self.win.configure(cursor="watch"); self.win.update_idletasks()
        try: messagebox.showinfo(self.app.t("api_test"), ChatProvider(config).test(), parent=self.win)
        except Exception as exc: messagebox.showerror(self.app.t("connection_failed"), str(exc), parent=self.win)
        finally: self.win.configure(cursor="")

    def save(self):
        config = self.config()
        if config.provider != "Demo" and not config.endpoint.startswith("https://"):
            messagebox.showerror(self.app.t("unsafe_endpoint"), self.app.t("https_required"), parent=self.win); return
        try:
            if config.provider != "Demo" and config.api_key: save_api_key(config.provider, config.api_key)
            save_settings(config)
        except Exception as exc: messagebox.showerror(self.app.t("could_not_settings"), str(exc), parent=self.win); return
        self.app.config = config; self.app.provider_label.configure(text=self.app.t("provider", provider=config.provider)); self.app.status_var.set(self.app.t("settings_saved")); self.win.destroy()
