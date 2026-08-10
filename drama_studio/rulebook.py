from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .settings import app_data_dir


@dataclass
class Rule:
    rule_id: str
    title: str
    category: str
    text: str
    applies_when: str = ""
    exception: str = ""
    scope: str = "global"
    enabled: bool = True
    built_in: bool = False
    preference: str = "rule"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        allowed = cls.__dataclass_fields__.keys()
        clean = {key: data[key] for key in allowed if key in data}
        clean.setdefault("rule_id", f"USR_{uuid.uuid4().hex[:10].upper()}")
        clean.setdefault("title", "Untitled rule")
        clean.setdefault("category", "General")
        clean.setdefault("text", "")
        return cls(**clean)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_RULES = [
    Rule("BI_CAMERA", "One continuous camera take", "Camera", "Each scene must be generatable as one believable uninterrupted camera take. Continuous pan, tilt, tracking, push-in, pull-back, orbit, focus shift, and following movement are allowed.", built_in=True),
    Rule("BI_CUT", "Split incompatible camera cuts", "Camera", "Split when the shot requires an explicit cut, camera teleportation, independently positioned camera, incompatible exterior/interior viewpoint, or composition reset.", "Cut language or a viewpoint the same camera cannot reach continuously.", "Do not split a physically possible continuous follow shot.", built_in=True),
    Rule("BI_TRANSITION", "Transition words are warnings", "Camera", "Words such as 随后、接着、然后、之后、紧接着 trigger camera-continuity inspection but never cause splitting by themselves.", exception="Connected actions in one continuous take remain together.", built_in=True),
    Rule("BI_BEAT", "One primary visual beat", "Structure", "Prefer one primary visual beat per scene. Connected micro-actions serving the same dramatic purpose may remain together.", built_in=True),
    Rule("BI_DURATION", "Natural short-scene duration", "Duration", "Prefer 3–6 seconds. 7–8 seconds is acceptable. More than 8 and up to 10 seconds requires strict feasibility inspection. More than 10 seconds is prohibited and must be split.", built_in=True),
    Rule("BI_DIALOGUE", "Dialogue must fit", "Dialogue", "Dialogue and reaction time must fit naturally inside the duration; shorten, extend within 10 seconds, or split rather than forcing unnaturally fast speech.", built_in=True),
    Rule("BI_CONTINUITY", "Identity and object continuity", "Continuity", "Preserve character identity, appearance, costume, emotion, props, injuries, location, lighting, weather, and object state across connected scenes.", built_in=True),
    Rule("BI_CHARACTER_ARCHIVE", "Resolve character archives", "Continuity", "Every photo and video prompt must resolve its character IDs and include relevant visible identity anchors, fixed distinguishing features, default costume or scene-specific state; a name or ID alone is insufficient.", built_in=True),
    Rule("BI_CHARACTER_REFS", "Standard character references", "Photo prompt", "Every archived character has separate front-face and three-quarter-face reference prompts in that order. Add a full-body/default-costume reference for main, recurring, or visually important characters.", built_in=True),
    Rule("BI_NEGATIVE", "Optional precise negative prompts", "Prompt", "Generate a concise negative prompt only when it helps prevent identity drift, wrong costume or props, extra people, malformed anatomy, hidden cuts, environmental instability, text, or watermarks. Never exclude a required identity feature.", built_in=True),
    Rule("BI_PHOTO", "One accurate still frame", "Photo prompt", "Photo prompts describe one representative still frame in precise Chinese, approximately 100 Chinese characters, without sequential action, timestamps, hidden cuts, or invented events.", built_in=True),
    Rule("BI_VIDEO", "One continuous video prompt", "Video prompt", "Video prompts match the inspected scene, use realistic timing and flexible continuous camera movement, and add no cut, new location, character, or independent event.", built_in=True),
    Rule("BI_WORD_CONTINUOUS", "Prefer continuous camera language", "Word preference", "Prefer 连续跟拍、镜头缓慢推近、镜头平滑摇向、同一镜头内. Avoid 快速切换镜头、随后切至、画面突然转到 when they conceal a cut.", built_in=True, preference="word"),
]


def rulebook_path() -> Path:
    return app_data_dir() / "rulebook.json"


def load_global_rules(path: str | Path | None = None) -> list[Rule]:
    target = Path(path) if path else rulebook_path()
    overrides: dict[str, dict] = {}
    users: list[Rule] = []
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            overrides = {item.get("rule_id", ""): item for item in data.get("built_in_overrides", [])}
            users = [Rule.from_dict(item) for item in data.get("user_rules", [])]
        except (OSError, ValueError, TypeError):
            pass
    builtins = []
    for default in DEFAULT_RULES:
        merged = default.to_dict()
        merged.update({key: value for key, value in overrides.get(default.rule_id, {}).items() if key in {"title", "category", "enabled", "text", "applies_when", "exception"}})
        builtins.append(Rule.from_dict(merged))
    return builtins + users


def save_global_rules(rules: list[Rule], path: str | Path | None = None) -> None:
    target = Path(path) if path else rulebook_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    defaults = {rule.rule_id: rule for rule in DEFAULT_RULES}
    overrides, users = [], []
    for rule in rules:
        if rule.rule_id in defaults:
            original = defaults[rule.rule_id]
            changed = {"rule_id": rule.rule_id}
            for key in ("title", "category", "enabled", "text", "applies_when", "exception"):
                if getattr(rule, key) != getattr(original, key): changed[key] = getattr(rule, key)
            if len(changed) > 1: overrides.append(changed)
        elif rule.scope == "global":
            users.append(rule.to_dict())
    target.write_text(json.dumps({"format": "drama-rulebook-v1", "built_in_overrides": overrides, "user_rules": users}, ensure_ascii=False, indent=2), encoding="utf-8")


def project_rules(project) -> list[Rule]:
    return [Rule.from_dict(item) for item in getattr(project, "rules", []) if isinstance(item, dict)]


def active_rules(global_rules: list[Rule], project) -> list[Rule]:
    return [rule for rule in [*global_rules, *project_rules(project)] if rule.enabled and rule.text.strip()]


def compile_rules(rules: list[Rule]) -> str:
    lines = []
    for rule in rules:
        line = f"- [{rule.category}] {rule.text.strip()}"
        if rule.exception: line += f" Exception: {rule.exception.strip()}"
        lines.append(line)
    return "\n".join(lines)


def new_rule(title: str, category: str, text: str, applies_when: str = "", exception: str = "", scope: str = "global", preference: str = "rule") -> Rule:
    return Rule(f"USR_{uuid.uuid4().hex[:10].upper()}", title.strip() or "New rule", category.strip() or "General", text.strip(), applies_when.strip(), exception.strip(), scope, True, False, preference)
