from __future__ import annotations

import json
from collections.abc import Callable

from .docx_reader import ExtractedNovel, chunk_novel
from .characters import scene_character_context
from .models import ProjectData, Scene
from .providers import ChatProvider, parse_json_response
from .quality import inspect_and_repair_batch, renumber_scenes
from .validation import normalize_project

Progress = Callable[[str], None]

SYSTEM = """你是专业AI竖屏短剧编剧和生成式影像提示词设计师。把小说忠实压缩成节奏紧凑、可逐镜头生成的短剧。普通用户不需要提供创意指令。输出必须是有效JSON，不能使用Markdown。每个scene必须是一台真实摄影机可完成的连续镜头：允许推拉摇移、跟拍、环绕、焦点转移和连续动作，但不能隐藏切镜或摄影机瞬移。时长优先3-6秒，7-8秒可接受，超过8至10秒严格判断，绝不能超过10秒；复杂机位或独立视觉事件必须拆镜。字幕适合短视频。人物ID使用简短大写拉丁字母。照片提示词用精确自然中文，目标约100个汉字，轻微超出可接受；优先写可见信息。视频提示词明确时间内动作、表情、连续运镜和环境运动，并保持身份与场景连续。"""

SCHEMA = {
    "project_summary": {"title": "", "main_theme": "", "secondary_themes": [], "genre": "", "tone": "", "visual_style": "", "time_period": "", "adaptation_direction": ""},
    "characters": [{"character_id": "LIN", "name": "林", "importance": "main", "role": "", "identity": {"age": 26, "gender": "female", "face": "", "eyes": "", "hair": "", "build": "", "distinctive_features": ""}, "default_costume": "", "personality": "", "movement_style": {"posture": "", "walking": "", "gestures": "", "eye_behavior": "", "emotional_motion": "", "speech_behavior": ""}, "identity_anchor": "", "negative_identity_prompt": "", "reference_prompts": [{"order": 1, "reference_type": "face_front", "view": "front", "positive_prompt": "", "negative_prompt": ""}, {"order": 2, "reference_type": "face_three_quarter", "view": "three_quarter", "positive_prompt": "", "negative_prompt": ""}]}],
    "scenes": [{"prompt_id": "E001_S001", "episode": 1, "scene": 1, "plot": "", "location": "", "time_of_day": "", "characters": ["LIN"], "character_state": "", "action": "", "subtitles": [{"speaker": "林", "text": "", "start_seconds": 0.5, "end_seconds": 3.0}], "duration_seconds": 6, "shot": "", "continuity": "", "photo_prompt": "", "photo_negative_prompt": "", "video_prompt": "", "video_negative_prompt": "", "status": "draft"}]
}

PLAN_SCHEMA = {
    "project_summary": SCHEMA["project_summary"],
    "characters": SCHEMA["characters"],
    "episodes": [{"episode": 1, "title": "", "source_sections": [1], "plot_arc": "", "opening_hook": "", "ending_hook": "", "target_scene_count": 12}],
}


