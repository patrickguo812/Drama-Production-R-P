from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from .models import ProjectData, Scene
from .providers import ChatProvider, parse_json_response


CUT_TERMS = ("切至", "切回", "再切", "镜头切换", "快速切换", "画面切换", "转场", "反打", "插入特写")
TRANSITION_TERMS = ("随后", "接着", "然后", "之后", "紧接着", "随即", "转而", "下一秒", "与此同时")


@dataclass
class QualityIssue:
    code: str
    severity: str
    message: str


def inspect_scene(scene: Scene) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    combined = " ".join((scene.plot, scene.action, scene.shot, scene.continuity))
    if scene.duration_seconds > 10:
        issues.append(QualityIssue("duration_over_10", "split", "Duration exceeds the absolute 10-second limit."))
    elif scene.duration_seconds > 8:
        issues.append(QualityIssue("duration_review", "warning", "An 8–10-second scene requires a justified continuous take."))
    if any(term in combined for term in CUT_TERMS):
        issues.append(QualityIssue("explicit_cut", "split", "The scene contains explicit camera-cut language."))
    elif any(term in combined for term in TRANSITION_TERMS):
        issues.append(QualityIssue("transition_review", "warning", "Transition wording requires camera-continuity inspection."))
    for field, value in (("location", scene.location), ("plot", scene.plot), ("action", scene.action), ("shot", scene.shot), ("continuity", scene.continuity)):
        if not str(value).strip(): issues.append(QualityIssue(f"missing_{field}", "repair", f"Missing required {field}."))
    if not scene.characters:
        issues.append(QualityIssue("missing_characters", "repair", "Characters must be explicit, even if the list is intentionally empty."))
    for subtitle in scene.subtitles:
        if subtitle.end_seconds > scene.duration_seconds or subtitle.start_seconds < 0 or subtitle.end_seconds < subtitle.start_seconds:
            issues.append(QualityIssue("subtitle_timing", "repair", "Subtitle timing does not fit the scene duration."))
    return issues


def blocking_issues(scene: Scene) -> list[QualityIssue]:
    return [issue for issue in inspect_scene(scene) if issue.severity in ("repair", "split")]


def inspect_prompt(scene: Scene, kind: str) -> list[QualityIssue]:
    value = scene.photo_prompt if kind == "photo" else scene.video_prompt
    issues: list[QualityIssue] = []
    if not value.strip(): return [QualityIssue("empty_prompt", "repair", "Prompt is empty.")]
    if kind == "photo":
        if len(value.strip()) > 150: issues.append(QualityIssue("photo_too_long", "repair", "Photo prompt is too long for the concise still-frame target."))
        if re.search(r"\b\d+\s*[-–—至]\s*\d+\s*(?:s|秒)", value, re.I): issues.append(QualityIssue("photo_timeline", "repair", "A photo prompt cannot contain a video timeline."))
        if any(term in value for term in CUT_TERMS): issues.append(QualityIssue("photo_cut", "repair", "A still-image prompt cannot contain a camera cut."))
    else:
        if any(term in value for term in CUT_TERMS): issues.append(QualityIssue("video_cut", "repair", "Video prompt must describe one continuous take without cuts."))
        if scene.duration_seconds > 10: issues.append(QualityIssue("video_duration", "repair", "Video prompt duration cannot exceed 10 seconds."))
    return issues


def renumber_scenes(scenes: list[Scene]) -> None:
    counters: dict[int, int] = {}
    for scene in scenes:
        counters[scene.episode] = counters.get(scene.episode, 0) + 1
        scene.scene = counters[scene.episode]
        scene.prompt_id = f"E{scene.episode:03d}_S{scene.scene:03d}"


def inspect_and_repair_batch(scenes: list[Scene], provider: ChatProvider, project_summary: dict, characters: list[dict], rules: str,
                             progress: Callable[[str], None] = lambda _message: None) -> tuple[list[Scene], list[dict]]:
    if provider.config.provider == "Demo":
        report = []
        for scene in scenes:
            issues = inspect_scene(scene)
            report.append({"prompt_id": scene.prompt_id, "status": "needs_attention" if blocking_issues(scene) else "warning" if issues else "pass",
                           "reasons": [issue.message for issue in issues]})
        for scene, item in zip(scenes, report):
            scene.quality_status = item["status"]; scene.quality_notes = item["reasons"]
        return scenes, report
    current = scenes
    report: list[dict] = []
    for attempt in range(1, 3):
        progress(f"Inspecting returned scenes · pass {attempt}/2")
        prompt = f"""你是AI视频分镜质量检查器。检查并直接修复下面这一批分镜。输出JSON：{{"scenes":[完整修复后的scene对象],"report":[{{"original_prompt_id":"","status":"pass|repaired|split|needs_attention","reasons":[""]}}]}}。

核心标准：每个scene必须是一个真实摄影机可完成的、不中断的连续镜头。允许推拉摇移、跟拍、环绕、焦点转移、跟随人物开门进入相邻空间和服务同一视觉目的的连续小动作。不要因为“随后、接着、然后”本身拆镜。必须拆分明确切镜、摄影机瞬移、互不兼容的外景/内景机位、独立布置的屏幕特写与人物反应、反打或新的独立事件。
时长优先3–6秒，7–8秒可接受，超过8至10秒严格判断，超过10秒必须拆分。对话必须按自然语速适配。拆分后保留全部剧情并返回所有替代scene。

当前有效规则：
{rules}
项目摘要：{json.dumps(project_summary, ensure_ascii=False)}
角色：{json.dumps(characters, ensure_ascii=False)}
待检查分镜：{json.dumps([scene.to_dict() for scene in current], ensure_ascii=False)}"""
        data = parse_json_response(provider.complete("你是严格但不僵化的AI连续镜头质量检查器。只输出有效JSON。", prompt, 24000))
        returned = data.get("scenes", [])
        if not isinstance(returned, list) or not returned:
            raise ValueError("The quality checker did not return inspected scenes.")
        current = [Scene.from_dict(item) for item in returned]
        report = data.get("report", []) if isinstance(data.get("report"), list) else []
        if not any(blocking_issues(scene) for scene in current): break
    report_by_id = {str(item.get("original_prompt_id") or item.get("prompt_id") or ""): item for item in report if isinstance(item, dict)}
    for scene in current:
        issues = inspect_scene(scene); blocking = [issue for issue in issues if issue.severity in ("repair", "split")]
        provider_item = report_by_id.get(scene.prompt_id, {})
        provider_status = provider_item.get("status", "")
        scene.quality_status = "needs_attention" if blocking or provider_status == "needs_attention" else "warning" if issues else "pass"
        scene.quality_notes = [issue.message for issue in issues] or [str(value) for value in provider_item.get("reasons", [])]
    return current, report


