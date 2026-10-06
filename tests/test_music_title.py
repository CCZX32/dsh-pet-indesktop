# -*- coding: utf-8 -*-
"""标题 → 取词查询词 的纯函数测试（pet/music_title.py）。

覆盖两条真实用户需求：

- **B 站 / 浏览器媒体会话的网页标题**（issue #228 的 B 站侧）：SMTC 给的 title
  就是网页标题（``【4K】周杰伦《晴天》官方MV_哔哩哔哩_bilibili``），直接拿去
  搜歌词命中率极低。
- **foobar2000 窗口标题**（issue #228 本体）：foobar 默认不注册 SMTC，只能从
  窗口标题拿曲目信息，而那是用户可配置的 titleformat 串。

真值表里的输入都是**真实风格**的标题（B 站/YouTube 的实际形态），不是编出来的
形状。误伤防护单独成组：清洗失败必须**整体退回原始输入**，宁可搜不到不可改坏。
"""

from __future__ import annotations

from pet import music_title


# ------------------------------------------------- 任务一：网页/浏览器标题清洗
#
# 期望值不是"跑出来的"而是按规则推出来的：
# - 书名号内是歌名（优先）；
# - 书名号外的最近一段（书名号前取最后一段、之后取第一段）是歌手；
# - 没有书名号时**不猜顺序**：整条清洗结果同时作歌名与歌手
#   （见 music_title._haystack_artist 的说明）。

WEB_TITLE_CASES = [
    # ---- B 站：书名号 + 站名后缀 ----
    ("【4K】周杰伦《晴天》官方MV_哔哩哔哩_bilibili", ("晴天", "周杰伦")),
    ("周杰伦《晴天》_哔哩哔哩_bilibili", ("晴天", "周杰伦")),
    ("【周杰伦】《晴天》官方MV - 哔哩哔哩", ("晴天", "周杰伦")),
    ("《晴天》- 周杰伦 - 哔哩哔哩", ("晴天", "周杰伦")),
    ("《晴天》 周杰伦 - 哔哩哔哩", ("晴天", "周杰伦")),
    ("【1080P】周杰伦《晴天》【Hi-Res无损】_哔哩哔哩_bilibili", ("晴天", "周杰伦")),
    ("【纯享版】周杰伦《晴天》现场版_哔哩哔哩_bilibili", ("晴天", "周杰伦")),
    ("【歌单】周杰伦《晴天》无损音质_哔哩哔哩_bilibili", ("晴天", "周杰伦")),
    ("【4K修复】周杰伦《晴天》高清MV", ("晴天", "周杰伦")),
    ("《晴天》- Jay Chou - 哔哩哔哩", ("晴天", "Jay Chou")),
    # ---- B 站：没有书名号 → 不猜（整条同时作歌名与歌手 haystack）----
    ("晴天 - 周杰伦_哔哩哔哩_bilibili", ("晴天 - 周杰伦", "晴天 - 周杰伦")),
    ("周杰伦 - 晴天 (Official MV) - 哔哩哔哩", ("周杰伦 - 晴天", "周杰伦 - 晴天")),
    ("周杰伦 - 晴天【官方MV】 - 哔哩哔哩", ("周杰伦 - 晴天", "周杰伦 - 晴天")),
    # ---- 歌名在**第二对**书名号里（前面那对是噪声段）----
    ("《官方MV》周杰伦《晴天》_哔哩哔哩_bilibili", ("晴天", "周杰伦")),
    # ---- B 站：UP 主段 / 分区标签 ----
    (
        "【初音ミク】千本桜「ボカロ」UP主: 某某某 - 哔哩哔哩",
        ("初音ミク千本桜", "初音ミク千本桜ボカロ"),
    ),
    # ---- YouTube / 其它站点 ----
    ("周杰伦 - 晴天 (Official Music Video) - YouTube", ("周杰伦 - 晴天", "周杰伦 - 晴天")),
    ("Jay Chou 周杰倫《晴天》MV - YouTube Music", ("晴天", "Jay Chou 周杰倫")),
]


def test_web_title_truth_table():
    """20 条真实风格标题的清洗真值表（逐条断言，失败即指出哪一条）。"""
    wrong = []
    for raw, expected in WEB_TITLE_CASES:
        got = music_title.clean_web_title(raw, "")
        if got != expected:
            wrong.append(f"{raw!r} -> {got!r}（期望 {expected!r}）")
    assert not wrong, "清洗结果不符：\n" + "\n".join(wrong)


def test_web_title_truth_table_covers_enough_real_shapes():
    """真值表本身要够宽：至少 15 条，且书名号/无书名号两种形态都在。"""
    assert len(WEB_TITLE_CASES) >= 15
    assert any("《" in raw for raw, _ in WEB_TITLE_CASES)
    assert any("《" not in raw for raw, _ in WEB_TITLE_CASES)


def test_web_title_keeps_supplied_artist_and_uses_it_to_pick_the_song_side():
    """SMTC 给了歌手字段时以它为准，并用它把"歌名 - 歌手"的两段切开。

    浏览器会话通常给空 artist，但网页音乐平台（或用户装了媒体扩展）可能给值；
    有值时顺序就不再是未知——把等于歌手名的那一段摘出去，剩下的就是歌名。
    """
    assert music_title.clean_web_title("晴天 - 周杰伦", "周杰伦") == ("晴天", "周杰伦")
    assert music_title.clean_web_title("周杰伦 - 晴天", "周杰伦") == ("晴天", "周杰伦")
    assert music_title.clean_web_title(
        "周杰伦《晴天》官方MV_哔哩哔哩_bilibili", "周杰伦"
    ) == ("晴天", "周杰伦")


