from __future__ import annotations

from typing import Any


IMPORTANT = {"main", "lead", "major", "core", "recurring", "protagonist", "antagonist", "主角", "主要", "反派", "常驻"}


def _text(value: Any) -> str:
    if isinstance(value, list): return "、".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict): return "、".join(str(item).strip() for item in value.values() if str(item).strip())
    return str(value or "").strip()


def identity_anchor(character: dict) -> str:
    identity = character.get("identity", {}) if isinstance(character.get("identity"), dict) else {}
    parts = [
        f"{_text(identity.get('age'))}岁" if _text(identity.get("age")) else "",
        _text(identity.get("gender")), _text(identity.get("face")), _text(identity.get("eyes")),
        _text(identity.get("hair")), _text(identity.get("build")), _text(identity.get("distinctive_features")),
    ]
    return "，".join(part for part in parts if part)


def needs_full_body(character: dict) -> bool:
    importance = _text(character.get("importance")).casefold()
    return importance in IMPORTANT or any(word in importance for word in ("main", "lead", "major", "recurr", "主", "常驻"))


def _face_prompt(character: dict, view: str) -> dict:
    anchor = character["identity_anchor"] or character.get("name") or character["character_id"]
    view_text = "严格正面，双眼直视镜头，头部端正" if view == "front" else "左前方三分之四视角，双眼自然看向镜头，清楚呈现面部立体轮廓"
    kind = "face_front" if view == "front" else "face_three_quarter"
    negative = "错误年龄，错误性别，五官比例变化，发型变化，身份标记缺失，夸张表情，面部遮挡，强烈戏剧光，背景人物，文字，水印"
    if view == "front": negative = "侧脸，头部倾斜，" + negative
    else: negative = "完全正面，完全侧面，" + negative
    return {
        "order": 1 if view == "front" else 2, "reference_type": kind, "view": view,
        "positive_prompt": f"写实电影角色身份参考图，{anchor}，中性放松表情，{view_text}，头肩构图，真实皮肤纹理，85毫米人像镜头，柔和均匀棚拍光，浅灰纯色背景，高精度，无饰景。",
        "negative_prompt": negative,
    }


def _body_prompt(character: dict) -> dict:
    anchor = character["identity_anchor"] or character.get("name") or character["character_id"]
    costume = _text(character.get("default_costume")) or "符合角色身份的默认服装"
    posture = _text((character.get("movement_style") or {}).get("posture")) if isinstance(character.get("movement_style"), dict) else ""
    return {
        "order": 3, "reference_type": "full_body", "view": "full_body_front", "required": True,
        "reason": "Important or recurring character requiring stable physique and costume continuity.",
        "positive_prompt": f"写实电影角色全身参考图，{anchor}，{costume}，{posture or '自然站姿'}，完整头顶到鞋底，正面略带三分之四身体角度，双臂自然下垂，50毫米镜头，柔和均匀棚拍光，浅灰纯色背景，高精度，无饰景。",
        "negative_prompt": "身体裁切，坐姿，强烈透视，错误体型，错误服装，错误鞋履，多余配饰，夸张动作，背景人物，文字，水印",
    }


def ensure_character_profile(character: dict) -> dict:
    profile = dict(character)
    profile["character_id"] = _text(profile.get("character_id")) or "CHARACTER"
    profile.setdefault("name", profile["character_id"])
    profile.setdefault("identity", {})
    profile.setdefault("movement_style", {})
    profile["identity_anchor"] = _text(profile.get("identity_anchor")) or identity_anchor(profile)
    profile.setdefault("fixed_features", [part for part in (profile["identity_anchor"],) if part])
    profile.setdefault("variable_features", ["costume", "emotion", "injury", "weather exposure", "scene props"])
    existing = profile.get("reference_prompts", [])
    by_type = {item.get("reference_type"): item for item in existing if isinstance(item, dict)}
    def specific(kind: str, fallback: dict) -> dict:
        candidate = by_type.get(kind, {})
        if len(_text(candidate.get("positive_prompt"))) < 25: return fallback
        return {**fallback, **candidate, "order": fallback["order"], "reference_type": kind, "view": fallback["view"]}
    prompts = [specific("face_front", _face_prompt(profile, "front")), specific("face_three_quarter", _face_prompt(profile, "three_quarter"))]
    if needs_full_body(profile): prompts.append(specific("full_body", _body_prompt(profile)))
    profile["reference_prompts"] = prompts
    profile["negative_identity_prompt"] = _text(profile.get("negative_identity_prompt")) or "错误年龄，错误性别，五官与发型变化，身份标记缺失，服装连续性错误，人物融合，多余人物"
    profile.pop("reference_prompt", None)
    return profile


def normalize_character_profiles(characters: list[dict]) -> list[dict]:
    return [ensure_character_profile(character) for character in characters if isinstance(character, dict)]


def scene_character_context(project, scene) -> list[dict]:
    character_map = {item.get("character_id"): ensure_character_profile(item) for item in project.characters}
    context = []
    for character_id in scene.characters:
        profile = character_map.get(character_id)
        if not profile: continue
        context.append({
            "character_id": character_id, "name": profile.get("name", ""), "importance": profile.get("importance", ""),
            "identity_anchor": profile.get("identity_anchor", ""), "default_costume": profile.get("default_costume", ""),
            "fixed_features": profile.get("fixed_features", []), "negative_identity_prompt": profile.get("negative_identity_prompt", ""),
            "reference_prompts": profile.get("reference_prompts", []), "scene_state": scene.character_state,
        })
    return context