def process_novel(novel: ExtractedNovel, provider: ChatProvider, progress: Progress = lambda _: None, cancelled: Callable[[], bool] = lambda: False, rule_text: str = "") -> ProjectData:
    if provider.config.provider == "Demo":
        progress("PROGRESS 100 100 Creating demo scene plan")
        project = demo_project(novel.title)
        for scene in project.scenes:
            scene.photo_prompt = scene.video_prompt = ""
            scene.photo_status = scene.video_status = "missing"
        return project
    summaries: list[dict] = []
    chunks = chunk_novel(novel)
    for index, chunk in enumerate(chunks, 1):
        if cancelled():
            raise InterruptedError("Processing cancelled. No partial provider output was saved.")
        progress(f"PROGRESS {int(index / len(chunks) * 40)} 100 Analyzing novel section {index} of {len(chunks)}")
        prompt = f"""分析以下小说片段，供后续统一改编。输出JSON：
{{"source_section":{index},"plot_events":[""],"characters":[{{"name":"","traits":"","appearance_clues":""}}],"locations":[""],"themes":[""],"visual_clues":[""]}}
只记录文本有依据的重要内容，保留事件顺序。

小说片段：
{chunk}"""
        summaries.append(parse_json_response(provider.complete(SYSTEM, prompt, 5000)))
    progress("PROGRESS 45 100 Planning the complete short drama")
    if cancelled():
        raise InterruptedError("Processing cancelled. No partial provider output was saved.")
    plan_prompt = f"""根据所有片段分析，制定完整AI短剧内部改编计划。不要遗漏主线结局。严格遵循这个JSON结构：
{json.dumps(PLAN_SCHEMA, ensure_ascii=False)}

要求：
1. project_summary融合主题、类型、基调和统一视觉风格。
2. 每个重要或会重复出现的人物必须有稳定可视身份和动作习惯，并生成两个独立、具体的角色参考提示词：第一个严格正面脸，第二个三分之四脸；主要、常驻或服装体型重要的人物再增加全身默认服装参考提示词。每个参考都有positive_prompt和必要的negative_prompt。
3. episodes覆盖全部主线，source_sections引用片段编号，target_scene_count务实控制节奏。
4. 这只是内存中的生成计划，不写入项目文件。

当前有效制作规则：
{rule_text or '使用系统默认规则'}

片段分析：
{json.dumps(summaries, ensure_ascii=False)}"""
    plan = parse_json_response(provider.complete(SYSTEM, plan_prompt, 12000))
    episodes = plan.get("episodes", [])
    if not episodes:
        raise ValueError("The provider did not create an episode plan.")
    all_scenes: list[dict] = []
    prior_tail: list[dict] = []
    for position, episode in enumerate(episodes, 1):
        if cancelled():
            raise InterruptedError("Processing cancelled. No partial provider output was saved.")
        episode_number = int(episode.get("episode") or position)
        progress(f"PROGRESS {50 + int(position / len(episodes) * 45)} 100 Writing episode {position} of {len(episodes)}")
        source_numbers = {int(value) for value in episode.get("source_sections", []) if str(value).isdigit()}
        source_material = [s for s in summaries if int(s.get("source_section", 0)) in source_numbers] or summaries
        scene_prompt = f"""为这一集生成可直接制作的逐镜头JSON。输出结构：{{"scenes":[{json.dumps(SCHEMA['scenes'][0], ensure_ascii=False)}]}}。
项目摘要：{json.dumps(plan.get('project_summary', {}), ensure_ascii=False)}
固定角色：{json.dumps(plan.get('characters', []), ensure_ascii=False)}
本集计划：{json.dumps(episode, ensure_ascii=False)}
本集原文分析：{json.dumps(source_material, ensure_ascii=False)}
上一集最后两镜：{json.dumps(prior_tail, ensure_ascii=False)}

要求：scene的episode全部为{episode_number}，scene从1连续编号，prompt_id格式E{episode_number:03d}_S001；每镜是一台摄影机能连续完成的镜头，优先3-6秒，7-8秒可接受，8-10秒必须有合理的连续动作，绝不超过10秒；允许跟拍开门进入相邻空间和同一目的的连续小动作，不要因“随后、接着、然后”本身拆镜；明确切至、摄影机无法连续到达的新机位、外景大景直接变车内面部特写、独立屏幕特写与反应镜头必须拆分；字段齐全；photo_prompt和video_prompt必须留空；结尾实现ending_hook。
当前有效规则：
{rule_text or '使用系统默认规则'}"""
        batch = parse_json_response(provider.complete(SYSTEM, scene_prompt, 24000))
        scenes = batch.get("scenes", [])
        if not isinstance(scenes, list) or not scenes:
            raise ValueError(f"The provider did not create scenes for episode {episode_number}.")
        candidate_scenes = [Scene.from_dict(scene) for scene in scenes]
        candidate_scenes, _report = inspect_and_repair_batch(candidate_scenes, provider, plan.get("project_summary", {}), plan.get("characters", []), rule_text, progress)
        for scene_position, candidate in enumerate(candidate_scenes, 1):
            scene = candidate.to_dict()
            scene["episode"] = episode_number
            scene["scene"] = scene_position
            scene["prompt_id"] = f"E{episode_number:03d}_S{scene_position:03d}"
            all_scenes.append(scene)
        prior_tail = all_scenes[-2:]
    data = {"project_summary": plan.get("project_summary", {}), "characters": plan.get("characters", []), "scenes": all_scenes}
    try:
        project = normalize_project(data)
    except ValueError as first_error:
        progress("Repairing incomplete provider output")
        repair_prompt = f"""修复下面的项目JSON，使其严格符合给定结构。保留已有剧情，只补齐、纠正字段和唯一ID。只输出有效JSON。
结构：{json.dumps(SCHEMA, ensure_ascii=False)}
校验问题：{first_error}
待修复JSON：{json.dumps(data, ensure_ascii=False)}"""
        repaired = parse_json_response(provider.complete(SYSTEM, repair_prompt, 24000))
        project = normalize_project(repaired)
    for scene in project.scenes:
        # Scene planning and prompt production are separate approval stages.
        scene.photo_prompt = ""
        scene.photo_negative_prompt = ""
        scene.video_prompt = ""
        scene.video_negative_prompt = ""
        scene.photo_status = "missing"
        scene.video_status = "missing"
        scene.status = "draft"
    progress("PROGRESS 100 100 Scene plan ready for review")
    return project


