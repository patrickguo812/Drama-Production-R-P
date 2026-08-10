from __future__ import annotations

import re
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import ProjectData
from .storage import ensure_project_folders, load_project, save_project


INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TRASH_FOLDER = ".DramaStudio Trash"
TRASH_METADATA = ".drama-trash.json"


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


def _direct_child(library: str | Path, root: str | Path) -> tuple[Path, Path]:
    base = Path(library).resolve()
    child = Path(root).resolve()
    if child.parent != base or child.name == TRASH_FOLDER:
        raise ValueError("The project must be directly inside the selected project library.")
    return base, child


def rename_project(library: str | Path, root: str | Path, name: str) -> tuple[Path, ProjectData]:
    base, source = _direct_child(library, root)
    clean = validate_project_name(name)
    target = base / clean
    if target != source and target.exists():
        raise FileExistsError(f'A project named "{clean}" already exists.')
    project = load_project(source)
    if target != source:
        source.rename(target)
    project.project_name = clean
    save_project(target, project)
    return target, project


def duplicate_project(library: str | Path, root: str | Path, name: str) -> tuple[Path, ProjectData]:
    base, source = _direct_child(library, root)
    clean = validate_project_name(name)
    target = base / clean
    if target.exists():
        raise FileExistsError(f'A project named "{clean}" already exists.')
    load_project(source)  # Refuse to copy arbitrary non-project folders.
    shutil.copytree(source, target)
    project = load_project(target)
    project.project_name = clean
    save_project(target, project)
    return target, project


def move_project_to_trash(library: str | Path, root: str | Path, now: datetime | None = None) -> Path:
    base, source = _direct_child(library, root)
    project = load_project(source)  # Refuse to move arbitrary folders.
    deleted_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    trash = base / TRASH_FOLDER
    trash.mkdir(exist_ok=True)
    target = trash / source.name
    suffix = 2
    while target.exists():
        target = trash / f"{source.name} ({suffix})"
        suffix += 1
    source.rename(target)
    metadata = {
        "format": "drama-studio-trash-v1",
        "deleted_at": deleted_at.isoformat(),
        "original_name": source.name,
        "project_name": project.project_name or source.name,
    }
    (target / TRASH_METADATA).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _trash_record(library: str | Path, root: str | Path) -> tuple[Path, dict]:
    trash = (Path(library).resolve() / TRASH_FOLDER).resolve()
    child = Path(root).resolve()
    if child.parent != trash:
        raise ValueError("The item is not directly inside Drama Studio Trash.")
    metadata_path = child / TRASH_METADATA
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("format") != "drama-studio-trash-v1": raise ValueError
        datetime.fromisoformat(metadata["deleted_at"])
        load_project(child)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("This folder is not a valid Drama Studio trash item.") from exc
    return child, metadata


def scan_trash(library: str | Path) -> list[tuple[Path, dict, ProjectData]]:
    trash = Path(library) / TRASH_FOLDER
    if not trash.is_dir(): return []
    found = []
    for folder in sorted((p for p in trash.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        try:
            child, metadata = _trash_record(library, folder)
            found.append((child, metadata, load_project(child)))
        except (OSError, ValueError):
            continue
    return found


def restore_project(library: str | Path, root: str | Path, name: str | None = None) -> tuple[Path, ProjectData]:
    source, metadata = _trash_record(library, root)
    clean = validate_project_name(name or metadata["original_name"])
    target = Path(library).resolve() / clean
    if target.exists():
        raise FileExistsError(f'A project named "{clean}" already exists.')
    (source / TRASH_METADATA).unlink()
    source.rename(target)
    project = load_project(target)
    project.project_name = clean
    save_project(target, project)
    return target, project


def permanently_delete_trash_item(library: str | Path, root: str | Path) -> None:
    child, _metadata = _trash_record(library, root)
    shutil.rmtree(child)


def purge_expired_trash(library: str | Path, days: int = 10, now: datetime | None = None) -> list[Path]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(days=days)
    removed = []
    for child, metadata, _project in scan_trash(library):
        deleted_at = datetime.fromisoformat(metadata["deleted_at"])
        if deleted_at.tzinfo is None: deleted_at = deleted_at.replace(tzinfo=timezone.utc)
        if deleted_at.astimezone(timezone.utc) <= cutoff:
            shutil.rmtree(child)
            removed.append(child)
    return removed


def invalidate_scene_prompts(scene) -> None:
    scene.photo_prompt = ""
    scene.video_prompt = ""
    scene.photo_status = "missing"
    scene.video_status = "missing"
    scene.status = "draft"
