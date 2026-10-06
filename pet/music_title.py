# -*- coding: utf-8 -*-
"""把「原始标题」洗成「取词查询词（歌名 / 歌手）」。纯函数、零 Qt。

两个来源的标题都需要清洗，而且都不是结构化的：

1. **浏览器媒体会话**（``now_playing.is_browser_session`` 认得的会话）：SMTC 给的
   title 就是网页标题。B 站是「【4K】周杰伦《晴天》官方MV_哔哩哔哩_bilibili」，
   直接拿去搜歌词命中率极低（issue #228 的 B 站侧）。
2. **foobar2000 窗口标题**（issue #228 本体）：foobar 默认不注册 SMTC，只能从
   窗口标题拿曲目信息；而窗口标题是**用户可配置的 titleformat 串**，出厂默认值
   随版本/主题变化，社区常见的有 ``%artist% - %title%``、``[%artist%][ - %title%]``
   等（见 foobar2000 的「显示 → 默认用户界面 → 窗口标题」）。所以解析要么按用户
   填的格式串切，要么不猜。

## 三条硬规则

**只删片段，不改写。** 清洗结果必须是原始输入的**子序列**：不补字、不改字、不
翻译。这样"洗坏"只可能洗成"搜不到"，不可能洗成"搜到别人"。

**空/过短整体退回原文。** 清洗后歌名不足 2 字（或为空）时，连歌手一起退回调用方
传来的原值——这是仓库明文反对白名单式误伤的同一条纪律：宁可这条搜不到，也不能
把用户的歌名换成一个搜得到但不对的东西。

**顺序不可知时不猜。** ``A - B`` 到底是「歌名 - 歌手」还是「歌手 - 歌名」，从字符串
本身看不出来（YouTube 标题是前者、中文曲库是后者，两种都常见）。此时把整条清洗
结果**同时**当作歌名与歌手，让下游自己收敛：

- 取词搜索串是 ``title + " " + artist``（拼接，与顺序无关）；
- 歌手校验 ``music_lyric._name_matches`` 是**子串包含**，而整条标题必然包含歌手名。

于是两种顺序都能命中，且不必押注哪一侧是歌手。押错了的代价不是"搜不到"而是
"把歌名当歌手名去校验"，那会把任意同名的歌贴上来——比搜不到更糟。

## 括号的两套待遇（这是刻意的，不是疏漏）

- ``【】`` / ``[]`` / ``（）`` / ``()``：**删括号、留内容**。它们既可能是质量标签
  （``【4K】``，命中噪声表 → 整组删掉），也可能是歌手/来源前缀（``【周杰伦】``、
  ``【某某UP】``）——留着内容，后者还能被当成歌手，前者也不会因为没登记就丢掉歌名。
- ``「」`` / ``『』``：按需求口径当作**分区标签**，整组（含内容）删掉。

## 噪声词是标签不是内容

``官方MV`` / ``高清`` / ``4K`` / ``无损`` / ``现场版`` / ``Live`` / ``歌词版`` 等一律
按"整段标签"剥除，而不是把关键字从文本里抠掉：抠字会把 ``4K`` 从 ``4K修复`` 里
挖出一个洞，剩下一堆碎片反而更难搜。
"""

from __future__ import annotations

import re

# 清洗结果的可用下限（去空白与分隔符后的字符数）。低于它一律退回原文。
MIN_QUERY_CHARS = 2

# foobar 窗口标题格式串的长度上限：手改配置写进超长正则会把每次采样的匹配代价
# 拖上去，且格式串本来就该是一行。超出部分截断。
FOOBAR_FORMAT_MAX_CHARS = 120

# ascii 站位：紧凑化时去掉的字符（空白 + 各类分隔符/引号）。
_COMPACT_RE = re.compile(r"[\s\-–—|·_/、,，;；:：'\"“”‘’（）()【】\[\]「」『』《》]+")
# 分段分隔符（**不含空白**）：歌手名里常有空格（"Jay Chou"），不能按空白切。
_SPLIT_RE = re.compile(r"[-–—|·/、,，;；:：]+")
# 数"段数"用的分隔符（**含空白**）：判断标题里除了歌名还有没有别的东西。
_TOKEN_RE = re.compile(r"[\s\-–—|·/、,，;；:：]+")
# 至少一个"有意义的字"（字母/数字/CJK 等），防止结果只剩标点。
_WORD_RE = re.compile(r"\w")

# 站点后缀：形如「... - 哔哩哔哩」「..._哔哩哔哩_bilibili」「... - YouTube Music」。
_SITE_TAIL_RE = re.compile(
    r"[\s_\-–—|·]*(?:哔哩哔哩(?:_bilibili)?|bilibili(?:\.com)?|youtube(?:\s+music)?|"
    r"网易云音乐|酷狗音乐|qq音乐|咪咕音乐|抖音|快手|微博|腾讯视频|爱奇艺|优酷|西瓜视频)"
    r"\s*$",
    re.IGNORECASE,
)