def generate_scene_prompts(project: ProjectData, scene_indexes: list[int], provider: ChatProvider,
                           progress: Progress = lambda _: None,
                           cancelled: Callable[[], bool] = lambda: False) -> dict[int, Scene]:
    results: dict[int, Scene] = {}
    approved = [index for index in scene_indexes if project.scenes[index].status == "approved"]
    if not approved:
        raise ValueError("Approve at least one scene before generating prompts.")
    for position, index in enumerate(approved, 1):
        if cancelled():
            raise InterruptedError("Prompt generation cancelled. Completed prompts were saved.")
        scene = regenerate_scene(project, index, provider, prompts_only=True)
        scene.status = "approved"
        scene.photo_status = "draft"
        scene.video_status = "draft"
        results[index] = scene
        progress(f"PROGRESS {position} {len(approved)} Generated prompts for {scene.prompt_id}")
    return results


def regenerate_scene(project: ProjectData, scene_index: int, provider: ChatProvider, prompts_only: bool = False, rule_text: str = "") -> Scene:
    original = project.scenes[scene_index]
    if provider.config.provider == "Demo":
        scene = Scene.from_dict(original.to_dict())
        if prompts_only:
            scene.photo_prompt = _demo_photo_prompt(scene, project)
            scene.photo_negative_prompt = _demo_photo_negative(scene, project)
            scene.video_prompt = _demo_video_prompt(scene, project)
            scene.video_negative_prompt = _demo_video_negative(scene, project)
        else:
            scene.plot = scene.plot or "重新生成的演示剧情节点"
            scene.action = scene.action or "人物完成一个清晰可见的动作。"
            scene.photo_prompt = _demo_photo_prompt(scene, project)
            scene.photo_negative_prompt = _demo_photo_negative(scene, project)
            scene.video_prompt = _demo_video_prompt(scene, project)
            scene.video_negative_prompt = _demo_video_negative(scene, project)
        scene.status = "draft"
        return scene
    context_characters = scene_character_context(project, original)
    if prompts_only:
        instruction = "只重写photo_prompt、photo_negative_prompt、video_prompt、video_negative_prompt，其他字段逐字保持原值。正向提示词必须写入相关角色档案中的可见身份锚点和本镜状态。照片提示词为精确中文、约100汉字；视频提示词含时间动作、连续运镜和不变项。negative字段仅在有助于防止身份、服装、道具、额外人物、画面质量或镜头错误时填写，否则留空。"
    else:
        instruction = "在保持prompt_id、episode、scene和主线位置不变的前提下重写这个镜头，使它是4-10秒、单一主要动作且可生成。补齐全部字段。"
    prompt = f"""{instruction} 输出JSON对象，字段与输入scene完全一致，不加外层包装。
项目摘要：{json.dumps(project.project_summary, ensure_ascii=False)}
相关角色：{json.dumps(context_characters, ensure_ascii=False)}
前一镜：{json.dumps(project.scenes[scene_index - 1].to_dict(), ensure_ascii=False) if scene_index else '无'}
当前镜：{json.dumps(original.to_dict(), ensure_ascii=False)}
后一镜：{json.dumps(project.scenes[scene_index + 1].to_dict(), ensure_ascii=False) if scene_index + 1 < len(project.scenes) else '无'}
当前有效规则：{rule_text or '使用系统默认规则'}"""
    data = parse_json_response(provider.complete(SYSTEM, prompt, 5000))
    if "scene" in data and isinstance(data["scene"], dict):
        data = data["scene"]
    regenerated = Scene.from_dict(data)
    regenerated.prompt_id = original.prompt_id
    regenerated.episode = original.episode
    regenerated.scene = original.scene
    regenerated.status = "draft"
    if prompts_only:
        preserved = original.to_dict()
        preserved["photo_prompt"] = regenerated.photo_prompt
        preserved["photo_negative_prompt"] = regenerated.photo_negative_prompt
        preserved["video_prompt"] = regenerated.video_prompt
        preserved["video_negative_prompt"] = regenerated.video_negative_prompt
        preserved["status"] = "draft"
        regenerated = Scene.from_dict(preserved)
        regenerated.photo_status = "draft"
        regenerated.video_status = "draft"
    return regenerated


