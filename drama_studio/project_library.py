from __future__ import annotations

import re
from pathlib import Path

from .models import ProjectData
from .storage import ensure_project_folders, load_project, save_project


INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validate_project_name(name: str) -> str:
    value = name.strip().rstrip(". ")
    if not value or value in {".", ".."}:
        raise ValueError("Enter a project name.")
    if INVALID.search(value):
        raise ValueError('Project names cannot contain < > : " / \\ | ? *')
    if value.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError("That name is reserved by Windows.")
    return value


def create_project(library: str | Path, name: str) -> tuple[Path, ProjectData]:
    library_path = Path(library)
    library_path.mkdir(parents=True, exist_ok=True)
    clean = validate_project_name(name)
    root = library_path / clean
    if root.exists():
        raise FileExistsError(f'A project named "{clean}" already exists.')
    ensure_project_folders(root)
    project = ProjectData(project_name=clean)
    save_project(root, project)
    return root, project


def scan_projects(library: str | Path) -> list[tuple[Path, ProjectData]]:
    base = Path(library)
    if not base.is_dir():
        return []
    found = []
    for folder in sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        marker = folder / "Project Plan" / "project.drama"
        legacy = folder / "Project Plan" / "Scene Plan.json"
        if marker.exists() or legacy.exists():
            try: found.append((folder, load_project(folder)))
            except (OSError, ValueError): continue
    return found


def invalidate_scene_prompts(scene) -> None:
    scene.photo_prompt = ""
    scene.video_prompt = ""
    scene.photo_status = "missing"
    scene.video_status = "missing"
    scene.status = "draft"
