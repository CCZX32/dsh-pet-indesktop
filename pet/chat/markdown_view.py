"""AI 回复的 Markdown → Qt 富文本。

用 Qt 自带的 md4c 解析（QTextDocument.setMarkdown，GitHub 方言：表格、删除线、
任务列表、自动链接），不引入第三方依赖。几处取舍：

- ``MarkdownNoHTML``：模型输出里的原始 HTML 按字面显示，不渲染——联网搜索的网页
  内容可能诱导模型输出标签，渲染进 QLabel 没必要也不安全；
- 单个换行保留为换行：标准 Markdown 把单换行并成同一段，但桌宠的回复常用单换行
  分句（与 GitHub 评论 / 主流聊天界面的显示习惯一致）；代码块内不处理；
- 去掉文档级字体，让气泡沿用聊天窗口 QSS 的字体字号；代码换等宽字体并加浅底色。
- 场景扮演的动作段（括号包裹）在 Markdown 解析前先换 token，解析后还原成斜体弱色；
  modern 聊天窗、classic 聊天窗与快速对话气泡**统一走这里渲染**，落盘原文不变。
"""
from __future__ import annotations

import html as html_mod
import re

from PySide6.QtGui import QTextDocument

_FENCE = re.compile(r'^\s{0,3}(```|~~~)')
_BODY_STYLE = re.compile(r'<body style="[^"]*">')
_LINK_COLOR = re.compile(r'(<a href="[^"]*">)<span style=" color:#[0-9a-fA-F]{6};">')
_TABLE_DELIM = re.compile(r'^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$')
_FONT_DECL =re.compile(r"font-family:'[^']*';")
_MONO_STYLED = "font-family:'Consolas','Courier New',monospace; background-color:rgba(127,127,127,0.16);"
# 聊天气泡里标题缩一档，避免 h1 比正文大太多
_HEADING_SIZE = re.compile(r'font-size:(xx-large|x-large);')
_HEADING_MAP = {'xx-large': 'x-large', 'x-large': 'large'}
# 场景扮演的动作段：全角（）或半角 () 整段包裹；允许多行（跨行连续动作段）。
# 括号配对与嵌套层级在 _action_spans 里处理：只允许一层嵌套（外层整体作为动作段），
# 两层以上回退到只取最内层，不递归。
_INLINE_CODE = re.compile(r'`[^`\n]*`')
# 裸 URL：从 http(s):// 起，到空白或中文标点为止。动作段预处理前先圈出来，
# 避免把 URL 里的半角括号当成动作段（那会把 token 塞进 href）。
_URL = re.compile(r'https?://[^\s，。、；：！？（）【】《》〈〉「」『』“”‘’…—～·]+')
_LINK_TARGET_OPEN = re.compile(r'\]\(')
# 斜体 + 弱色：半透明灰在浅色/深色气泡里都比正文弱一档（跟随主题的对比关系，
# 不写死某一种主题的底色）。整段（含括号）一起渲染。
_ACTION_STYLE = 'font-style:italic; color:rgba(128,128,128,0.88);'


def _features():
    f = QTextDocument.MarkdownFeature
    return f(f.MarkdownDialectGitHub.value | f.MarkdownNoHTML.value)


def _is_table_header(lines, i) -> bool:
    return 0 <= i < len(lines) - 1 and '|' in lines[i] and bool(_TABLE_DELIM.match(lines[i + 1]))


def _overlaps(span: tuple[int, int], ranges: list[tuple[int, int]]) -> bool:
    """区间交集非空（端点相接不算相交）。"""
    start, end = span
    return any(start < range_end and range_start < end for range_start, range_end in ranges)


def _fenced_ranges(text: str) -> list[tuple[int, int]]:
    """围栏代码块的字符区间。"""
    ranges: list[tuple[int, int]] = []
    position = 0
    fence_start = None
    for line in text.splitlines(keepends=True):
        if _FENCE.match(line):
            if fence_start is None:
                fence_start = position
            else:
                ranges.append((fence_start, position + len(line)))
                fence_start = None
        position += len(line)
    if fence_start is not None:
        ranges.append((fence_start, len(text)))
    return ranges


def _inline_code_ranges(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _INLINE_CODE.finditer(text)]


def _code_ranges(text: str) -> list[tuple[int, int]]:
    """围栏代码块与行内代码的字符区间（动作段不碰这些地方）。"""
    return _fenced_ranges(text) + _inline_code_ranges(text)


