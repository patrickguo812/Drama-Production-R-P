from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import ProjectData


def ensure_project_folders(root: str | Path) -> dict[str, Path]:
    base = Path(root)
    paths = {
        "root": base,
        "plan": base / "Project Plan",
        "characters": base / "Project Plan" / "Character Profiles",
        "genre": base / "Project Genre",
        "references": base / "Project Genre" / "Character References",
        "photos": base / "Project Genre" / "Photos",
    }
    for key, path in paths.items():
        if key != "root":
            path.mkdir(parents=True, exist_ok=True)
    return paths


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".drama-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def save_project(root: str | Path, project: ProjectData) -> None:
    paths = ensure_project_folders(root)
    scene_plan = {
        "project_summary": project.project_summary,
        "scenes": [scene.to_dict() for scene in project.scenes],
    }
    _atomic_text(paths["plan"] / "Scene Plan.json", json.dumps(scene_plan, ensure_ascii=False, indent=2))
    active_ids: set[str] = set()
    for character in project.characters:
        character_id = safe_id(str(character.get("character_id", "CHARACTER")))
        active_ids.add(character_id)
        _atomic_text(paths["characters"] / f"{character_id}.json", json.dumps(character, ensure_ascii=False, indent=2))
    # Do not silently delete stale profiles; user-created files are preserved.
    _atomic_text(paths["genre"] / "Photo Prompts.txt", render_photo_prompts(project))
    _atomic_text(paths["genre"] / "Video Prompts.txt", render_video_prompts(project))


def load_project(root: str | Path) -> ProjectData:
    base = Path(root)
    path = base / "Project Plan" / "Scene Plan.json"
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    characters = []
    profiles = base / "Project Plan" / "Character Profiles"
    if profiles.exists():
        for profile in sorted(profiles.glob("*.json")):
            try:
                characters.append(json.loads(profile.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    data["characters"] = characters
    return ProjectData.from_dict(data)


def safe_id(value: str) -> str:
    cleaned = "".join(c for c in value.upper() if c.isalnum() or c in "_-")
    return cleaned or "CHARACTER"


def render_photo_prompts(project: ProjectData) -> str:
    blocks = [
        "DRAMA_STUDIO_PROMPT_FORMAT: 1\n"
        "PROMPT_KIND: PHOTO\n"
        "GENERATION_RULE: Process one marked block at a time; generate only scenes whose STATUS is APPROVED."
    ]
    for s in project.scenes:
        blocks.append(
            f"===== PHOTO_SCENE_BEGIN {s.prompt_id} =====\n"
            f"PROMPT_ID: {s.prompt_id}\nASPECT_RATIO: 9:16\nSTATUS: {s.status.upper()}\n"
            f"CHARACTER_REFERENCES: {', '.join(s.characters) if s.characters else 'NONE'}\n"
            f"LOCATION: {s.location}\n\n"
            f"<<<PHOTO_PROMPT_BEGIN>>>\n{s.photo_prompt.strip()}\n<<<PHOTO_PROMPT_END>>>\n\n"
            f"===== PHOTO_SCENE_END {s.prompt_id} ====="
        )
    return "\n\n".join(blocks) + "\n"


def render_video_prompts(project: ProjectData) -> str:
    blocks = [
        "DRAMA_STUDIO_PROMPT_FORMAT: 1\n"
        "PROMPT_KIND: VIDEO\n"
        "GENERATION_RULE: Process one marked block at a time; generate only scenes whose STATUS is APPROVED."
    ]
    for s in project.scenes:
        blocks.append(
            f"===== VIDEO_SCENE_BEGIN {s.prompt_id} =====\n"
            f"PROMPT_ID: {s.prompt_id}\nDURATION_SECONDS: {s.duration_seconds}\n"
            f"SOURCE_PHOTO: {s.prompt_id}\nSTATUS: {s.status.upper()}\n"
            f"CHARACTER_REFERENCES: {', '.join(s.characters) if s.characters else 'NONE'}\n\n"
            f"<<<VIDEO_PROMPT_BEGIN>>>\n{s.video_prompt.strip()}\n<<<VIDEO_PROMPT_END>>>\n\n"
            f"===== VIDEO_SCENE_END {s.prompt_id} ====="
        )
    return "\n\n".join(blocks) + "\n"


def extract_marked_prompt(content: str, prompt_id: str, kind: str = "PHOTO") -> str:
    kind = kind.upper()
    block_start = f"===== {kind}_SCENE_BEGIN {prompt_id} ====="
    block_end = f"===== {kind}_SCENE_END {prompt_id} ====="
    prompt_start = f"<<<{kind}_PROMPT_BEGIN>>>"
    prompt_end = f"<<<{kind}_PROMPT_END>>>"
    start = content.find(block_start)
    end = content.find(block_end, start + len(block_start))
    if start < 0 or end < 0:
        raise KeyError(f"Prompt block {prompt_id} was not found.")
    block = content[start:end]
    value_start = block.find(prompt_start)
    value_end = block.find(prompt_end, value_start + len(prompt_start))
    if value_start < 0 or value_end < 0:
        raise ValueError(f"Prompt markers are incomplete for {prompt_id}.")
    return block[value_start + len(prompt_start):value_end].strip()
