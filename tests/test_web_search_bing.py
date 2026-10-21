# -*- coding: utf-8 -*-
"""免 Key 搜索引擎层新增 Bing：解析 / 分发 / 人机验证报错 / 引擎枚举。

Google 明确**不加**（spec 允许二选一）：2026-10-21 本机实测 Google 搜索页是
纯 JS 外壳——92 KB 页面里 `<h3>` 0 个、`/url?q=` 0 个、命中 `/httpservice/retry
/enablejs`，服务端不再返回可直接解析的结果节点，用正则抓取只能抓到脚本。该决定由
`test_google_is_not_an_engine` 钉住，避免后来者"顺手加一个"。
"""

from __future__ import annotations

from pet.chat import web_search as ws
from pet.chat.models import WEB_SEARCH_ENGINES, WebSearchSettings

_BING_PAGE = (
    '<html><body><ol id="b_results">'
    '<li class="b_ad"><h2><a href="https://ad.example.com/x">广告</a></h2></li>'
    '<li class="b_algo" data-id iid=SERP.1><h2><a target="_blank" href="https://news.example.cn/a.html" h="ID=SERP,1">'
    '国庆<strong>放假</strong>安排</a></h2>'
    '<div class="b_caption"><p class="b_lineclamp2">10 月 1 日至 8 日放假</p></div></li>'
    '<li class="b_algo" data-id iid=SERP.2><h2><a href="https://www.bing.com/aclick?ld=1">Bing 内部跳转</a></h2>'
    '<div class="b_caption"><p>不应出现</p></div></li>'
    '<li class="b_algo" data-id iid=SERP.3><h2><a href="https://example.com/b">第二条 &amp; 结果</a></h2>'
    '<div class="b_caption"><p>摘要 &amp; 内容</p></div></li>'
    '</ol></body></html>'
)


def test_parse_bing_html_extracts_results_and_skips_ads_internal_links():
    results = ws.parse_bing_html(_BING_PAGE, 5)
    assert [(r.title, r.url) for r in results] == [
        ('国庆 放假 安排', 'https://news.example.cn/a.html'),
        ('第二条 & 结果', 'https://example.com/b'),
    ]
    assert results[0].snippet == '10 月 1 日至 8 日放假'
    assert results[1].snippet == '摘要 & 内容'


def test_parse_bing_html_respects_limit():
    assert len(ws.parse_bing_html(_BING_PAGE, 1)) == 1


def test_bing_engine_fetches_and_parses(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _BING_PAGE, 'text/html; charset=utf-8'

    monkeypatch.setattr(ws, '_http_get', fake_get)
    results = ws.search('国庆放假', WebSearchSettings(enabled=True, engine='bing'))
    assert calls and calls[0].startswith('https://www.bing.com/search?')
    assert '%E5%9B%BD%E5%BA%86' in calls[0]
    assert [r.url for r in results][0] == 'https://news.example.cn/a.html'


def test_bing_captcha_is_reported_not_bypassed(monkeypatch):
    import pytest

    monkeypatch.setattr(ws, '_http_get', lambda url, **kw: ('<html><div id="b_captcha"></div></html>', 'text/html'))
    settings = WebSearchSettings(enabled=True, engine='bing')
    with pytest.raises(ws.WebSearchError) as excinfo:
        # 直连引擎层：search() 会先兜底到百度，验证"不许绕过"要看引擎自己的判据
        ws._search_engine('bing', 'x', 5, settings, 15.0, True)
    assert 'Bing 要求人机验证' in str(excinfo.value)


def test_bing_failure_falls_back_to_baidu(monkeypatch):
    pages = {}

    def fake_get(url, **kwargs):
        if 'bing.com' in url:
            raise ws.WebSearchError('HTTP 503')
        pages['baidu'] = True
        return (
            '<div class="result c-container" mu="https://fallback.example.com/x"><h3>备用</h3>'
            '<div class="c-abstract">摘要</div></div>',
            'text/html',
        )

    monkeypatch.setattr(ws, '_http_get', fake_get)
    results = ws.search('x', WebSearchSettings(enabled=True, engine='bing'))
    assert pages.get('baidu') is True
    assert [r.url for r in results] == ['https://fallback.example.com/x']


def test_bing_is_a_selectable_engine():
    assert 'bing' in WEB_SEARCH_ENGINES
    assert 'Bing' in ws.ENGINE_LABELS['bing']
    assert WebSearchSettings.from_dict({'engine': 'bing'}).engine == 'bing'


def test_google_is_not_an_engine():
    assert 'google' not in WEB_SEARCH_ENGINES
    assert WebSearchSettings.from_dict({'engine': 'google'}).engine == 'baidu'