def _link_target_ranges(text: str) -> list[tuple[int, int]]:
    """Markdown 链接目标 ``](...)`` 的字符区间。

    从目标的左括号起按括号配对往后数，URL 里的成对括号（``a_(b)``）也算目标的一部分；
    目标不跨行，扫到行尾仍未闭合就当没有这个链接目标。
    """
    ranges: list[tuple[int, int]] = []
    for match in _LINK_TARGET_OPEN.finditer(text):
        depth = 0
        for index in range(match.end() - 1, len(text)):
            char = text[index]
            if char == '\n':
                break
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    ranges.append((match.start(), index + 1))
                    break
    return ranges


def _url_ranges(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in _URL.finditer(text)]


def _autolink_bare_urls(text: str) -> str:
    """把含括号的裸 URL 包成 ``<...>``：Qt 的自动链接不认括号，不包就整段不成链。

    只动代码区间外、且不在 markdown 链接目标里的裸 URL；目标本身已有解析语法，
    括号配对交给 Markdown。返回用于解析的新文本，原文本不被修改（落盘原文由
    调用方保证）。
    """
    code = _code_ranges(text)
    links = _link_target_ranges(text)
    edits = []
    for match in _URL.finditer(text):
        url = match.group()
        if '(' not in url and ')' not in url:
            continue
        if _overlaps((match.start(), match.end()), code):
            continue
        if _overlaps((match.start(), match.end()), links):
            continue  # 链接目标本身有 markdown 语法，括号配对交给解析器
        if (match.start() > 0 and text[match.start() - 1] == '<'
                and match.end() < len(text) and text[match.end()] == '>'):
            continue  # 已经是 <url> 形式
        edits.append(match)
    if not edits:
        return text
    chunks: list[str] = []
    last = 0
    for match in edits:
        chunks.append(text[last:match.start()])
        chunks.append('<' + match.group() + '>')
        last = match.end()
    chunks.append(text[last:])
    return ''.join(chunks)


def _paren_pairs(text: str, opening: str, closing: str) -> list[tuple[int, int]]:
    """把同一种括号按栈配对，返回所有 ``(start, end)`` 区间（含括号本身）。"""
    stack: list[int] = []
    pairs: list[tuple[int, int]] = []
    for index, char in enumerate(text):
        if char == opening:
            stack.append(index)
        elif char == closing and stack:
            pairs.append((stack.pop(), index + 1))
    return pairs


def _action_spans(text: str) -> list[tuple[int, int]]:
    """动作段候选区间：允许一层括号嵌套，两层以上只取最内层。

    先按括号配对建树，再挑区间：
    - 顶层括号若无孙层（最多一层嵌套），整段作为动作段；
    - 有孙层时外层不取，只取没有子括号的最内层；
    - 已经被外层选中的内层不重复添加。
    """
    pairs = _paren_pairs(text, '（', '）') + _paren_pairs(text, '(', ')')
    pairs = [pair for pair in pairs if pair[1] - pair[0] > 2]  # 空括号不是动作段
    if not pairs:
        return []
    contains = [
        [j for j, inner in enumerate(pairs)
         if j != i and outer[0] <= inner[0] and inner[1] <= outer[1]]
        for i, outer in enumerate(pairs)
    ]
    parents = [
        [j for j, outer in enumerate(pairs)
         if j != i and outer[0] <= pair[0] and pair[1] <= outer[1]]
        for i, pair in enumerate(pairs)
    ]
    selected: list[tuple[int, int]] = []
    for index, pair in enumerate(pairs):
        children = contains[index]
        if parents[index]:
            # 嵌套层：只有最内层（没有子括号）才取，避免两层以上递归。
            if not children:
                selected.append(pair)
        elif any(contains[child] for child in children):
            continue  # 顶层但有两层以上嵌套：外层不取，交给最内层
        else:
            selected.append(pair)
    # 被另一个已选区间完整包住的内层丢弃（一层嵌套时外层已经在里面了）。
    return sorted(
        pair for pair in selected
        if not any(other != pair and other[0] <= pair[0] and pair[1] <= other[1]
                   for other in selected)
    )


def _action_ranges(text: str) -> list[tuple[int, int]]:
    fenced = _fenced_ranges(text)
    inline = _inline_code_ranges(text)
    protected = _link_target_ranges(text) + _url_ranges(text)
    spans: list[tuple[int, int]] = []
    for span in _action_spans(text):
        # 围栏/链接目标/裸 URL：交集非空一律跳过。R2 的判据是起点终点都在区间外，
        # 起于围栏外、止于围栏内的匹配会把围栏符吞进斜体 span。
        if _overlaps(span, fenced) or _overlaps(span, protected):
            continue
        # 行内代码：部分相交（起止点落在代码里或跨边界）跳过；整段动作**完整包住**
        # 一个行内代码时不跳过——R5 要在动作段里把 `x` 还原成等宽样式，而不是把
        # 整个动作段让给 Markdown 解析。
        if any(span[0] < end and start < span[1]
               and not (span[0] <= start and end <= span[1])
               for start, end in inline):
            continue
        spans.append(span)
    return spans