# ------------------------------------------------------- 误伤防护（不可改坏）
#
# 清洗只允许"删片段"，不允许改写或补字；结果为空/过短时**整体退回原始输入**。
# 这是仓库明文反对白名单式误伤的同一条纪律：宁可这条搜不到，也不能把用户的
# 歌名改成一个搜得到但不对的东西。


def test_falls_back_when_cleaning_empties_the_title():
    """整条都是站名后缀 → 清洗后为空 → 退回原文（不得返回空串）。"""
    raw = "_哔哩哔哩_bilibili"
    assert music_title.clean_web_title(raw, "") == (raw, "")


def test_falls_back_when_cleaned_song_name_is_too_short():
    """书名号内只剩一个字 → 视为洗坏了 → 退回原文（含原歌手字段）。"""
    raw = "【4K】《晴》_哔哩哔哩_bilibili"
    assert music_title.clean_web_title(raw, "周杰伦") == (raw, "周杰伦")


def test_empty_input_stays_empty():
    assert music_title.clean_web_title("", "") == ("", "")
    assert music_title.clean_web_title("   ", "周杰伦") == ("   ", "周杰伦")


def test_already_clean_title_is_returned_unchanged():
    """本来就干净的标题不得被"顺手"改动——单段且无被剥内容时歌手留空。

    这里刻意不把整条标题塞进歌手位：标题只有一个词时它不含歌手信息，硬塞进去
    会让 ``_name_matches`` 把歌名当成歌手名（标题就叫《周杰伦》时会给任意
    周杰伦的歌贴上歌词，那才是真正的"改坏"）。
    """
    assert music_title.clean_web_title("晴天", "") == ("晴天", "")
    assert music_title.clean_web_title("晴天", "周杰伦") == ("晴天", "周杰伦")


def test_cleaning_never_invents_characters():
    """清洗只做删片段：输出必须是输入的**子序列**（不补字、不改字）。"""
    for raw, _expected in WEB_TITLE_CASES:
        title, artist = music_title.clean_web_title(raw, "")
        assert _is_subsequence(title, raw), f"{title!r} 不是 {raw!r} 的子序列"
        assert _is_subsequence(artist, raw), f"{artist!r} 不是 {raw!r} 的子序列"


def _is_subsequence(part: str, whole: str) -> bool:
    it = iter(whole)
    return all(ch in it for ch in part)


# ------------------------------------------------- 任务二：foobar2000 窗口标题
#
# foobar2000 的窗口标题是用户可配置的 titleformat 串（默认值随版本/主题变化，
# 社区常见写法有 ``%artist% - %title%``、``[%artist%][ - %title%]`` 等）。
# 所以解析器有两条路：用户填了格式串就照它切；没填就**不猜顺序**。


def test_parse_auto_does_not_guess_the_order():
    """未给格式串：``A - B`` 两种顺序都不可确认 → 整条同时作歌名与歌手。"""
    assert music_title.parse_foobar_title("周杰伦 - 晴天") == ("周杰伦 - 晴天", "周杰伦 - 晴天")
    assert music_title.parse_foobar_title("晴天 - 周杰伦") == ("晴天 - 周杰伦", "晴天 - 周杰伦")


def test_parse_auto_single_field():
    """只有一段时歌名就是它，歌手留空（不硬塞 haystack）。"""
    assert music_title.parse_foobar_title("晴天") == ("晴天", "")


def test_parse_with_explicit_format():
    """给了格式串就按它切；两种常见写法都要能对上。"""
    assert music_title.parse_foobar_title(
        "周杰伦 - 晴天", "%artist% - %title%"
    ) == ("晴天", "周杰伦")
    assert music_title.parse_foobar_title(
        "晴天 - 周杰伦", "%title% - %artist%"
    ) == ("晴天", "周杰伦")
    # 实际窗口标题里的多空格/无空格都要能吃下
    assert music_title.parse_foobar_title(
        "晴天-周杰伦", "%title% - %artist%"
    ) == ("晴天", "周杰伦")


def test_parse_with_conditional_brackets():
    """titleformat 的方括号是"字段非空才输出"的条件段，解析必须容得下。

    ``[%artist% - ]%title%`` 是社区里最常见的一种写法：歌手为空时窗口标题只剩
    歌名，两个分支都要能解析。
    """
    assert music_title.parse_foobar_title(
        "周杰伦 - 晴天", "[%artist% - ]%title%"
    ) == ("晴天", "周杰伦")
    assert music_title.parse_foobar_title("晴天", "[%artist% - ]%title%") == ("晴天", "")


def test_parse_format_falls_back_to_auto_when_it_does_not_match():
    """格式串对不上（用户改了 foobar 显示设置）→ 退回不猜，而不是放弃整条。"""
    assert music_title.parse_foobar_title(
        "晴天 - 周杰伦", "%album% / %title%"
    ) == ("晴天 - 周杰伦", "晴天 - 周杰伦")


def test_parse_rejects_idle_and_empty_titles():
    """没在播歌时 foobar 窗口标题只剩程序名/占位符，必须判为"无曲目"。"""
    for idle in ("foobar2000", "foobar2000 v2.24.1", "FooBar2000", "  ", "- "):
        assert music_title.parse_foobar_title(idle) is None, idle


def test_parse_rejects_format_without_title_field():
    """格式串里没有 %title% 就等于拿不到歌名——退回不猜，而不是返回半条。"""
    assert music_title.parse_foobar_title(
        "周杰伦 - 晴天", "%artist% - %album%"
    ) == ("周杰伦 - 晴天", "周杰伦 - 晴天")


def test_parse_strips_whitespace():
    assert music_title.parse_foobar_title("  晴天  ") == ("晴天", "")
