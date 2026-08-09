from __future__ import annotations

import re
from typing import Any

from .models import ProjectData, Scene

REQUIRED_SUMMARY = ("title", "main_theme", "genre", "tone", "visual_style", "adaptation_direction")


class ProjectValidationError(ValueError):
    pass


def normalize_project(data: dict[str, Any]) -> ProjectData:
    if not isinstance(data, dict):
        raise ProjectValidationError("The provider result is not a project object.")
    if isinstance(data.get("data"), dict) and not data.get("scenes"):
        data = data["data"]
    project = ProjectData.from_dict(data)
    if not project.scenes:
        raise ProjectValidationError("The provider did not create any scenes.")
    project.project_summary = dict(project.project_summary or {})
    for key in REQUIRED_SUMMARY:
        project.project_summary.setdefault(key, "")
    project.characters = [c for c in project.characters if isinstance(c, dict)]
    used_character_ids: set[str] = set()
    for index, character in enumerate(project.characters, 1):
        cid = _id(character.get("character_id")) or f"CHAR_{index:03d}"
        if cid in used_character_ids:
            cid = f"{cid}_{index}"
        character["character_id"] = cid
        used_character_ids.add(cid)
        character.setdefault("name", cid)
        character.setdefault("identity", {})
        character.setdefault("movement_style", {})
        character.setdefault("reference_prompt", "")
    used_scene_ids: set[str] = set()
    for index, scene in enumerate(project.scenes, 1):
        scene.episode = _positive_int(scene.episode, 1)
        scene.scene = _positive_int(scene.scene, index)
        expected = f"E{scene.episode:03d}_S{scene.scene:03d}"
        scene.prompt_id = _id(scene.prompt_id) or expected
        if scene.prompt_id in used_scene_ids:
            scene.prompt_id = expected
        while scene.prompt_id in used_scene_ids:
            scene.prompt_id += "_X"
        used_scene_ids.add(scene.prompt_id)
        scene.duration_seconds = max(2, min(15, _positive_int(scene.duration_seconds, 6)))
        scene.characters = [_id(value) for value in scene.characters if _id(value)]
        scene.status = scene.status if scene.status in ("draft", "reviewed", "approved") else "draft"
        for subtitle in scene.subtitles:
            subtitle.start_seconds = max(0.0, float(subtitle.start_seconds or 0))
            subtitle.end_seconds = min(float(scene.duration_seconds), max(subtitle.start_seconds, float(subtitle.end_seconds or 0)))
    return project


def validate_project(project: ProjectData) -> list[str]:
    warnings: list[str] = []
    ids = {c.get("character_id") for c in project.characters}
    seen: set[str] = set()
    for scene in project.scenes:
        if scene.prompt_id in seen:
            warnings.append(f"Duplicate scene ID: {scene.prompt_id}")
        seen.add(scene.prompt_id)
        missing = [cid for cid in scene.characters if cid not in ids]
        if missing:
            warnings.append(f"{scene.prompt_id}: missing character profiles {', '.join(missing)}")
        if not scene.photo_prompt.strip():
            warnings.append(f"{scene.prompt_id}: empty photo prompt")
        if not scene.video_prompt.strip():
            warnings.append(f"{scene.prompt_id}: empty video prompt")
        if len(scene.photo_prompt.strip()) > 115:
            warnings.append(f"{scene.prompt_id}: photo prompt is {len(scene.photo_prompt.strip())} characters (target about 100)")
    return warnings


def _id(value: Any) -> str:
    return re.sub(r"[^A-Z0-9_-]", "", str(value or "").upper())


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
        return number if number > 0 else default
    except (TypeError, ValueError):
        return default