# 来源段：``UP主: 某某某`` / ``作者：某某某``。前面的否定后顾是防 "Su**up**er: xxx"
# 这类拉丁词被误切；内容段停在下一个分隔符处。
_SOURCE_SEGMENT_RE = re.compile(
    r"[\s\-–—|·]*(?:(?<![A-Za-z])UP主?|作者|投稿人|投稿者|发布者|搬运)"
    r"\s*[:：]\s*[^\s\-–—|·_]*",
    re.IGNORECASE,
)

# 书名号里的歌名（优先）。中文标题里《》最无歧义。
_SONG_RE = re.compile(r"《([^》]+)》")

# 括号配对：第一组删括号留内容，第二组（「」）整组删掉。
_UNWRAP_PAIRS = (("【", "】"), ("[", "]"), ("（", "）"), ("(", ")"))
_RIPPLE_PAIRS = (("「", "」"), ("『", "』"))

# 噪声标签：**整组**（含括号）删掉，或整段（裸标签）跳过。
#
# exact 只做整串相等匹配（短拉丁标签如 mv/hd，做子串匹配会误伤
# 「[周杰伦MV精选]」这类带内容的括号）；loose 做子串匹配（多字词足够长，
# 误伤面小），专门吃掉「【4K修复】」「【Hi-Res无损】」这种带修饰的写法。
_NOISE_EXACT = frozenset(
    {
        "mv", "hd", "hq", "4k", "8k", "2k", "1080p", "720p", "2160p",
        "flac", "ape", "wav", "mp3", "hires", "m4a",
        "op", "ed", "pv", "mad", "amv", "cover", "b站", "bilibili",
    }
)
_NOISE_LOOSE = (
    "官方mv", "官方视频", "官方音频", "官方版", "official",
    "无损", "高清", "超清", "蓝光", "高音质", "音质", "修复版", "重制版",
    "现场版", "演唱会", "完整版", "纯享", "试听", "母带",
    "歌词版", "动态歌词", "字幕", "中字", "双语", "花絮", "预告", "片头", "片尾",
    "合集", "全集", "翻唱", "纯音乐", "歌曲", "歌单",
    "4k", "8k", "1080p", "720p", "2160p", "hires",
)


def _compact(text: str) -> str:
    """紧凑形式（去空白/分隔符/引号 + 小写），只用于比较与判长短。"""
    return _COMPACT_RE.sub("", str(text or "")).lower()


def _usable(value: str) -> bool:
    """这个查询词能不能用：至少 :data:`MIN_QUERY_CHARS` 个有意义的字、且不是纯数字。"""
    compact = _compact(value)
    return len(compact) >= MIN_QUERY_CHARS and not compact.isdigit()


def _is_noise(text: str) -> bool:
    """该片段是不是"标签"（噪声词）——整段相等或包含长噪声词都算。"""
    compact = _compact(text)
    if not compact:
        return False
    if compact in _NOISE_EXACT:
        return True
    return any(token in compact for token in _NOISE_LOOSE)


def _collapse(text: str) -> str:
    """收敛空白、去掉首尾残留的分隔符（删掉一段后常留下悬空的 " - "）。"""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.strip(" \t-–—|·_/、,，;；:：")
    return re.sub(r"\s+", " ", text).strip()


def _strip_sites(title: str) -> str:
    """反复剥站点后缀（部分标题同时带 "网站名_站点名" 两段）。"""
    text = title
    for _ in range(3):
        stripped = _SITE_TAIL_RE.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return text


def _strip_source_segments(title: str) -> str:
    """剥 ``UP主: xxx`` 这类来源段。"""
    return _SOURCE_SEGMENT_RE.sub(" ", title)


def _strip_brackets(title: str, *, drop_ripple: bool) -> str:
    """括号处理：``【】[]（）()`` 删括号留内容；``「」『』`` 按需整组删掉。

    ``drop_ripple=False`` 时「」也只删括号留内容——用于生成歌手 haystack
    （见 :func:`_haystack_artist`），让被当标签删掉的内容仍能参与歌手校验。
    """
    text = title
    for open_ch, close_ch in _UNWRAP_PAIRS + _RIPPLE_PAIRS:
        drop_content = drop_ripple and (open_ch, close_ch) in _RIPPLE_PAIRS
        out: list[str] = []
        cursor = 0
        while True:
            start = text.find(open_ch, cursor)
            if start < 0:
                out.append(text[cursor:])
                break
            end = text.find(close_ch, start + 1)
            if end < 0:
                # 括号没闭合（残缺标题）：原样留着，别把后半条一起吃掉。
                out.append(text[cursor:])
                break
            out.append(text[cursor:start])
            content = text[start + 1:end]
            if not drop_content and not _is_noise(content):
                out.append(content)
            cursor = end + 1
        text = "".join(out)
    return text