def _tokenize_actions(text: str) -> tuple[str, list[tuple[str, str]]]:
    """把动作段换成占位 token，交给 Markdown 解析后再还原成带样式的富文本。

    不能直接把 ``<span>`` 塞进 Markdown：``MarkdownNoHTML`` 会把它当字面文本。
    先换 token 还让跨行动作段作为一个整体（不会在段落切分时被拆散）。
    """
    spans = _action_ranges(text)
    if not spans:
        return text, []
    prefix = '\u2063AR'
    while prefix in text:  # 用户正文恰好含 token 前缀时继续加长，绝不误还原
        prefix += '\u2063'
    chunks: list[str] = []
    replacements: list[tuple[str, str]] = []
    last = 0
    for index, (start, end) in enumerate(spans):
        token = f'{prefix}{index}\u2063'
        chunks.append(text[last:start])
        chunks.append(token)
        replacements.append((token, text[start:end]))
        last = end
    chunks.append(text[last:])
    return ''.join(chunks), replacements


_ACTION_INLINE = re.compile(r'(`[^`\n]*`|\*\*[^*\n]+\*\*)')


def _render_action_inline(text: str) -> str:
    """动作段内的最小行内解析：`` `x` `` → 等宽 ``<code>``，``**x**`` → ``<strong>``。

    先整体 escape 再认这两个标记，其余字符（包括 HTML）仍按字面显示。
    """
    escaped = html_mod.escape(text, quote=False)
    chunks: list[str] = []
    last = 0
    for match in _ACTION_INLINE.finditer(escaped):
        chunks.append(escaped[last:match.start()])
        token = match.group()
        if token.startswith('`'):
            chunks.append(f'<code style="{_MONO_STYLED}">{token[1:-1]}</code>')
        else:
            chunks.append(f'<strong>{token[2:-2]}</strong>')
        last = match.end()
    chunks.append(escaped[last:])
    return ''.join(chunks).replace('\n', '<br />')


def _restore_actions(html: str, replacements: list[tuple[str, str]]) -> str:
    for token, action in replacements:
        rendered = _render_action_inline(action)
        html = html.replace(token, f'<span style="{_ACTION_STYLE}">{rendered}</span>')
    return html


def preserve_line_breaks(text: str) -> str:
    """段落内的单个换行改成硬换行（行尾两个空格）；围栏代码块内原样保留。

    另外：表格紧跟在文字行后面时补一个空行——md4c 不允许表格打断段落，而模型常写
    「如下：」换行就直接开始画表。
    """
    lines = str(text).split('\n')
    out = []
    in_fence = False
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if _is_table_header(lines, i) and out and out[-1].strip() and '|' not in out[-1]:
            out.append('')
        nxt = lines[i + 1] if i + 1 < len(lines) else ''
        if (line.strip() and nxt.strip() and not _FENCE.match(nxt) and not _is_table_header(lines, i + 1)
                and not line.endswith('  ') and not line.endswith('\\')):
            line += '  '
        out.append(line)
    return '\n'.join(out)


def markdown_to_html(text: str, *, link_color: str = '#3994ff') -> str:
    # 带括号的裸 URL 先包成 <...> 再解析：Qt 的自动链接只认到括号前，不包会断链。
    source = _autolink_bare_urls(str(text))
    source, actions = _tokenize_actions(source)
    doc = QTextDocument()
    doc.setMarkdown(preserve_line_breaks(source), _features())
    html = doc.toHtml()
    head, sep, body = html.partition('<body')
    body = _BODY_STYLE.sub('<body>', sep + body, count=1)
    # 去掉文档级字体后，正文里剩下的 font-family 只来自代码片段（Qt 按平台写入不同的
    # 等宽族名），统一换成等宽字体 + 浅底色
    html = head + _FONT_DECL.sub(_MONO_STYLED, body)
    html = _HEADING_SIZE.sub(lambda m: f'font-size:{_HEADING_MAP[m.group(1)]};', html)
    html = _LINK_COLOR.sub(lambda m: f'{m.group(1)}<span style=" color:{link_color};">', html)
    return _restore_actions(html, actions)
