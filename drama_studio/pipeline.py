from __future__ import annotations

import json
from collections.abc import Callable

from .docx_reader import ExtractedNovel, chunk_novel
from .models import ProjectData, Scene
from .providers import ChatProvider, parse_json_response
from .validation import normalize_project

Progress = Callable[[str], None]

SYSTEM = """你是专业AI竖屏短剧编剧和生成式影像提示词设计师。把小说忠实压缩成节奏紧凑、可逐镜头生成的短剧。普通用户不需要提供创意指令。输出必须是有效JSON，不能使用Markdown。每个scene是一个4-10秒且单独可生成的视频镜头；复杂动作必须拆镜。字幕适合短视频。人物ID使用简短大写拉丁字母。照片提示词用精确自然中文，目标约100个汉字，轻微超出可接受；优先写可见信息：主体身份特征、服装、动作表情、地点时间、构图镜头、光线风格和关键排除项。视频提示词明确时间内动作、表情、镜头和环境运动，并保持身份与场景连续。"""

SCHEMA = {
    "project_summary": {"title": "", "main_theme": "", "secondary_themes": [], "genre": "", "tone": "", "visual_style": "", "time_period": "", "adaptation_direction": ""},
    "characters": [{"character_id": "LIN", "name": "林", "importance": "main", "role": "", "identity": {"age": 26, "gender": "female", "face": "", "eyes": "", "hair": "", "build": "", "distinctive_features": ""}, "default_costume": "", "personality": "", "movement_style": {"posture": "", "walking": "", "gestures": "", "eye_behavior": "", "emotional_motion": "", "speech_behavior": ""}, "reference_prompt": ""}],
    "scenes": [{"prompt_id": "E001_S001", "episode": 1, "scene": 1, "plot": "", "location": "", "time_of_day": "", "characters": ["LIN"], "character_state": "", "action": "", "subtitles": [{"speaker": "林", "text": "", "start_seconds": 0.5, "end_seconds": 3.0}], "duration_seconds": 6, "shot": "", "continuity": "", "photo_prompt": "", "video_prompt": "", "status": "draft"}]
}

PLAN_SCHEMA = {
    "project_summary": SCHEMA["project_summary"],
    "characters": SCHEMA["characters"],
    "episodes": [{"episode": 1, "title": "", "source_sections": [1], "plot_arc": "", "opening_hook": "", "ending_hook": "", "target_scene_count": 12}],
}


def process_novel(novel: ExtractedNovel, provider: ChatProvider, progress: Progress = lambda _: None, cancelled: Callable[[], bool] = lambda: False) -> ProjectData:
    if provider.config.provider == "Demo":
        progress("Creating demo scene plan")
        return demo_project(novel.title)
    summaries: list[dict] = []
    chunks = chunk_novel(novel)
    for index, chunk in enumerate(chunks, 1):
        if cancelled():
            raise InterruptedError("Processing cancelled. No partial provider output was saved.")
        progress(f"Analyzing novel section {index} of {len(chunks)}")
        prompt = f"""分析以下小说片段，供后续统一改编。输出JSON：
{{"source_section":{index},"plot_events":[""],"characters":[{{"name":"","traits":"","appearance_clues":""}}],"locations":[""],"themes":[""],"visual_clues":[""]}}
只记录文本有依据的重要内容，保留事件顺序。

小说片段：
{chunk}"""
        summaries.append(parse_json_response(provider.complete(SYSTEM, prompt, 5000)))
    progress("Planning the complete short drama")
    if cancelled():
        raise InterruptedError("Processing cancelled. No partial provider output was saved.")
    plan_prompt = f"""根据所有片段分析，制定完整AI短剧内部改编计划。不要遗漏主线结局。严格遵循这个JSON结构：
{json.dumps(PLAN_SCHEMA, ensure_ascii=False)}

要求：
1. project_summary融合主题、类型、基调和统一视觉风格。
2. recurring人物各有稳定可视身份、动作习惯和角色参考图提示词。
3. episodes覆盖全部主线，source_sections引用片段编号，target_scene_count务实控制节奏。
4. 这只是内存中的生成计划，不写入项目文件。

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
        progress(f"Writing episode {position} of {len(episodes)}")
        source_numbers = {int(value) for value in episode.get("source_sections", []) if str(value).isdigit()}
        source_material = [s for s in summaries if int(s.get("source_section", 0)) in source_numbers] or summaries
        scene_prompt = f"""为这一集生成可直接制作的逐镜头JSON。输出结构：{{"scenes":[{json.dumps(SCHEMA['scenes'][0], ensure_ascii=False)}]}}。