def regenerate_field(project: ProjectData, scene_index: int, field: str, provider: ChatProvider, rule_text: str = "", feedback: str = "") -> str:
    allowed = {"plot", "action", "shot", "continuity", "photo_prompt", "photo_negative_prompt", "video_prompt", "video_negative_prompt"}
    if field not in allowed:
        raise ValueError("This field cannot be regenerated individually.")
    scene = project.scenes[scene_index]
    if provider.config.provider == "Demo":
        if field == "photo_prompt": return _demo_photo_prompt(scene, project)
        if field == "photo_negative_prompt": return _demo_photo_negative(scene, project)
        if field == "video_prompt": return _demo_video_prompt(scene, project)
        if field == "video_negative_prompt": return _demo_video_negative(scene, project)
        defaults = {"plot": "本镜推进关键剧情并留下明确悬念。", "action": "人物完成一个清晰可见的动作。", "shot": "9:16中近景，镜头稳定缓慢推近。", "continuity": "保持人物身份、服装、道具、轴线与光线连续。"}
        return defaults[field]
    characters = scene_character_context(project, scene)
    rules = {
        "photo_prompt": "精确中文，目标约100汉字；包含参考人物的可见身份锚点、服装动作表情、地点时间、镜头构图、光线风格和关键排除项。",
        "photo_negative_prompt": "仅写有助于避免本镜身份漂移、错误服装道具、额外人物、肢体错误、文字水印或风格错误的负向内容；不需要时返回空字符串。",
        "video_prompt": "写清本镜时长内分段动作、表情、运镜、环境运动和必须保持不变的内容。",
        "video_negative_prompt": "仅写有助于避免切镜、摄影机瞬移、身份漂移、动作变形、额外人物或环境突变的负向内容；不需要时返回空字符串。",
        "plot": "一句到两句说明本镜剧情功能和信息变化。",
        "action": "只写本镜时长内可见且可生成的一个主要动作。",
        "shot": "写明竖屏构图、景别、机位、镜头运动和必要镜头语言。",
        "continuity": "写明人物身份、服装、道具、空间、轴线、光线及前后镜衔接。",
    }
    prompt = f"""只重写scene的{field}字段。输出JSON：{{"value":"..."}}。
规则：{rules[field]}
项目摘要：{json.dumps(project.project_summary, ensure_ascii=False)}
相关角色：{json.dumps(characters, ensure_ascii=False)}
完整scene：{json.dumps(scene.to_dict(), ensure_ascii=False)}
当前有效规则：{rule_text or '使用系统默认规则'}
用户反馈：{feedback or '无'}"""
    data = parse_json_response(provider.complete(SYSTEM, prompt, 2000))
    value = data.get("value")
    if not isinstance(value, str) or (not value.strip() and not field.endswith("negative_prompt")):
        raise ValueError("The provider did not return a usable field value.")
    return value.strip()