def _strip_chrome(title: str, *, drop_ripple: bool) -> str:
    """站点后缀 → 来源段 → 括号 → 收敛空白。清洗的完整一遍。"""
    text = _strip_source_segments(_strip_sites(title))
    text = _strip_brackets(text, drop_ripple=drop_ripple)
    return _collapse(text)


def _first_song_name(text: str) -> str:
    """取第一个不是标签的书名号内容；没有就返回空串。"""
    for match in _SONG_RE.finditer(text):
        content = match.group(1).strip()
        if content and not _is_noise(content):
            return content
    return ""


def _singer_near_song(text: str, song: str) -> str:
    """书名号外的"最近一段"就是歌手：前面取最后一段、后面取第一段。

    前取"最后"、后取"第一"是因为距离歌名越近越可能是歌手——``【某某UP】周杰伦
    《晴天》【某某UP】`` 这种两头都挂来源段的标题，取到的仍是贴着书名号的歌手。
    逐段跳过噪声标签，于是 ``《晴天》官方MV`` 不会把 "官方MV" 当成歌手。

    定位的是**歌名所在的那对书名号**（不是"第一对"）：歌名可能来自靠后的书名号
    （前面那对是 ``《官方MV》`` 这类噪声段）。定位不到就返回空——不猜。
    """
    found = None
    for match in _SONG_RE.finditer(text):
        if match.group(1).strip() == song:
            found = match
            break
    if found is None:
        return ""
    for chunk, take_last in (
        # 别的书名号段（如前面那对噪声段）不该混进歌手名。
        (_SONG_RE.sub(" ", text[: found.start()]), True),
        (_SONG_RE.sub(" ", text[found.end():]), False),
    ):
        parts = [part.strip() for part in _SPLIT_RE.split(chunk)]
        parts = [part for part in parts if part]
        for part in reversed(parts) if take_last else parts:
            if part and not _is_noise(part):
                return part
    return ""


def _haystack_artist(main: str, haystack: str) -> str:
    """顺序不可知时的歌手位：整条清洗文本，只在这个位置用。

    两条不用的理由（都属于"宁可搜不到"）：

    - 标题只有一个词、且没有任何被剥掉的内容（``晴天``）：它本身不含歌手信息，
      塞进歌手位只会让 ``_name_matches`` 拿歌名当歌手名去匹配；
    - 括号内容被按标签删掉、原文又只剩一段时，同样无助于校验。

    其余情况（有分隔符、或括号内容带来了额外信息）用整条文本，两种顺序都能过
    ``_name_matches`` 的子串校验。
    """
    if _compact(haystack) == _compact(main) and len(_tokens(main)) < 2:
        return ""
    return haystack.strip()


def _tokens(text: str) -> list[str]:
    return [part for part in _TOKEN_RE.split(str(text or "")) if part]


def _pick_side_by_artist(text: str, artist: str) -> str:
    """已知歌手时用它把两段切开：等于歌手名的那段摘出去，剩下的是歌名。"""
    parts = [part.strip() for part in _SPLIT_RE.split(text)]
    parts = [part for part in parts if part]
    if len(parts) != 2:
        return text
    wanted = _compact(artist)
    if not wanted:
        return text
    for index, part in enumerate(parts):
        compact = _compact(part)
        if compact and (compact in wanted or wanted in compact):
            other = parts[1 - index]
            return other if other else text
    return text


def clean_web_title(raw_title: str, raw_artist: str = "") -> tuple[str, str]:
    """网页/浏览器会话标题 → ``(歌名, 歌手)`` 取词查询词。

    ``raw_artist`` 是 SMTC 给的歌手字段（浏览器通常为空）。有值时以它为准，并用
    它把 ``A - B`` 的顺序切开（见 :func:`_pick_side_by_artist`）。

    **清洗失败（结果为空或不足 :data:`MIN_QUERY_CHARS` 字）时原样返回入参**，
    调用方拿到的仍然是能用的东西——只是这一条搜不到，绝不会被改成一个错的歌名。
    """
    original = str(raw_title or "")
    artist_in = str(raw_artist or "").strip()
    if not _usable(original):
        return original, str(raw_artist or "")

    main = _strip_chrome(original, drop_ripple=True)
    song = _first_song_name(main)
    if song:
        title = song
        artist = artist_in or _singer_near_song(main, song)
    else:
        # 没有书名号：先看歌手字段能不能切开顺序，不能就不猜。
        title = _pick_side_by_artist(main, artist_in) if artist_in else main
        artist = artist_in or _haystack_artist(
            main, _strip_chrome(original, drop_ripple=False)
        )

    title = _collapse(title)
    artist = _collapse(artist)
    if not _usable(title):
        return original, str(raw_artist or "")
    return title, artist_in or (artist if _usable(artist) else "")