项目摘要：{json.dumps(plan.get('project_summary', {}), ensure_ascii=False)}
固定角色：{json.dumps(plan.get('characters', []), ensure_ascii=False)}
本集计划：{json.dumps(episode, ensure_ascii=False)}
本集原文分析：{json.dumps(source_material, ensure_ascii=False)}
上一集最后两镜：{json.dumps(prior_tail, ensure_ascii=False)}

要求：scene的episode全部为{episode_number}，scene从1连续编号，prompt_id格式E{episode_number:03d}_S001；每镜4-10秒且只有一个主要可见动作；所有字段齐全；照片提示词精确中文约100汉字；视频提示词写清时序动作、运镜和连续性；结尾实现计划中的ending_hook。"""
        batch = parse_json_response(provider.complete(SYSTEM, scene_prompt, 24000))
        scenes = batch.get("scenes", [])
        if not isinstance(scenes, list) or not scenes:
            raise ValueError(f"The provider did not create scenes for episode {episode_number}.")
        for scene_position, scene in enumerate(scenes, 1):
            scene["episode"] = episode_number
            scene["scene"] = scene_position
            scene["prompt_id"] = f"E{episode_number:03d}_S{scene_position:03d}"
        all_scenes.extend(scenes)
        prior_tail = scenes[-2:]
    data = {"project_summary": plan.get("project_summary", {}), "characters": plan.get("characters", []), "scenes": all_scenes}
    try:
        return normalize_project(data)
    except ValueError as first_error:
        progress("Repairing incomplete provider output")
        repair_prompt = f"""修复下面的项目JSON，使其严格符合给定结构。保留已有剧情，只补齐、纠正字段和唯一ID。只输出有效JSON。
结构：{json.dumps(SCHEMA, ensure_ascii=False)}
校验问题：{first_error}
待修复JSON：{json.dumps(data, ensure_ascii=False)}"""
        repaired = parse_json_response(provider.complete(SYSTEM, repair_prompt, 24000))
        return normalize_project(repaired)


def regenerate_scene(project: ProjectData, scene_index: int, provider: ChatProvider, prompts_only: bool = False) -> Scene:
    original = project.scenes[scene_index]
    if provider.config.provider == "Demo":
        scene = Scene.from_dict(original.to_dict())
        if prompts_only:
            scene.photo_prompt = _demo_photo_prompt(scene)
            scene.video_prompt = _demo_video_prompt(scene)
        else:
            scene.plot = scene.plot or "重新生成的演示剧情节点"
            scene.action = scene.action or "人物完成一个清晰可见的动作。"
            scene.photo_prompt = _demo_photo_prompt(scene)
            scene.video_prompt = _demo_video_prompt(scene)
        scene.status = "draft"
        return scene
    character_map = {c.get("character_id"): c for c in project.characters}
    context_characters = [character_map[cid] for cid in original.characters if cid in character_map]
    if prompts_only:
        instruction = "只重写photo_prompt和video_prompt，其他字段逐字保持原值。照片提示词为精确中文、约100汉字；视频提示词含时间动作、运镜和不变项。"
    else:
        instruction = "在保持prompt_id、episode、scene和主线位置不变的前提下重写这个镜头，使它是4-10秒、单一主要动作且可生成。补齐全部字段。"
    prompt = f"""{instruction} 输出JSON对象，字段与输入scene完全一致，不加外层包装。
