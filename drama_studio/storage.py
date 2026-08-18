from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .models import ProjectData
from .characters import normalize_character_profiles


def ensure_project_folders(root: str | Path) -> dict[str, Path]:
    base = Path(root)
    paths = {
        "root": base,
        "source": base / "Source",
        "plan": base / "Project Plan",
        "character_profiles": base / "Project Plan" / "Character Profiles",
        "genre": base / "Project Genre",
        "references": base / "Project Genre" / "Character References",
        "photos": base / "Project Genre" / "Photos",
        "videos": base / "Project Genre" / "Videos",
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
    project.characters = normalize_character_profiles(project.characters)
    scene_total = len(project.scenes)
    prompt_total = scene_total * 2
    prompt_done = sum(bool(scene.photo_prompt.strip()) for scene in project.scenes) + sum(bool(scene.video_prompt.strip()) for scene in project.scenes)
    project.processing.update(scene_percent=100 if scene_total else 0, scene_done=scene_total, scene_total=scene_total,
                              prompt_percent=(prompt_done / prompt_total * 100) if prompt_total else 0,
                              prompt_done=prompt_done, prompt_total=prompt_total)
    project.processing.setdefault("scene_state", "complete" if scene_total else "idle")
    if project.processing.get("prompt_state") != "processing":
        project.processing["prompt_state"] = "complete" if prompt_total and prompt_done == prompt_total else "idle" if not prompt_done else "warning"
    scene_plan = {"project_summary": project.project_summary, "scenes": [scene.to_dict() for scene in project.scenes]}
    internal = paths["plan"] / "project.drama"
    if internal.exists():
        try: shutil.copy2(internal, paths["plan"] / "project.drama.recovery")
        except OSError: pass
    _atomic_text(internal, json.dumps(project.to_dict(), ensure_ascii=False, indent=2))
    _atomic_text(paths["plan"] / "Scene Plan.json", json.dumps(scene_plan, ensure_ascii=False, indent=2))
    active_profiles = set()
    for character in project.characters:
        character_id = safe_id(character.get("character_id", "")); active_profiles.add(character_id)
        profile = {"_format": "drama-character-profile-v1", **character}
        _atomic_text(paths["character_profiles"] / f"{character_id}.json", json.dumps(profile, ensure_ascii=False, indent=2))
        (paths["references"] / character_id).mkdir(parents=True, exist_ok=True)
    for candidate in paths["character_profiles"].glob("*.json"):
        if candidate.stem in active_profiles: continue
        try: managed = json.loads(candidate.read_text(encoding="utf-8")).get("_format") == "drama-character-profile-v1"
        except (OSError, ValueError, TypeError): managed = False
        if managed: candidate.unlink()
    _atomic_text(paths["genre"] / "Photos Prompts.json", render_photo_prompts(project))
    _atomic_text(paths["genre"] / "Videos Prompts.json", render_video_prompts(project))
    for legacy in (paths["plan"] / "Scene Plan.txt", paths["plan"] / "Characters.txt", paths["genre"] / "Photos Prompts.txt", paths["genre"] / "Videos Prompts.txt"):
        if legacy.exists(): legacy.unlink()


def load_project(root: str | Path) -> ProjectData:
    base = Path(root)
    internal = base / "Project Plan" / "project.drama"
    if internal.exists():
        try:
            with internal.open(encoding="utf-8") as stream:
                return ProjectData.from_dict(json.load(stream))
        except (OSError, json.JSONDecodeError):
            recovery = internal.with_name("project.drama.recovery")
            if recovery.exists():
                with recovery.open(encoding="utf-8") as stream:
                    return ProjectData.from_dict(json.load(stream))
            raise
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
    prompts = []
    for s in project.scenes:
        if s.photo_status != "approved" or not s.photo_prompt.strip():
            continue
        prompts.append({
            "prompt_id": s.prompt_id, "aspect_ratio": "9:16", "character_ids": s.characters,
            "character_profile_files": [f"../Project Plan/Character Profiles/{safe_id(value)}.json" for value in s.characters],
            "location": s.location, "positive_prompt": s.photo_prompt.strip(),
            "negative_prompt": s.photo_negative_prompt.strip(), "negative_prompt_required": bool(s.photo_negative_prompt.strip()),
            "status": "approved",
        })
    return json.dumps({"format": "drama-photo-prompts-v2", "prompt_kind": "photo", "generation_rule": "Process one prompt record at a time and generate only approved records.", "prompts": prompts}, ensure_ascii=False, indent=2) + "\n"


def render_video_prompts(project: ProjectData) -> str:
    prompts = []
    for s in project.scenes:
        if s.video_status != "approved" or not s.video_prompt.strip():
            continue
        prompts.append({
            "prompt_id": s.prompt_id, "duration_seconds": s.duration_seconds, "source_photo_id": s.prompt_id,
            "character_ids": s.characters, "character_profile_files": [f"../Project Plan/Character Profiles/{safe_id(value)}.json" for value in s.characters],
            "positive_prompt": s.video_prompt.strip(), "negative_prompt": s.video_negative_prompt.strip(),
            "negative_prompt_required": bool(s.video_negative_prompt.strip()), "status": "approved",
        })
    return json.dumps({"format": "drama-video-prompts-v2", "prompt_kind": "video", "generation_rule": "Process one prompt record at a time and generate only approved records.", "prompts": prompts}, ensure_ascii=False, indent=2) + "\n"


def render_scene_plan(project: ProjectData) -> str:
    summary = project.project_summary
    lines = [f"PROJECT: {project.project_name or summary.get('title', '')}",
             f"THEME: {summary.get('main_theme', '')}", f"GENRE: {summary.get('genre', '')}",
             f"STYLE: {summary.get('visual_style', '')}", ""]
    for scene in project.scenes:
        subtitles = " / ".join(f"{s.speaker}: {s.text}" for s in scene.subtitles)
        lines.extend([f"<<<SCENE_START {scene.prompt_id}>>>",
                      f"EPISODE: {scene.episode}", f"SCENE: {scene.scene}", f"LOCATION: {scene.location}",
                      f"CHARACTERS: {', '.join(scene.characters)}", f"DURATION: {scene.duration_seconds}s",
                      f"PLOT: {scene.plot}", f"ACTION: {scene.action}", f"SUBTITLES: {subtitles}",
                      f"CAMERA: {scene.shot}", f"CONTINUITY: {scene.continuity}",
                      f"<<<SCENE_END {scene.prompt_id}>>>", ""])
    return "\n".join(lines)


def render_characters(project: ProjectData) -> str:
    blocks = []
    for character in project.characters:
        blocks.append(json.dumps(character, ensure_ascii=False, indent=2))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def extract_marked_prompt(content: str, prompt_id: str, kind: str = "PHOTO") -> str:
    try:
        data = json.loads(content)
        if isinstance(data, dict) and isinstance(data.get("prompts"), list):
            for record in data["prompts"]:
                if record.get("prompt_id") == prompt_id:
                    value = record.get("positive_prompt", "")
                    if not str(value).strip(): raise ValueError(f"Prompt {prompt_id} is empty.")
                    return str(value).strip()
            raise KeyError(f"Prompt record {prompt_id} was not found.")
    except json.JSONDecodeError:
        pass
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