def regenerate_prompt_kind(project: ProjectData, scene_index: int, kind: str, provider: ChatProvider, rule_text: str = "", feedback: str = "") -> tuple[str, str]:
    if kind not in ("photo", "video"): raise ValueError("Prompt kind must be photo or video.")
    scene = project.scenes[scene_index]
    if provider.config.provider == "Demo":
        return ((_demo_photo_prompt(scene, project), _demo_photo_negative(scene, project)) if kind == "photo" else (_demo_video_prompt(scene, project), _demo_video_negative(scene, project)))
    positive_field, negative_field = f"{kind}_prompt", f"{kind}_negative_prompt"
    prompt = f"""只生成当前一个scene的{kind}正向和可选负向提示词。不要复述scene、角色档案、规则或解释。只输出一个紧凑JSON对象：{{"positive_prompt":"","negative_prompt":"","negative_prompt_required":true}}。
正向提示词必须准确写入角色档案中相关人物的身份锚点、固定特征和本镜服装情绪，不得只写角色ID或姓名。负向提示词仅在能减少身份漂移、错误服装道具、额外人物、肢体画质问题、隐藏切镜或环境突变时填写；不需要时返回空字符串和false。
当前有效规则：{rule_text or '使用系统默认规则'}
用户反馈：{feedback or '无'}
项目摘要：{json.dumps(project.project_summary, ensure_ascii=False)}
角色档案：{json.dumps(scene_character_context(project, scene), ensure_ascii=False)}
scene：{json.dumps(scene.to_dict(), ensure_ascii=False)}"""
    try:
        response = provider.complete(SYSTEM, prompt, 1200)
    except RuntimeError as exc:
        if "truncated" not in str(exc).lower() and "too long" not in str(exc).lower():
            raise
        retry_prompt = prompt + "\n上次输出被截断。本次正向提示词不超过180个中文字符，负向提示词不超过100个中文字符，禁止输出JSON以外的任何内容。"
        response = provider.complete(SYSTEM, retry_prompt, 900)
    data = parse_json_response(response)
    positive = str(data.get("positive_prompt", "")).strip(); negative = str(data.get("negative_prompt", "")).strip()
    if not positive: raise ValueError("The provider did not return a usable positive prompt.")
    return positive, negative


def _demo_photo_prompt(scene: Scene, project: ProjectData | None = None) -> str:
    people = "、".join(scene.characters) or "人物"
    anchors = "；".join(item.get("identity_anchor", "") for item in scene_character_context(project, scene)) if project else ""
    subject = f"{people}（{anchors}）" if anchors else people
    return f"9:16竖屏写实电影剧照，{scene.location or '剧情现场'}{scene.time_of_day}。{subject}{scene.character_state}，{scene.action}。{scene.shot or '中近景'}，戏剧光影，构图明确，面容服装一致，无水印乱码。"


def _demo_video_prompt(scene: Scene, project: ProjectData | None = None) -> str:
    anchors = "；".join(item.get("identity_anchor", "") for item in scene_character_context(project, scene)) if project else ""
    return f"{scene.duration_seconds}秒竖屏镜头。人物身份锚点：{anchors or '保持既定角色身份'}。{scene.action}镜头按{scene.shot or '稳定中近景'}完成，环境保持自然微动。保持人物身份、服装、道具、空间布局与光线连续，不增加人物，不切换场景。"


def _demo_photo_negative(scene: Scene, project: ProjectData) -> str:
    context = scene_character_context(project, scene)
    identity = "，".join(item.get("negative_identity_prompt", "") for item in context if item.get("negative_identity_prompt"))
    return "，".join(part for part in (identity, "多余人物，人物融合，肢体变形，错误服装道具，文字，水印") if part)