项目摘要：{json.dumps(project.project_summary, ensure_ascii=False)}
相关角色：{json.dumps(context_characters, ensure_ascii=False)}
前一镜：{json.dumps(project.scenes[scene_index - 1].to_dict(), ensure_ascii=False) if scene_index else '无'}
当前镜：{json.dumps(original.to_dict(), ensure_ascii=False)}
后一镜：{json.dumps(project.scenes[scene_index + 1].to_dict(), ensure_ascii=False) if scene_index + 1 < len(project.scenes) else '无'}"""
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
        preserved["video_prompt"] = regenerated.video_prompt
        preserved["status"] = "draft"
        regenerated = Scene.from_dict(preserved)
    return regenerated


def regenerate_field(project: ProjectData, scene_index: int, field: str, provider: ChatProvider) -> str:
    allowed = {"plot", "action", "shot", "continuity", "photo_prompt", "video_prompt"}
    if field not in allowed:
        raise ValueError("This field cannot be regenerated individually.")
    scene = project.scenes[scene_index]
    if provider.config.provider == "Demo":
        if field == "photo_prompt": return _demo_photo_prompt(scene)
        if field == "video_prompt": return _demo_video_prompt(scene)
        defaults = {"plot": "本镜推进关键剧情并留下明确悬念。", "action": "人物完成一个清晰可见的动作。", "shot": "9:16中近景，镜头稳定缓慢推近。", "continuity": "保持人物身份、服装、道具、轴线与光线连续。"}
        return defaults[field]
    character_map = {c.get("character_id"): c for c in project.characters}
    characters = [character_map[cid] for cid in scene.characters if cid in character_map]
    rules = {
        "photo_prompt": "精确中文，目标约100汉字；包含参考人物的可见身份锚点、服装动作表情、地点时间、镜头构图、光线风格和关键排除项。",
        "video_prompt": "写清本镜时长内分段动作、表情、运镜、环境运动和必须保持不变的内容。",
        "plot": "一句到两句说明本镜剧情功能和信息变化。",
        "action": "只写本镜时长内可见且可生成的一个主要动作。",
        "shot": "写明竖屏构图、景别、机位、镜头运动和必要镜头语言。",
        "continuity": "写明人物身份、服装、道具、空间、轴线、光线及前后镜衔接。",
    }
    prompt = f"""只重写scene的{field}字段。输出JSON：{{"value":"..."}}。
规则：{rules[field]}
项目摘要：{json.dumps(project.project_summary, ensure_ascii=False)}
相关角色：{json.dumps(characters, ensure_ascii=False)}
完整scene：{json.dumps(scene.to_dict(), ensure_ascii=False)}"""
    data = parse_json_response(provider.complete(SYSTEM, prompt, 2000))
    value = data.get("value")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("The provider did not return a usable field value.")
    return value.strip()


def _demo_photo_prompt(scene: Scene) -> str:
    people = "、".join(scene.characters) or "人物"
    return f"9:16竖屏写实电影剧照，{scene.location or '剧情现场'}{scene.time_of_day}。{people}{scene.character_state}，{scene.action}。{scene.shot or '中近景'}，戏剧光影，构图明确，面容服装一致，无水印乱码。"


def _demo_video_prompt(scene: Scene) -> str:
    return f"{scene.duration_seconds}秒竖屏镜头。{scene.action}镜头按{scene.shot or '稳定中近景'}完成，环境保持自然微动。保持人物身份、服装、道具、空间布局与光线连续，不增加人物，不切换场景。"


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
            "reference_prompt": "26岁中国女性，椭圆脸窄下颌，深棕杏眼，左眼下泪痣，中分齐肩黑直发，清瘦，灰色针织衫，白底写实角色设定图"
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
