from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from .models import ChatMessage, ChatSettings
from .memory_recall import augment_for_turn

def load_character_manifest(root:Path,character_id:str):
    try: raw=json.loads((Path(root)/character_id/'manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError): return {}
    return raw if isinstance(raw,dict) else {}

def load_character_prompt(root:Path,character_id:str):
    chat=load_character_manifest(root,character_id).get('chat',{})
    return str(chat.get('system_prompt','')) if isinstance(chat,dict) else ''

_WEEKDAYS='一二三四五六日'
_TIME_NOTE=('【时间信息】当前时间：{now}。{elapsed}对话记录中用户消息开头的「[日期 时间]」是系统自动附加的发送时间，'
    '用来帮助你感知时间的流逝（例如隔了多久没聊、现在是白天还是深夜、日期是否变了），回复时自然地体现即可；'
    '不要在回复中复述或模仿这种时间标记。')

# 扮演格式引导（spec §「扮演格式引导」定稿文案，逐字照抄，不得改写语义）。
ROLEPLAY_GUIDE = (
    '你在和用户进行场景扮演。\n'
    '① 回复由（动作/神态）和台词组成：动作简短、具体、一次不超过两处，不堆辞藻。\n'
    '② 场景转换、新人物入场、或过了较长时间的节点：用一段旁白描述新场景和在场的人——'
    '每个人给一个外貌特征加一个说话/习惯特征，照着场景卡写，场景卡没有就自己编但前后保持一致。\n'
    '③ 场景里的其他人不是应声虫：他们有自己的小动作和小目的，会插话、会看眼色、会起哄，'
    '但不抢你和用户的戏。\n'
    '④ 绝不替用户做决定，不写用户的动作、台词和心理——用户的（动作）是剧情的一部分，'
    '接着演，不重复不点评。\n'
    '⑤ 场景卡是硬设定：与场景卡冲突时以场景卡为准。'
)


def roleplay_context(scene, cast) -> str:
    """roleplay 引导段 + 非空场景卡；场景/人物都空时只返回引导段。"""
    parts = [ROLEPLAY_GUIDE]
    scene = str(scene or '').strip()
    cast = str(cast or '').strip()
    if scene or cast:
        card = ['【场景卡】']
        if scene:
            card.append('场景：' + scene)
        if cast:
            card.append('在场人物：\n' + cast)
        parts.append('\n'.join(card))
    return '\n\n'.join(parts)


def _local_time(iso):
    """created_at（ISO 字符串，通常为 UTC）→ 本地时区 datetime；无法解析返回 None。"""
    try: dt=datetime.fromisoformat(str(iso))
    except (TypeError,ValueError): return None
    return dt.astimezone()  # naive 视为本地时间

def format_time(dt): return f"{dt:%Y-%m-%d} 周{_WEEKDAYS[dt.weekday()]} {dt:%H:%M}"

def format_elapsed(seconds):
    minutes=int(seconds//60); days,rest=divmod(minutes,1440); hours,mins=divmod(rest,60)
    if days: return f'{days} 天' + (f' {hours} 小时' if hours else '')
    if hours: return f'{hours} 小时' + (f' {mins} 分钟' if mins else '')
    return f'{mins} 分钟'

def stamp_message(message):
    """用户消息前加「[YYYY-MM-DD 周X HH:MM] 」；助手消息不加，避免模型在回复里模仿时间标记。"""
    if message.role!='user': return message.content
    dt=_local_time(message.created_at)
    return f'[{format_time(dt)}] {message.content}' if dt else message.content

def time_context(history,now):
    elapsed=''; last=None
    for m in reversed(history or []):
        last=_local_time(m.created_at)
        if last is not None: break
    if last is not None and (now-last).total_seconds()>=600:  # 10 分钟以内视为连续对话，不额外提示
        elapsed=f'距离上一条消息（{format_time(last)}）已经过去约 {format_elapsed((now-last).total_seconds())}。'
    return _TIME_NOTE.format(now=format_time(now),elapsed=elapsed)

class PromptBuilder:
    def __init__(self,characters_root=None): self.characters_root=Path(characters_root) if characters_root else None
    def effective_system_prompt(self,settings,character_id,role_prompt=None):
        if role_prompt and role_prompt.strip(): return role_prompt.strip()
        if self.characters_root:
            prompt=load_character_prompt(self.characters_root,character_id)
            if prompt.strip(): return prompt.strip()
        return settings.default_system_prompt.strip()
    def build_messages(self,settings,character_id,history,user_text,role_prompt=None,now=None,memory_text=None,
                       roleplay_enabled=None,roleplay_scene=None,roleplay_cast=None):
        """时间感知：历史用户消息前加发送时间标记，system 末尾附当前时间与距上条消息的间隔。
        时间取自已落盘的 ChatMessage.created_at，只在发给模型时附加，不改动会话文件。
        memory_text（user 层快照，pet/chat/memory.injection_text 渲染）追加在
        system 最末、与 time_context 同级；fact/lesson/topic 的按需命中由
        augment_for_turn 用本次真实用户消息补第二段（首轮不命中）。
        None/空 = 不注入，输出与无记忆逐字节一致。
        roleplay_*：每宠场景卡；未显式传入时从 settings 上读同名属性（测试/旧调用方
        直接构造 ChatSettings() 时为默认关）。只在 roleplay_enabled=True 且 persona
        段确实非空时追加——留空场景卡 = 只有格式引导。"""
        now=(now or datetime.now().astimezone()).astimezone()
        if roleplay_enabled is None:
            roleplay_enabled=bool(getattr(settings,'roleplay_enabled',False))
        if roleplay_scene is None:
            roleplay_scene=getattr(settings,'roleplay_scene','')
        if roleplay_cast is None:
            roleplay_cast=getattr(settings,'roleplay_cast','')
        system=self.effective_system_prompt(settings,character_id,role_prompt)
        if roleplay_enabled and system.strip():
            system=(system+'\n\n'+roleplay_context(roleplay_scene,roleplay_cast)).strip()
        system=(system+'\n\n'+time_context(history,now)).strip()
        memory_text=str(memory_text or '').strip()
        if memory_text: system=(system+'\n\n'+memory_text).strip()
        recall_text=augment_for_turn(history,user_text,now=now)
        if recall_text: system=(system+'\n\n'+recall_text).strip()
        trimmed=self.trim_history(history,settings.history_message_limit,settings.history_char_limit)
        return [{'role':'system','content':system},*({'role':m.role,'content':stamp_message(m)} for m in trimmed),{'role':'user','content':user_text.strip()}]
    @staticmethod
    def trim_history(history,message_limit,char_limit):
        result=[]; used=0; limit=max(100,char_limit)
        for m in reversed(history):
            if result and (len(result)>=max(1,message_limit) or used+len(m.content)>limit): break
            if not result and len(m.content)>limit:
                result.append(ChatMessage(m.role,m.content[-limit:],m.created_at,m.message_id)); break
            result.append(m); used+=len(m.content)
        return list(reversed(result))