def _demo_video_negative(scene: Scene, project: ProjectData) -> str:
    return "切镜，摄影机瞬移，人物身份漂移，服装突变，多余人物，动作变形，背景闪烁"


def demo_project(title: str = "演示小说") -> ProjectData:
    return ProjectData.from_dict({
        "project_summary": {
            "title": title, "main_theme": "在失去与欺骗中重新辨认亲情",
            "secondary_themes": ["记忆", "信任"], "genre": "都市悬疑短剧",
            "tone": "克制、紧张、情绪化", "visual_style": "写实电影感，冷蓝夜色与孤立暖光对比",
            "time_period": "当代", "adaptation_direction": "竖屏快节奏，每集以信息反转收尾"
        },
        "characters": [{
            "character_id": "LIN", "name": "林岚", "importance": "main", "role": "寻找失踪姐姐的记者",
            "identity": {"age": 26, "gender": "female", "face": "椭圆脸、窄下颌", "eyes": "深棕杏眼", "hair": "中分齐肩黑直发", "build": "清瘦", "distinctive_features": "左眼下小泪痣"},
            "default_costume": "灰色针织衫、黑色长裤、银色细项链", "personality": "克制、敏锐",
            "movement_style": {"posture": "肩略内收", "walking": "谨慎轻快", "gestures": "紧张时拇指摩擦食指", "eye_behavior": "先观察再对视", "emotional_motion": "震惊时身体静止，仅眼神和呼吸变化", "speech_behavior": "短句、嘴部动作克制"},
            "identity_anchor": "26岁中国女性，椭圆脸窄下颌，深棕杏眼，左眼下泪痣，中分齐肩黑直发，清瘦",
            "reference_prompts": [
                {"order": 1, "reference_type": "face_front", "view": "front", "positive_prompt": "26岁中国女性，椭圆脸窄下颌，深棕杏眼，左眼下泪痣，中分齐肩黑直发，严格正面中性表情，均匀棚拍光，浅灰纯色背景，写实面部参考图", "negative_prompt": "侧脸，头部倾斜，泪痣缺失，发型变化，夸张表情，文字水印"},
                {"order": 2, "reference_type": "face_three_quarter", "view": "three_quarter", "positive_prompt": "同一26岁中国女性，椭圆脸窄下颌，深棕杏眼，左眼下泪痣，中分齐肩黑直发，左前三分之四中性表情，均匀棚拍光，浅灰纯色背景，写实面部参考图", "negative_prompt": "完全正面，完全侧面，泪痣缺失，发型变化，夸张表情，文字水印"}
            ]
        }],
        "scenes": [{
            "prompt_id": "E001_S001", "episode": 1, "scene": 1,
            "plot": "林岚在深夜收到来自失踪姐姐号码的信息。", "location": "上海公寓厨房", "time_of_day": "雨夜",
            "characters": ["LIN"], "character_state": "疲惫，灰色针织衫被雨水微微打湿", "action": "林岚查看碎屏手机，读到信息后缓慢抬头。",
            "subtitles": [{"speaker": "林岚", "text": "这个号码……是姐姐的。", "start_seconds": 1.2, "end_seconds": 4.2}],
            "duration_seconds": 6, "shot": "50毫米中近景，稳定缓慢推近", "continuity": "手机始终在右手，银色项链可见。",
            "photo_prompt": "9:16竖屏写实电影剧照，上海公寓厨房雨夜。26岁林岚，齐肩黑发、左眼下泪痣，灰色针织衫，右手握碎屏手机，震惊凝视屏幕。50毫米中近景，人物居右，冷蓝月光左侧照入，暖光勾边，浅景深，无旁人水印。",
            "video_prompt": "6秒竖屏镜头。0-2秒林岚低头读手机；2-4秒眼神停住、右手收紧；4-6秒呼吸一滞并缓慢抬头。镜头稳定推近，雨水沿窗流动。保持脸、泪痣、服装、手机、厨房布局与光线不变，不增加人物。",
            "status": "draft"
        }]
    })