def analyze_feedback(provider: ChatProvider, feedback: str, context: str, rules: str, modification: str = "") -> dict:
    if provider.config.provider == "Demo":
        text = feedback.strip()
        category = "Camera" if any(word in text for word in ("镜头", "切", "camera", "shot")) else "General"
        return {"interpretation": text, "title": "User feedback rule", "category": category,
                "rule": text, "applies_when": "When the described production situation occurs.",
                "exception": "Keep the scene when one camera can perform it continuously.", "recommended_scope": "global"}
    prompt = f"""把用户反馈转换为一条清晰、可复用但不过度僵化的AI短剧检查规则。输出JSON：
{{"interpretation":"","title":"","category":"Camera|Structure|Duration|Dialogue|Continuity|Photo prompt|Video prompt|Word preference|General","rule":"","applies_when":"","exception":"","recommended_scope":"global|project"}}
必须围绕用户真实意图，写出适用情况和不适用例外。不要执行修改。
当前规则：{rules}
关联内容：{context or '无'}
原始反馈：{feedback}
用户对上一版规则的修改意见：{modification or '无'}"""
    return parse_json_response(provider.complete("你是本地制作规则编辑代理。只输出有效JSON。", prompt, 4000))


def apply_scene_feedback(project: ProjectData, scene_index: int, feedback: str, provider: ChatProvider, rules: str) -> tuple[list[Scene], list[dict]]:
    original = project.scenes[scene_index]
    if provider.config.provider == "Demo":
        first = Scene.from_dict(original.to_dict()); second = Scene.from_dict(original.to_dict())
        first.plot = f"{original.plot}（第一连续镜头）"; first.action = original.action; first.duration_seconds = min(6, original.duration_seconds)
        second.plot = f"{original.plot}（第二连续镜头）"; second.action = "承接上一镜完成反馈要求的第二个连续视觉部分。"; second.duration_seconds = min(6, original.duration_seconds)
        first.shot = "第一部分使用一个连续机位完成，不切镜。"; second.shot = "第二部分使用一个独立连续机位完成，不切镜。"
        for scene in (first, second):
            scene.photo_prompt = scene.video_prompt = ""; scene.photo_status = scene.video_status = "missing"; scene.status = "draft"
        return [first, second], [{"status": "split", "reasons": [feedback]}]
    surrounding = project.scenes[max(0, scene_index - 1):scene_index + 2]
    prompt = f"""根据用户反馈修复或拆分当前scene。输出JSON：{{"scenes":[完整scene对象],"report":[{{"status":"repaired|split","reasons":[""]}}]}}。
保留剧情位置和全部重要信息。每个返回scene是一台真实摄影机可完成的连续镜头。时长优先3–6秒，任何scene不得超过10秒。photo_prompt和video_prompt留空。
有效规则：{rules}
项目摘要：{json.dumps(project.project_summary, ensure_ascii=False)}
角色：{json.dumps(project.characters, ensure_ascii=False)}
相邻上下文：{json.dumps([s.to_dict() for s in surrounding], ensure_ascii=False)}
当前scene：{json.dumps(original.to_dict(), ensure_ascii=False)}
用户反馈：{feedback}"""
    data = parse_json_response(provider.complete("你是AI短剧分镜修复代理。只输出有效JSON。", prompt, 12000))
    returned = data.get("scenes", [])
    if not isinstance(returned, list) or not returned: raise ValueError("The API did not return replacement scenes.")
    scenes = [Scene.from_dict(item) for item in returned]
    for scene in scenes:
        scene.episode = original.episode; scene.photo_prompt = scene.video_prompt = ""
        scene.photo_status = scene.video_status = "missing"; scene.status = "draft"
    inspected, checker_report = inspect_and_repair_batch(scenes, provider, project.project_summary, project.characters, rules)
    return inspected, [*(data.get("report", []) if isinstance(data.get("report"), list) else []), *checker_report]


def estimate_speaking_seconds(text: str) -> float:
    compact = re.sub(r"\s+", "", text or "")
    return len(compact) / 4.0
