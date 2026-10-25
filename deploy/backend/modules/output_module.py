"""⑥ 输出模块：查证卡渲染数据与导出（HTML 片段，可转图片）。"""
from __future__ import annotations
import html
def render_card_html(card: dict) -> str:
    """把查证卡渲染为可导出的独立 HTML（用于前端截图导出）。"""
    e = html.escape
    v = card["verdict"]
    support_rows = "".join(
        f"<li><b>{e(i['point'])}</b><br><span class='src'>来源：{e(i['source_title'])} · {e(i['source_domain'])}</span></li>"
        for i in card["evidence"]["support"]
    ) or "<li class='empty'>未发现支持证据</li>"
    refute_rows = "".join(
        f"<li><b>{e(i['point'])}</b><br><span class='src'>来源：{e(i['source_title'])} · {e(i['source_domain'])}</span></li>"
        for i in card["evidence"]["refute"]
    ) or "<li class='empty'>未发现矛盾证据</li>"
    source_rows = "".join(
        f"<li><a href='{e(s['url'])}'>{e(s['title'])}</a> "
        f"<span class='tag'>{e(s['credibility_label'])}</span> "
        f"<span class='src'>{e(s['domain'])} · {e(s['published_at'])}</span></li>"
        for s in card["sources"]
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>查证卡 {e(card['card_id'])}</title>
<style>
body{{background:#070B14;color:#E6F1FF;font-family:system-ui,'Microsoft YaHei',sans-serif;padding:24px}}
.card{{max-width:760px;margin:0 auto;background:rgba(18,26,43,.92);border:1px solid rgba(0,229,192,.35);border-radius:16px;padding:24px}}
.verdict{{font-size:28px;font-weight:700;color:{v['color']}}}
h3{{color:#00E5C0;font-size:14px;letter-spacing:2px;margin:18px 0 8px}}
ul{{padding-left:18px;line-height:1.8}}
.src{{color:#7A8CA6;font-size:12px}}
.tag{{background:rgba(0,229,192,.15);color:#00E5C0;font-size:11px;padding:1px 6px;border-radius:4px}}
a{{color:#7FD8FF}}
.empty{{color:#7A8CA6}}
</style></head><body><div class="card">
<div class="verdict">{e(v['label'])} · 置信度 {v['confidence']}%</div>
<p>{e(card['input_text'])}</p>
<h3>结论说明</h3><p>{e(v['summary'])}</p>
<h3>支持依据</h3><ul>{support_rows}</ul>
<h3>矛盾证据</h3><ul>{refute_rows}</ul>
<h3>来源清单</h3><ul>{source_rows}</ul>
<h3>核查信息</h3>
<p class="src">卡片编号 {e(card['card_id'])} · 核查时间 {e(card['created_at_display'])}</p>
</div></body></html>"""