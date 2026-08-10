from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Subtitle:
    speaker: str = ""
    text: str = ""
    start_seconds: float = 0.0
    end_seconds: float = 0.0


@dataclass
class Scene:
    prompt_id: str
    episode: int
    scene: int
    plot: str = ""
    location: str = ""
    time_of_day: str = ""
    characters: list[str] = field(default_factory=list)
    character_state: str = ""
    action: str = ""
    subtitles: list[Subtitle] = field(default_factory=list)
    duration_seconds: int = 6
    shot: str = ""
    continuity: str = ""
    photo_prompt: str = ""
    video_prompt: str = ""
    status: str = "draft"
    photo_status: str = "missing"
    video_status: str = "missing"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        clean = dict(data)
        clean["subtitles"] = [Subtitle(**s) for s in clean.get("subtitles", [])]
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in clean.items() if k in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectData:
    project_name: str = ""
    source_document: str = ""
    project_summary: dict[str, Any] = field(default_factory=dict)
    characters: list[dict[str, Any]] = field(default_factory=list)
    scenes: list[Scene] = field(default_factory=list)
    processing: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectData":
        return cls(
            project_name=data.get("project_name", ""),
            source_document=data.get("source_document", ""),
            project_summary=data.get("project_summary", {}),
            characters=data.get("characters", []),
            scenes=[Scene.from_dict(s) for s in data.get("scenes", [])],
            processing=data.get("processing", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "source_document": self.source_document,
            "project_summary": self.project_summary,
            "characters": self.characters,
            "scenes": [s.to_dict() for s in self.scenes],
            "processing": self.processing,
        }
