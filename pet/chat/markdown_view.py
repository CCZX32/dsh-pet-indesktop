"""AI 回复的 Markdown → Qt 富文本。

用 Qt 自带的 md4c 解析（QTextDocument.setMarkdown，GitHub 方言：表格、删除线、
任务列表、自动链接），不引入第三方依赖。几处取舍：

- ``MarkdownNoHTML``：模型输出里的原始 HTML 按字面显示，不渲染——联网搜索的网页
  内容可能诱导模型输出标签，渲染进 QLabel 没必要也不安全；
- 单个换行保留为换行：标准 Markdown 把单换行并成同一段，但桌宠的回复常用单换行
  分句（与 GitHub 评论 / 主流聊天界面的显示习惯一致）；代码块内不处理；
- 去掉文档级字体，让气泡沿用聊天窗口 QSS 的字体字号；代码换等宽字体并加浅底色。
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
_ACTION_SEGMENT = re.compile(r'（[^（）]+）|\([^()]+\)')
_INLINE_CODE = re.compile(r'`[^`\n]*`')
# 斜体 + 弱色：半透明灰在浅色/深色气泡里都比正文弱一档（跟随主题的对比关系，
# 不写死某一种主题的底色）。整段（含括号）一起渲染。
_ACTION_STYLE = 'font-style:italic; color:rgba(128,128,128,0.88);'


def _features():
    f = QTextDocument.MarkdownFeature
    return f(f.MarkdownDialectGitHub.value | f.MarkdownNoHTML.value)


def _is_table_header(lines, i) -> bool:
    return 0 <= i < len(lines) - 1 and '|' in lines[i] and bool(_TABLE_DELIM.match(lines[i + 1]))


def _code_ranges(text: str) -> list[tuple[int, int]]:
    """围栏代码块与行内代码的字符区间（动作段不碰这些地方）。"""
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
    ranges.extend((match.start(), match.end()) for match in _INLINE_CODE.finditer(text))
    return ranges


def _action_ranges(text: str) -> list[tuple[int, int]]:
    code = _code_ranges(text)
    return [
        (match.start(), match.end())
        for match in _ACTION_SEGMENT.finditer(text)
        if not any(start <= match.start() < end for start, end in code)
    ]


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


def _restore_actions(html: str, replacements: list[tuple[str, str]]) -> str:
    for token, action in replacements:
        rendered = html_mod.escape(action, quote=False).replace('\n', '<br />')
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
    source, actions = _tokenize_actions(str(text))
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
