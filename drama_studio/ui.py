from __future__ import annotations

import copy
import json
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .credentials import load_api_key, save_api_key
from .docx_reader import ExtractedNovel, extract_docx
from .i18n import tr
from .models import ProjectData, Scene, Subtitle
from .pipeline import generate_scene_prompts, process_novel, regenerate_field, regenerate_scene
from .project_library import create_project, invalidate_scene_prompts, scan_projects
from .providers import DEFAULTS, ChatProvider
from .settings import (load_project_library, load_settings, load_ui_language,
                       save_project_library, save_settings, save_ui_language)
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
        self.project_library = load_project_library()
        self.project_root: Path | None = None
        self.novel: ExtractedNovel | None = None
        self.project = ProjectData()
        self.selected_scene: int | None = None
        self.checked_scene_ids: set[str] = set()
        self.sidebar_collapsed = False
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
        self.folder_var = tk.StringVar(value=str(self.project_root) if self.project_root else self.t("no_project_open"))
        self.novel_var = tk.StringVar(value=self._novel_label())
        project_card = ttk.Frame(setup, style="Surface.TFrame"); project_card.grid(row=0, column=0, sticky="ew", padx=(0, 20))
        ttk.Label(project_card, text=self.t("project_folder"), style="Section.TLabel").pack(anchor="w")
        ttk.Label(project_card, textvariable=self.folder_var, style="Sub.TLabel", wraplength=360).pack(anchor="w", pady=(3, 8))
        CurveButton(project_card, text=self.t("project_manager"), command=lambda: self._show_page("projects"), variant="secondary", width=150).pack(anchor="w")
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
        self.sidebar_panel = BezierPanel(workspace, fill=self.colors["sidebar"], radius=24, width=220)
        self.sidebar_panel.pack(side="left", fill="y", padx=(0, 4)); self.sidebar_panel.pack_propagate(False)
        sidebar_panel = self.sidebar_panel
        sidebar = sidebar_panel.content
        self.sidebar_title = tk.Label(sidebar, text=self.t("workspace"), bg=self.colors["sidebar"], fg="#C4DCF3", font=("Helvetica Neue", 9, "bold"), anchor="w", padx=18, pady=10)
        self.sidebar_title.pack(fill="x")
        self.collapse_btn = CurveButton(sidebar, text="‹", command=self.toggle_sidebar, variant="nav", width=42, height=30)
        self.collapse_btn.pack(anchor="e", padx=6)
        self.nav_buttons = {}
        self.nav_labels = dict((("projects", self.t("project_manager")), ("preview", self.t("novel_preview")), ("summary", self.t("story_cast")), ("scenes", self.t("scene_board")), ("prompts", self.t("prompt_board"))))
        for key, label in self.nav_labels.items():
            button = CurveButton(sidebar, text=label, variant="nav", height=44, command=lambda page=key: self._show_page(page))
            button.pack(fill="x", pady=1); self.nav_buttons[key] = button
        self.output_title = tk.Label(sidebar, text=self.t("output"), bg=self.colors["sidebar"], fg="#C4DCF3", font=("Helvetica Neue", 9, "bold"), anchor="w", padx=18, pady=8); self.output_title.pack(fill="x", pady=(20, 0))
        self.output_label = tk.Label(sidebar, text=self.t("output_folders"), bg=self.colors["sidebar"], fg="#E8F3FF", justify="left", anchor="w", padx=18, font=("Helvetica Neue", 10), pady=4); self.output_label.pack(fill="x")
        self.language_box = tk.Frame(sidebar, bg=self.colors["sidebar"]); self.language_box.pack(side="bottom", fill="x", padx=10, pady=12)
        self.language_label = tk.Label(self.language_box, text=self.t("language"), bg=self.colors["sidebar"], fg="#C4DCF3", font=("Helvetica Neue", 9, "bold"), anchor="w"); self.language_label.pack(anchor="w", padx=8, pady=(0, 5))
        self.language_buttons = tk.Frame(self.language_box, bg=self.colors["sidebar"]); self.language_buttons.pack(fill="x")
        self.en_button = CurveButton(self.language_buttons, text="EN", command=lambda: self.switch_language("en"), variant="nav_active" if self.language == "en" else "nav", width=72, height=34); self.en_button.pack(side="left", padx=(0, 4))
        self.zh_button = CurveButton(self.language_buttons, text="中文", command=lambda: self.switch_language("zh"), variant="nav_active" if self.language == "zh" else "nav", width=72, height=34); self.zh_button.pack(side="left")

        self.page_container = tk.Frame(workspace, bg=self.colors["bg"], highlightthickness=0); self.page_container.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.projects_tab = tk.Frame(self.page_container, bg=self.colors["bg"], padx=18, pady=14)
        self.preview_tab = tk.Frame(self.page_container, bg=self.colors["bg"], padx=18, pady=14)
        self.summary_tab = tk.Frame(self.page_container, bg=self.colors["bg"], padx=18, pady=14)
        self.scenes_tab = tk.Frame(self.page_container, bg=self.colors["bg"], padx=14, pady=12)
        self.prompts_tab = tk.Frame(self.page_container, bg=self.colors["bg"], padx=14, pady=12)
        self.pages = {"projects": self.projects_tab, "preview": self.preview_tab, "summary": self.summary_tab, "scenes": self.scenes_tab, "prompts": self.prompts_tab}
        for page in self.pages.values(): page.grid(row=0, column=0, sticky="nsew")
        self.page_container.rowconfigure(0, weight=1); self.page_container.columnconfigure(0, weight=1)
        self._build_projects()
        self._build_preview()
        self._build_summary()
        self._build_scenes()
        self._build_prompts()
        self._show_page("projects" if not self.project_root else "preview")

        bottom = ttk.Frame(self.root, padding=(22, 2, 22, 14))
        bottom.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, mode="determinate", length=190, maximum=100)
        self.progress.pack(side="left")
        self.status_var = tk.StringVar(value=self.t("ready"))
        ttk.Label(bottom, textvariable=self.status_var, style="Status.TLabel").pack(side="left", padx=10)
        CurveButton(bottom, text=self.t("save_changes"), command=self.save, variant="secondary", width=130).pack(side="right")

    def _show_page(self, key):
        self.current_page = key
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items(): button.configure(style="ActiveNav.TButton" if name == key else "Nav.TButton")

    def toggle_sidebar(self):
        self.sidebar_collapsed = not self.sidebar_collapsed
        self.sidebar_panel.configure(width=78 if self.sidebar_collapsed else 220)
        self.sidebar_title.configure(text="" if self.sidebar_collapsed else self.t("workspace"))
        self.collapse_btn.configure(text="›" if self.sidebar_collapsed else "‹")
        icons = {"projects": "▣", "preview": "▤", "summary": "◆", "scenes": "▦", "prompts": "✦"}
        for key, button in self.nav_buttons.items():
            button.configure(text=icons[key] if self.sidebar_collapsed else self.nav_labels[key])
        if self.sidebar_collapsed:
            self.output_title.pack_forget(); self.output_label.pack_forget(); self.language_label.pack_forget()
            self.en_button.configure(width=48); self.zh_button.configure(width=48)
            self.en_button.pack_forget(); self.zh_button.pack_forget()
            self.en_button.pack(pady=2); self.zh_button.pack(pady=2)
        else:
            self.output_title.pack(fill="x", pady=(20, 0), before=self.language_box)
            self.output_label.pack(fill="x", before=self.language_box)
            self.language_label.pack(anchor="w", padx=8, pady=(0, 5), before=self.language_buttons)
            self.en_button.configure(width=72); self.zh_button.configure(width=72)
            self.en_button.pack_forget(); self.zh_button.pack_forget()
            self.en_button.pack(side="left", padx=(0, 4)); self.zh_button.pack(side="left")

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

    def _build_projects(self):
        top = tk.Frame(self.projects_tab, bg=self.colors["bg"]); top.pack(fill="x", pady=(0, 12))
        ttk.Label(top, text=self.t("project_manager_title"), style="PageTitle.TLabel").pack(side="left")
        CurveButton(top, text=self.t("new_project"), command=self.create_new_project, variant="primary", width=150).pack(side="right")
        CurveButton(top, text=self.t("choose_library"), command=self.choose_folder, variant="secondary", width=150).pack(side="right", padx=6)
        self.library_var = tk.StringVar(value=str(self.project_library) if self.project_library else self.t("no_library"))
        ttk.Label(self.projects_tab, textvariable=self.library_var, style="Status.TLabel").pack(anchor="w", pady=(0, 10))
        card = BezierPanel(self.projects_tab, fill=self.colors["surface"], radius=22); card.pack(fill="both", expand=True)
        self.project_tree = ttk.Treeview(card.content, columns=("name", "scenes", "scene_progress", "prompt_progress"), show="headings", selectmode="browse")
        for column, label, width in (("name", self.t("project_name"), 260), ("scenes", self.t("scenes"), 90),
                                     ("scene_progress", self.t("scene_approval"), 150), ("prompt_progress", self.t("prompt_approval"), 180)):
            self.project_tree.heading(column, text=label); self.project_tree.column(column, width=width, anchor="w")
        self.project_tree.pack(fill="both", expand=True)
        self.project_tree.bind("<Double-1>", lambda _event: self.open_selected_project())
        actions = ttk.Frame(card.content, style="Surface.TFrame"); actions.pack(fill="x", pady=(10, 0))
        CurveButton(actions, text=self.t("open_project"), command=self.open_selected_project, variant="primary", width=130).pack(side="left")
        CurveButton(actions, text=self.t("refresh"), command=self.refresh_projects, variant="secondary", width=100).pack(side="left", padx=6)
        self.refresh_projects()

    def choose_folder(self):
        folder = filedialog.askdirectory(title=self.t("choose_library"))
        if not folder: return
        self.project_library = Path(folder); save_project_library(self.project_library)
        if hasattr(self, "library_var"): self.library_var.set(str(self.project_library))
        self.refresh_projects()

    def refresh_projects(self):
        if not hasattr(self, "project_tree"): return
        self.project_tree.delete(*self.project_tree.get_children())
        if not self.project_library: return
        for root, project in scan_projects(self.project_library):
            scenes = len(project.scenes); approved = sum(s.status == "approved" for s in project.scenes)
            prompts = scenes * 2; approved_prompts = sum(s.photo_status == "approved" for s in project.scenes) + sum(s.video_status == "approved" for s in project.scenes)
            self.project_tree.insert("", "end", iid=str(root), values=(project.project_name or root.name, scenes, f"{approved}/{scenes}", f"{approved_prompts}/{prompts}"))

    def create_new_project(self):
        if not self.project_library:
            self.choose_folder()
            if not self.project_library: return
        name = simpledialog.askstring(self.t("new_project"), self.t("enter_project_name"), parent=self.root)
        if not name: return
        try: root, project = create_project(self.project_library, name)
        except Exception as exc: messagebox.showerror(self.t("could_not_create"), str(exc)); return
        self._open_project(root, project)

    def open_selected_project(self):
        selected = self.project_tree.selection()
        if not selected: return
        root = Path(selected[0])
        try: project = load_project(root)
        except Exception as exc: messagebox.showerror(self.t("open_project_failed"), str(exc)); return
        self._open_project(root, project)

    def _open_project(self, root: Path, project: ProjectData):
        if self.project_root: self._save_project(silent=True)
        self.project_root, self.project = root, project
        self.folder_var.set(f"{project.project_name or root.name}\n{root}")
        self.novel = None
        if project.source_document:
            source = root / "Source" / project.source_document
            if source.exists():
                try: self.novel = extract_docx(source)
                except Exception: self.novel = None
        self.novel_var.set(self._novel_label())
        if self.novel:
            self._set_text(self.preview_text, f"{self.novel.title}\n\n{self.novel.text[:50000]}", readonly=True)
        self.refresh_all(); self._show_page("summary" if project.scenes else "preview")
        self.status_var.set(self.t("project_opened"))

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
        bulk = ttk.Frame(self.scenes_tab); bulk.pack(fill="x", pady=(0, 8))
        for column in range(7): bulk.columnconfigure(column, weight=1)
        CurveButton(bulk, text=self.t("select_all"), command=self.check_all_scenes, variant="ghost", height=34).grid(row=0, column=0, sticky="ew", padx=2)
        CurveButton(bulk, text=self.t("clear_selection"), command=self.clear_scene_checks, variant="ghost", height=34).grid(row=0, column=1, sticky="ew", padx=2)
        self.scene_action_var = tk.StringVar(value=self.t("choose_status_action"))
        ttk.Combobox(bulk, textvariable=self.scene_action_var, values=(self.t("approve_selected"), self.t("review_selected"), self.t("delete_selected")), state="readonly").grid(row=0, column=2, columnspan=2, sticky="ew", padx=2)
        CurveButton(bulk, text=self.t("apply_action"), command=self.apply_scene_bulk_action, variant="secondary", height=34).grid(row=0, column=4, sticky="ew", padx=2)
        CurveButton(bulk, text=self.t("regenerate_selected_scenes"), command=lambda: self.start_regeneration(False), variant="primary", height=34).grid(row=0, column=5, columnspan=2, sticky="ew", padx=2)
        pane = ttk.Panedwindow(self.scenes_tab, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left_panel = BezierPanel(pane, fill=self.colors["surface"], radius=20)
        right_panel = BezierPanel(pane, fill=self.colors["surface"], radius=20)
        left, right = left_panel.content, right_panel.content
        pane.add(left_panel, weight=3); pane.add(right_panel, weight=5)
        self.scene_tree = ttk.Treeview(left, columns=("check", "id", "loc", "status"), show="headings", selectmode="extended")
        for column, label, width in (("check", self.t("select"), 58), ("id", self.t("scene"), 100), ("loc", self.t("location"), 160), ("status", self.t("status"), 90)):
            self.scene_tree.heading(column, text=label); self.scene_tree.column(column, width=width, anchor="w")
        self.scene_tree.pack(fill="both", expand=True)
        self.scene_tree.bind("<<TreeviewSelect>>", self.select_scene)
        self.scene_tree.bind("<Button-1>", self.toggle_scene_check, add="+")
        moves = ttk.Frame(left); moves.pack(fill="x", pady=(4, 0))
        for column in range(3): moves.columnconfigure(column, weight=1)
        CurveButton(moves, text=self.t("duplicate"), command=self.duplicate_scene, variant="ghost", height=32).grid(row=0, column=0, sticky="ew", padx=2)
        CurveButton(moves, text=self.t("move_up"), command=lambda: self.move_scene(-1), variant="ghost", height=32).grid(row=0, column=1, sticky="ew", padx=2)
        CurveButton(moves, text=self.t("move_down"), command=lambda: self.move_scene(1), variant="ghost", height=32).grid(row=0, column=2, sticky="ew", padx=2)
        inspector_head = ttk.Frame(right, style="Surface.TFrame"); inspector_head.pack(fill="x", pady=(0, 8))
        ttk.Label(inspector_head, text=self.t("scene_inspector"), style="Section.TLabel").pack(side="left")
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
        actions.columnconfigure(0, weight=1)
        CurveButton(actions, text=self.t("save_scene"), command=self.apply_scene, variant="primary", height=38).grid(row=0, column=0, sticky="e", padx=3, pady=2)

    def _build_prompts(self):
        top = tk.Frame(self.prompts_tab, bg=self.colors["bg"]); top.pack(fill="x", pady=(0, 10))
        ttk.Label(top, text=self.t("prompt_board_title"), style="PageTitle.TLabel").pack(side="left")
        self.prompt_count_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.prompt_count_var, style="Status.TLabel").pack(side="left", padx=12)
        prompt_bulk = ttk.Frame(self.prompts_tab); prompt_bulk.pack(fill="x", pady=(0, 8))
        for column in range(7): prompt_bulk.columnconfigure(column, weight=1)
        CurveButton(prompt_bulk, text=self.t("select_all"), command=self.select_all_prompts, variant="ghost", height=34).grid(row=0, column=0, sticky="ew", padx=2)
        CurveButton(prompt_bulk, text=self.t("clear_selection"), command=self.clear_prompt_selection, variant="ghost", height=34).grid(row=0, column=1, sticky="ew", padx=2)
        self.prompt_action_var = tk.StringVar(value=self.t("choose_status_action"))
        ttk.Combobox(prompt_bulk, textvariable=self.prompt_action_var, values=(self.t("approve_selected"), self.t("review_selected"), self.t("delete_selected")), state="readonly").grid(row=0, column=2, columnspan=2, sticky="ew", padx=2)
        CurveButton(prompt_bulk, text=self.t("apply_action"), command=self.apply_prompt_bulk_action, variant="secondary", height=34).grid(row=0, column=4, sticky="ew", padx=2)
        CurveButton(prompt_bulk, text=self.t("regenerate_selected_prompts"), command=self.start_prompt_generation, variant="primary", height=34).grid(row=0, column=5, columnspan=2, sticky="ew", padx=2)
        pane = ttk.Panedwindow(self.prompts_tab, orient="horizontal"); pane.pack(fill="both", expand=True)
        left_panel = BezierPanel(pane, fill=self.colors["surface"], radius=20); right_panel = BezierPanel(pane, fill=self.colors["surface"], radius=20)
        pane.add(left_panel, weight=3); pane.add(right_panel, weight=4)
        self.prompt_tree = ttk.Treeview(left_panel.content, columns=("scene", "kind", "status", "preview"), show="headings", selectmode="extended")
        for column, label, width in (("scene", self.t("scene"), 105), ("kind", self.t("prompt_type"), 80), ("status", self.t("status"), 90), ("preview", self.t("prompt_preview"), 230)):
            self.prompt_tree.heading(column, text=label); self.prompt_tree.column(column, width=width, anchor="w")
        self.prompt_tree.pack(fill="both", expand=True); self.prompt_tree.bind("<<TreeviewSelect>>", self.show_prompt)
        ttk.Label(right_panel.content, text=self.t("prompt_inspector"), style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        prompt_panel, self.prompt_editor = self._curved_text(right_panel.content, 18, width=60); prompt_panel.pack(fill="both", expand=True)
        self.prompt_char_var = tk.StringVar(value=""); ttk.Label(right_panel.content, textvariable=self.prompt_char_var, style="Sub.TLabel").pack(anchor="e", pady=4)
        actions = ttk.Frame(right_panel.content); actions.pack(fill="x", pady=(6, 0))
        CurveButton(actions, text=self.t("save_prompt"), command=self.save_prompt_edit, variant="secondary", width=115).pack(side="right")

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

    def import_docx(self):
        path = filedialog.askopenfilename(title=self.t("novel_dialog"), filetypes=[(self.t("word_document"), "*.docx")])
        if not path: return
        if not self.project_root:
            messagebox.showinfo(self.t("choose_project"), self.t("create_project_first")); self._show_page("projects"); return
        try:
            source_dir = ensure_project_folders(self.project_root)["source"]
            destination = source_dir / Path(path).name
            if Path(path).resolve() != destination.resolve(): shutil.copy2(path, destination)
            self.novel = extract_docx(destination)
            self.project.source_document = destination.name
            save_project(self.project_root, self.project)
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
        self.busy = True; self.cancel_event.clear(); self.progress["value"] = 0; self.process_btn.configure(state="disabled"); self.cancel_btn.configure(state="normal")
        threading.Thread(target=self._process_worker, daemon=True).start()

    def _process_worker(self):
        try:
            project = process_novel(self.novel, ChatProvider(self.config), self._thread_progress, self.cancel_event.is_set)
            self.root.after(0, self._processing_done, project, None)
        except Exception as exc:
            self.root.after(0, self._processing_done, None, exc)

    def _processing_done(self, project, error):
        self.busy = False; self.progress["value"] = 100; self.process_btn.configure(state="normal"); self.cancel_btn.configure(state="disabled")
        if error: self.status_var.set(self.t("processing_failed")); messagebox.showerror(self.t("processing_failed"), str(error)); return
        project.project_name = self.project.project_name or self.project_root.name
        project.source_document = self.project.source_document
        self.project = project; save_project(self.project_root, self.project); self.refresh_all(); self._show_page("scenes"); self.status_var.set(self.t("created_scenes", count=len(project.scenes)))
        messagebox.showinfo(self.t("scene_review_required"), self.t("scene_review_body", count=len(project.scenes)))

    def cancel_processing(self):
        if self.busy:
            self.cancel_event.set()
            self.status_var.set(self.t("cancelling"))

    def _thread_progress(self, message):
        parts = message.split(" ", 3)
        if len(parts) == 4 and parts[0] == "PROGRESS":
            try: percent = int(parts[1]) / max(1, int(parts[2])) * 100
            except ValueError: percent = 0
            self.root.after(0, self.progress.configure, {"value": percent})
            message = parts[3]
        self.root.after(0, self.status_var.set, message)

    def start_regeneration(self, prompts_only: bool):
        if self.busy or self.selected_scene is None:
            return
        if self.config.provider != "Demo" and not self.config.api_key:
            messagebox.showinfo(self.t("api_required"), self.t("api_required_body"))
            return
        indexes = self._scene_action_indexes()
        if not indexes:
            messagebox.showinfo(self.t("nothing_selected"), self.t("select_scene_action_body")); return
        index = indexes[0]
        self.apply_scene()
        if index is None:
            return
        if prompts_only: indexes = [index]
        if len(indexes) > 1:
            if not messagebox.askyesno(self.t("regenerating_scene"), self.t("regenerate_many_confirm", count=len(indexes))): return
            self.busy = True; self.progress["value"] = 0; self.cancel_event.clear(); self.cancel_btn.configure(state="normal")
            threading.Thread(target=self._regenerate_many_worker, args=(indexes,), daemon=True).start(); return
        self.busy = True; self.progress.start(12); self.status_var.set(self.t("regenerating_prompts" if prompts_only else "regenerating_scene"))
        threading.Thread(target=self._regenerate_worker, args=(index, prompts_only), daemon=True).start()

    def _regenerate_many_worker(self, indexes):
        results = {}
        try:
            provider = ChatProvider(self.config)
            for position, index in enumerate(indexes, 1):
                if self.cancel_event.is_set(): raise InterruptedError("Scene regeneration cancelled.")
                scene = regenerate_scene(self.project, index, provider, False); invalidate_scene_prompts(scene); results[index] = scene
                self._thread_progress(f"PROGRESS {position} {len(indexes)} Regenerated {scene.prompt_id}")
            self.root.after(0, self._regenerate_many_done, results, None)
        except Exception as exc: self.root.after(0, self._regenerate_many_done, results, exc)

    def _regenerate_many_done(self, results, error):
        self.busy = False; self.cancel_btn.configure(state="disabled")
        for index, scene in results.items(): self.project.scenes[index] = scene
        if results: save_project(self.project_root, self.project); self.refresh_all()
        if error: messagebox.showerror(self.t("regeneration_failed"), str(error)); return
        self.progress["value"] = 100; self.status_var.set(self.t("scenes_updated", count=len(results)))

    def _regenerate_worker(self, index: int, prompts_only: bool):
        try:
            scene = regenerate_scene(self.project, index, ChatProvider(self.config), prompts_only)
            self.root.after(0, self._regeneration_done, index, scene, prompts_only, None)
        except Exception as exc:
            self.root.after(0, self._regeneration_done, index, None, prompts_only, exc)

    def _regeneration_done(self, index, scene, prompts_only, error):
        self.busy = False; self.progress.stop()
        if error:
            self.status_var.set(self.t("regeneration_failed")); messagebox.showerror(self.t("regeneration_failed"), str(error)); return
        original = self.project.scenes[index]
        if not self._review_replacement(original, scene, self.t("regenerating_prompts" if prompts_only else "regenerating_scene")):
            self.status_var.set(self.t("ready")); return
        if prompts_only:
            scene.status = original.status
            scene.photo_status = scene.video_status = "draft"
        else: invalidate_scene_prompts(scene)
        self.project.scenes[index] = scene; self.save(); self.refresh_all(); self.scene_tree.selection_set(str(index)); self._show_scene(index)
        self.status_var.set(self.t("regenerated_saved", name=scene.prompt_id))

    def _review_replacement(self, original, replacement, title):
        win = tk.Toplevel(self.root); win.title(title); win.geometry("980x620"); win.transient(self.root); win.grab_set()
        result = {"accept": False}
        holder = ttk.Frame(win, padding=16); holder.pack(fill="both", expand=True)
        for column, (label, scene) in enumerate(((self.t("current_version"), original), (self.t("new_version"), replacement))):
            frame = ttk.Frame(holder); frame.grid(row=0, column=column, sticky="nsew", padx=6)
            ttk.Label(frame, text=label, style="Section.TLabel").pack(anchor="w", pady=(0, 6))
            text = tk.Text(frame, wrap="word", relief="flat", padx=10, pady=10, background="#FBFDFF")
            text.insert("1.0", json.dumps(scene.to_dict(), ensure_ascii=False, indent=2)); text.configure(state="disabled"); text.pack(fill="both", expand=True)
            holder.columnconfigure(column, weight=1)
        holder.rowconfigure(0, weight=1)
        actions = ttk.Frame(win, padding=(16, 0, 16, 16)); actions.pack(fill="x")
        def accept(): result["accept"] = True; win.destroy()
        CurveButton(actions, text=self.t("accept_new"), command=accept, variant="primary", width=140).pack(side="right")
        CurveButton(actions, text=self.t("keep_original"), command=win.destroy, variant="secondary", width=140).pack(side="right", padx=6)
        win.protocol("WM_DELETE_WINDOW", win.destroy); self.root.wait_window(win)
        return result["accept"]

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
        valid_ids = {scene.prompt_id for scene in self.project.scenes}
        self.checked_scene_ids.intersection_update(valid_ids)
        for i, s in enumerate(self.project.scenes):
            mark = "☑" if s.prompt_id in self.checked_scene_ids else "☐"
            self.scene_tree.insert("", "end", iid=str(i), values=(mark, s.prompt_id, s.location, s.status.title()), tags=(s.status,))
        self.scene_count_var.set(self.t("scenes_count", count=len(self.project.scenes)))
        self.prompt_tree.delete(*self.prompt_tree.get_children())
        approved_prompts = 0
        for i, scene in enumerate(self.project.scenes):
            for kind, value, status in (("photo", scene.photo_prompt, scene.photo_status), ("video", scene.video_prompt, scene.video_status)):
                iid = f"{i}:{kind}"; preview = value.replace("\n", " ")[:80] if value else self.t("regeneration_required")
                self.prompt_tree.insert("", "end", iid=iid, values=(scene.prompt_id, self.t(kind), status.title(), preview), tags=(status,))
                approved_prompts += status == "approved"
        self.prompt_count_var.set(self.t("prompts_approved", approved=approved_prompts, total=len(self.project.scenes) * 2))
        self.refresh_projects()
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
            focused = self.scene_tree.focus()
            target = int(focused if focused in selected else selected[0])
            if self.selected_scene is not None and target != self.selected_scene:
                self.apply_scene(silent=True)
            self._show_scene(target)

    def toggle_scene_check(self, event):
        if self.scene_tree.identify_region(event.x, event.y) != "cell" or self.scene_tree.identify_column(event.x) != "#1": return
        iid = self.scene_tree.identify_row(event.y)
        if not iid: return "break"
        prompt_id = self.project.scenes[int(iid)].prompt_id
        if prompt_id in self.checked_scene_ids: self.checked_scene_ids.remove(prompt_id)
        else: self.checked_scene_ids.add(prompt_id)
        values = list(self.scene_tree.item(iid, "values")); values[0] = "☑" if prompt_id in self.checked_scene_ids else "☐"
        self.scene_tree.item(iid, values=values)
        return "break"

    def check_all_scenes(self):
        self.checked_scene_ids = {scene.prompt_id for scene in self.project.scenes}; self.refresh_all()
        children = self.scene_tree.get_children()
        if children: self.scene_tree.selection_set(children); self.scene_tree.focus(children[0])

    def clear_scene_checks(self):
        self.checked_scene_ids.clear(); self.refresh_all(); self.scene_tree.selection_remove(self.scene_tree.get_children())

    def _scene_action_indexes(self):
        checked = [i for i, scene in enumerate(self.project.scenes) if scene.prompt_id in self.checked_scene_ids]
        if checked: return checked
        selected = self.scene_tree.selection()
        if selected: return [int(iid) for iid in selected]
        return []

    def _show_scene(self, index: int):
        self.selected_scene = index; scene = self.project.scenes[index]
        data = scene.to_dict(); data["characters"] = ", ".join(scene.characters)
        data["subtitles"] = "\n".join(f"{item.start_seconds:g}-{item.end_seconds:g} | {item.speaker} | {item.text}" for item in scene.subtitles)
        for key, widget in self.fields.items(): self._set_widget(widget, str(data.get(key, "")))
        self.update_photo_count()

    def apply_scene(self, silent=False):
        if self.selected_scene is None: return False
        try:
            raw = {key: self._get_widget(widget).strip() for key, widget in self.fields.items()}
            raw["episode"] = int(raw["episode"]); raw["scene"] = int(raw["scene"]); raw["duration_seconds"] = int(raw["duration_seconds"])
            raw["characters"] = [x.strip() for x in raw["characters"].split(",") if x.strip()]
            original = self.project.scenes[self.selected_scene]
            raw["subtitles"] = self._parse_subtitles(raw["subtitles"]); raw["status"] = original.status
            replacement = Scene.from_dict(raw)
            content_fields = ("plot", "location", "time_of_day", "characters", "character_state", "action", "subtitles", "duration_seconds", "shot", "continuity")
            changed = any(getattr(original, key) != getattr(replacement, key) for key in content_fields)
            if changed and original.status == "approved":
                invalidate_scene_prompts(replacement)
            else:
                replacement.photo_status, replacement.video_status = original.photo_status, original.video_status
            self.project.scenes[self.selected_scene] = replacement
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

    def set_scene_status(self, status):
        indexes = self._scene_action_indexes()
        if not indexes: return
        self.apply_scene(silent=True)
        for index in indexes: self.project.scenes[index].status = status
        save_project(self.project_root, self.project); self.checked_scene_ids.clear(); self.refresh_all()
        self.status_var.set(self.t("scenes_updated", count=len(indexes)))

    def apply_scene_bulk_action(self):
        if not self._scene_action_indexes():
            messagebox.showinfo(self.t("nothing_selected"), self.t("select_scene_action_body")); return
        action = self.scene_action_var.get()
        if action == self.t("approve_selected"): self.set_scene_status("approved")
        elif action == self.t("review_selected"): self.set_scene_status("reviewed")
        elif action == self.t("delete_selected"): self.delete_scene()
        else: messagebox.showinfo(self.t("choose_action"), self.t("choose_action_body"))

    def select_all_prompts(self):
        children = self.prompt_tree.get_children()
        if children: self.prompt_tree.selection_set(children); self.prompt_tree.focus(children[0])

    def clear_prompt_selection(self):
        self.prompt_tree.selection_remove(self.prompt_tree.get_children())

    def apply_prompt_bulk_action(self):
        if not self.prompt_tree.selection():
            messagebox.showinfo(self.t("nothing_selected"), self.t("select_prompt_action_body")); return
        action = self.prompt_action_var.get()
        if action == self.t("approve_selected"): self.set_prompt_status("approved")
        elif action == self.t("review_selected"): self.set_prompt_status("reviewed")
        elif action == self.t("delete_selected"): self.delete_selected_prompts()
        else: messagebox.showinfo(self.t("choose_action"), self.t("choose_action_body"))

    def delete_selected_prompts(self):
        selected = self.prompt_tree.selection()
        if not selected:
            messagebox.showinfo(self.t("nothing_selected"), self.t("select_prompt_action_body")); return
        if not messagebox.askyesno(self.t("delete_selected"), self.t("delete_prompts_confirm", count=len(selected))): return
        for iid in selected:
            index_text, kind = iid.split(":", 1); scene = self.project.scenes[int(index_text)]
            if kind == "photo": scene.photo_prompt, scene.photo_status = "", "missing"
            else: scene.video_prompt, scene.video_status = "", "missing"
        save_project(self.project_root, self.project); self.refresh_all()
        self.status_var.set(self.t("prompts_deleted", count=len(selected)))

    def show_prompt(self, _event=None):
        selected = self.prompt_tree.selection()
        if not selected: return
        index_text, kind = selected[0].split(":", 1); scene = self.project.scenes[int(index_text)]
        value = scene.photo_prompt if kind == "photo" else scene.video_prompt
        self._set_text(self.prompt_editor, value)
        self.prompt_char_var.set(self.t("char_count", count=len(value)))

    def save_prompt_edit(self):
        selected = self.prompt_tree.selection()
        if len(selected) != 1:
            messagebox.showinfo(self.t("select_one_prompt"), self.t("select_one_prompt_body")); return
        index_text, kind = selected[0].split(":", 1); scene = self.project.scenes[int(index_text)]
        value = self.prompt_editor.get("1.0", "end").strip()
        if kind == "photo": scene.photo_prompt, scene.photo_status = value, "draft"
        else: scene.video_prompt, scene.video_status = value, "draft"
        save_project(self.project_root, self.project); self.refresh_all(); self.prompt_tree.selection_set(selected[0]); self.show_prompt()

    def set_prompt_status(self, status):
        selected = self.prompt_tree.selection()
        if not selected: return
        skipped = 0
        for iid in selected:
            index_text, kind = iid.split(":", 1); scene = self.project.scenes[int(index_text)]
            value = scene.photo_prompt if kind == "photo" else scene.video_prompt
            if not value.strip(): skipped += 1; continue
            if kind == "photo": scene.photo_status = status
            else: scene.video_status = status
        save_project(self.project_root, self.project); self.refresh_all()
        self.status_var.set(self.t("prompts_updated", count=len(selected) - skipped))

    def start_prompt_generation(self):
        if self.busy or not self.project_root: return
        selected = self.prompt_tree.selection()
        if not selected:
            messagebox.showinfo(self.t("nothing_selected"), self.t("select_prompt_action_body")); return
        jobs = [(int(iid.split(":", 1)[0]), iid.split(":", 1)[1]) for iid in selected]
        jobs = [(index, kind) for index, kind in jobs if self.project.scenes[index].status == "approved"]
        if not jobs:
            messagebox.showinfo(self.t("nothing_to_generate"), self.t("select_approved_scenes")); return
        if self.config.provider != "Demo" and not self.config.api_key:
            messagebox.showinfo(self.t("api_required"), self.t("api_required_body")); return
        self.busy = True; self.cancel_event.clear(); self.progress["value"] = 0; self.cancel_btn.configure(state="normal"); self.status_var.set(self.t("generating_prompts"))
        threading.Thread(target=self._prompt_worker, args=(jobs,), daemon=True).start()

    def _prompt_worker(self, jobs):
        results = []
        try:
            provider = ChatProvider(self.config)
            for position, (index, kind) in enumerate(jobs, 1):
                if self.cancel_event.is_set(): raise InterruptedError("Prompt generation cancelled.")
                field = "photo_prompt" if kind == "photo" else "video_prompt"
                value = regenerate_field(self.project, index, field, provider)
                results.append((index, kind, value))
                self._thread_progress(f"PROGRESS {position} {len(jobs)} Generated {kind} prompt for {self.project.scenes[index].prompt_id}")
            self.root.after(0, self._prompt_done, results, None)
        except Exception as exc: self.root.after(0, self._prompt_done, results, exc)

    def _prompt_done(self, results, error):
        self.busy = False; self.cancel_btn.configure(state="disabled")
        for index, kind, value in results:
            scene = self.project.scenes[index]
            if kind == "photo": scene.photo_prompt, scene.photo_status = value, "draft"
            else: scene.video_prompt, scene.video_status = value, "draft"
        if results: save_project(self.project_root, self.project)
        self.refresh_all(); self._show_page("prompts")
        if error: messagebox.showerror(self.t("processing_failed"), str(error)); return
        self.progress["value"] = 100
        self.status_var.set(self.t("prompts_ready", count=len(results)))
        messagebox.showinfo(self.t("prompt_review_required"), self.t("prompt_review_body", count=len(results)))

    def update_photo_count(self, _event=None):
        widget = self.fields.get("photo_prompt")
        if widget and hasattr(self, "photo_count_var"):
            count = len(self._get_widget(widget).strip())
            self.photo_count_var.set(self.t("char_count_warn" if count > 115 else "char_count", count=count))

    def add_scene(self):
        n = len(self.project.scenes) + 1
        self.project.scenes.append(Scene(f"E001_S{n:03d}", 1, n)); save_project(self.project_root, self.project); self.refresh_all()
        index = len(self.project.scenes) - 1; self.scene_tree.selection_set(str(index)); self.scene_tree.focus(str(index)); self.scene_tree.see(str(index)); self._show_scene(index)

    def duplicate_scene(self):
        if self.selected_scene is None: return
        scene = copy.deepcopy(self.project.scenes[self.selected_scene]); scene.scene += 1; scene.prompt_id += "_COPY"; scene.status = "draft"
        target = self.selected_scene + 1; self.project.scenes.insert(target, scene); save_project(self.project_root, self.project); self.refresh_all()
        self.scene_tree.selection_set(str(target)); self.scene_tree.focus(str(target)); self.scene_tree.see(str(target)); self._show_scene(target)

    def delete_scene(self):
        indexes = self._scene_action_indexes()
        if not indexes or not messagebox.askyesno(self.t("delete_scene"), self.t("delete_many_confirm", count=len(indexes))): return
        for index in sorted(indexes, reverse=True): self.project.scenes.pop(index)
        self.checked_scene_ids.clear(); self.selected_scene = None; save_project(self.project_root, self.project); self.refresh_all()

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