# ------------------------------------------------------ foobar2000 窗口标题解析

# titleformat 里的字段占位符、条件段方括号。
_FMT_TOKEN_RE = re.compile(r"%([A-Za-z_][A-Za-z0-9_ ]*)%|(\[)|(\])")
# 只有程序名时 foobar 没在播歌（窗口标题格式化后只剩这些）。
_IDLE_RE = re.compile(r"^foobar2000(?:\s+v?[\d.]+)?$", re.IGNORECASE)
# 换个说法：窗口标题里连一个歌名字段都没有时也算没在播。
_TITLE_FIELD = "title"
_ARTIST_FIELD = "artist"


def _lit(text: str) -> str:
    """格式串里的字面文本 → 正则：空白放宽成 ``\\s*``（窗口标题空格数不固定）。"""
    return re.escape(text).replace("\\ ", r"\s*")


def _format_pattern(fmt: str):
    """把 titleformat 串编译成正则，返回 ``(pattern, 分组名集合)``。

    - ``%title%`` / ``%artist%`` → 具名分组；
    - 其它占位符（``%album%`` / ``%length%`` 等）→ 任意通配，不参与取值；
    - ``[...]`` 是 titleformat 的"字段非空才输出"条件段 → ``(?:...)?``；
    - ``'...'`` 是字面量界定符，本身不输出；
    - ``$if(...)`` 这类函数一律按字面文本处理——匹配不上就退回不猜，不会猜错。
    """
    text = fmt.replace("'", "")
    parts: list[str] = []
    fields: set[str] = set()
    cursor = 0
    for match in _FMT_TOKEN_RE.finditer(text):
        parts.append(_lit(text[cursor:match.start()]))
        placeholder, open_bracket, close_bracket = match.groups()
        if open_bracket:
            parts.append("(?:")
        elif close_bracket:
            parts.append(")?")
        else:
            name = placeholder.strip().lower()
            if name in (_TITLE_FIELD, _ARTIST_FIELD) and name not in fields:
                fields.add(name)
                parts.append(f"(?P<{name}>.+?)")
            else:
                parts.append(".+?")
        cursor = match.end()
    parts.append(_lit(text[cursor:]))
    try:
        return re.compile("^" + "".join(parts) + "$"), fields
    except re.error:
        return None, set()


def _parse_with_format(text: str, fmt: str):
    pattern, fields = _format_pattern(fmt)
    if pattern is None or _TITLE_FIELD not in fields:
        # 没有 %title% 的格式串给不出歌名；编译失败的（$if 之类）也不硬来。
        return None
    match = pattern.match(text)
    if match is None:
        return None
    groups = match.groupdict()
    return str(groups.get(_TITLE_FIELD) or ""), str(groups.get(_ARTIST_FIELD) or "")


def _parse_auto(text: str) -> tuple[str, str]:
    """没有格式串时不猜顺序：多段就整条同时作歌名与歌手（见模块 docstring）。"""
    if len(_tokens(text)) >= 2:
        return text, text
    return text, ""


def parse_foobar_title(window_title: str, fmt: str = "") -> tuple[str, str] | None:
    """foobar2000 窗口标题 → ``(歌名, 歌手)``；窗口里没有曲目时返回 ``None``。

    ``fmt`` 是用户在 foobar「显示 → 默认用户界面 → 窗口标题」里配置的 titleformat
    串（配置键 ``foobar_title_format``）。为空 = 自动（不猜顺序）。

    没在播歌时 foobar 的窗口标题只剩程序名或空的占位符，这里按"无曲目"返回
    ``None``——这是**启发式**：窗口标题本身不含播放状态，只能靠"解析不出歌名"
    判断，所以本能力的文档里如实写了这条局限。
    """
    text = re.sub(r"\s+", " ", str(window_title or "")).strip()
    if not _usable(text) or _IDLE_RE.match(text):
        return None

    parsed = None
    if str(fmt or "").strip():
        parsed = _parse_with_format(text, str(fmt)[:FOOBAR_FORMAT_MAX_CHARS])
    if parsed is None:
        parsed = _parse_auto(text)

    title = _collapse(parsed[0])
    artist = _collapse(parsed[1])
    if not _usable(title):
        return None
    return title, artist if _usable(artist) else ""
