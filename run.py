#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
亚马逊运营每日资讯 · 一体化脚本（单文件版）
包含：采集 + 生成网页 + 往期归档，全部在一个文件里。
只需配合 .github/workflows/daily_push.yml 即可每天自动运行。

用法：python3 run.py
"""

import argparse
import json
import re
import html as html_mod
import datetime
import os
import shutil
import xml.etree.ElementTree as ET
import requests
from email.utils import parsedate_to_datetime

UA = {"User-Agent": "Mozilla/5.0 (compatible; AmazonDailyBot/1.0)"}
TIMEOUT = 15
BASE_DATE = datetime.date(2026, 7, 8)
HISTORY_FILE = "archive/history.json"

# ===== 采集源 =====
OFFICIAL_FEEDS = [
    ("About Amazon", "https://www.aboutamazon.com/news/rss"),
    ("Practical Ecommerce", "https://www.practicalecommerce.com/feed"),
]
GN_QUERIES = [
    "亚马逊 卖家 政策", "亚马逊 FBA 费用", "亚马逊 Prime Day 大促",
    "跨境电商 关税 欧盟", "亚马逊 合规 AI 广告",
    "Amazon seller policy update", "Amazon FBA fee changes",
]

COLUMN_RULES = [
    ("物流与供应链", ["关税","清关","物流","海外仓","运价","海运","小包","免税","成本","涨价",
                      "tariff","customs","logistics","fulfillment","shipping","cost"]),
    ("全球合规",     ["合规","认证","隐私","法律","法规","披露","罚款","封号","召回","下架",
                      "compliance","regulation","law","privacy","recall","banned","suspended","fine","effective"]),
    ("政策与费用",   ["费用","费率","佣金","FBA","政策","规则","fee","commission","policy","rule"]),
    ("流量与活动",   ["Prime","大促","广告","流量","算法","促销","prime","sale","deal","advertising","traffic"]),
    ("工具与运营",   ["工具","AI","SOP","助手","canvas","tool","automation","assistant"]),
    ("今日头条",     ["市场","站点","新市场","拉美","巴西","墨西哥",
                      "marketplace","expansion","latin","brazil","mexico"]),
]
HIGH_WORDS = ["生效","新规","新法","税","关税","合规","封号","罚款","暂停","冻结","召回","下架",
              "诉讼","制裁","限制","强制","enforced","tax","tariff","compliance","recall",
              "banned","suspended","fine","law","effective"]
MID_WORDS  = ["费用","FBA","费率","佣金","补贴","大促","Prime","广告","流量",
              "fee","commission","sale","prime","advertising","subsidy"]
IMPACT_TPL = {
    "物流与供应链": "涉及跨境物流/关税成本，可能改变你的履约方案与到货成本。",
    "全球合规":     "涉及合规或法律风险，未及时处理可能影响账户健康或被处罚。",
    "政策与费用":   "涉及平台费用或规则，直接影响毛利与运营动作。",
    "流量与活动":   "涉及站内流量或大促节奏，影响曝光与转化规划。",
    "工具与运营":   "涉及运营工具/效率，可优化日常 SOP。",
    "今日头条":     "涉及市场/站点拓展机会，值得关注布局窗口。",
}
ACTION_TPL = {
    ("物流与供应链", "high"): "本周内核算该路向履约成本，评估转海外仓/本土仓方案。",
    ("全球合规", "high"):     "本周内排查相关合规风险，按新规整改素材/流程。",
    ("政策与费用", "high"):   "用新费率/规则重算主力 SKU 毛利，调整定价与库存。",
    ("流量与活动", "high"):   "据此调整广告/大促排期与预算。",
    ("工具与运营", "low"):    "评估是否将其接入现有运营流程。",
    ("今日头条", "mid"):      "有相关意向的，联系账户经理了解扶持/入驻条件。",
}


def _norm(t): return re.sub(r"[\s\W_]+", "", t.lower())
def _clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return html_mod.unescape(re.sub(r"\s+", " ", s)).strip()

def classify(title):
    t = title.lower()
    for col, words in COLUMN_RULES:
        if any(w.lower() in t for w in words): return col
    return "今日头条"

def level_of(title, column):
    t = title.lower()
    if any(w.lower() in t for w in HIGH_WORDS): return "high"
    if any(w.lower() in t for w in MID_WORDS): return "mid"
    return "low" if column == "工具与运营" else "mid"


def _make_item(title, link, src, pub, desc, origin):
    col = classify(title)
    lvl = level_of(title, col)
    impact = IMPACT_TPL.get(col, "与运营相关，建议关注。")
    action = ACTION_TPL.get((col,lvl)) or ACTION_TPL.get((col,"mid")) or "关注后续官方细则，评估对店铺的影响。"
    tag = "" if origin=="official" else "（via Google News 聚合）"
    return {
        "level":lvl,"column":col,"title":title,
        "tags":[f"#{col}",f"#{src}"],
        "what":f"{title}。{desc}".strip("."),
        "impact":impact,"action":action,
        "source":f"{src}{tag} ｜ {pub}",
        "link":link,"origin":origin,"needs_review":lvl=="high",
    }


# ---- 官方 RSS ----
def fetch_official(name, url, hours):
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=UA); r.raise_for_status()
    except Exception as e:
        print(f"  ! [{name}] 失败: {e}"); return {}
    try: root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  ! [{name}] 解析失败: {e}"); return {}
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    out = {}
    for item in root.iter("item"):
        title = _clean(item.findtext("title",""))
        link = (item.findtext("link","") or "").strip()
        pub = item.findtext("pubDate","")
        desc = _clean(item.findtext("description",""))[:200]
        if not title or not link or len(title)<8: continue
        try:
            dt = parsedate_to_datetime(pub).astimezone(datetime.timezone.utc)
            if dt < cutoff: continue
        except Exception: pass
        out[_norm(title)] = _make_item(title, link, name, pub, desc, "official")
    print(f"  ✓ 官方 [{name}]：{len(out)} 条")
    return out

# ---- Google News ----
def fetch_google(q, hours):
    url = "https://news.google.com/rss/search?q="+requests.utils.quote(q)+"&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=UA); r.raise_for_status()
    except Exception: return {}
    try: root = ET.fromstring(r.content)
    except Exception: return {}
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    out = {}
    for item in root.iter("item"):
        title = _clean(item.findtext("title",""))
        link = (item.findtext("link","") or "").strip()
        pub = item.findtext("pubDate","")
        src = ""
        try: src = item.find("{*}source").text or ""
        except Exception: pass
        if not src:
            try: src = item.find("source").text or ""
            except Exception: pass
        if not src: src = "Google News"
        desc = _clean(item.findtext("description",""))[:200]
        body = title.rsplit(" - ",1)[0] if " - " in title else title
        if len(body)<8: continue
        try:
            dt = parsedate_to_datetime(pub).astimezone(datetime.timezone.utc)
            if dt < cutoff: continue
        except Exception: pass
        key = _norm(body)
        if key not in out:
            out[key] = _make_item(body, link, src, pub, desc, "google")
    return out


def collect(hours, top):
    merged = {}
    for name,url in OFFICIAL_FEEDS: merged.update(fetch_official(name,url,hours))
    for q in GN_QUERIES:
        for k,v in fetch_google(q,hours).items(): merged.setdefault(k,v)
    items = list(merged.values())
    order = {"今日头条":0,"政策与费用":1,"流量与活动":2,"物流与供应链":3,"全球合规":4,"工具与运营":5}
    items.sort(key=lambda x: ({"high":0,"mid":1,"low":2}[x["level"]], order.get(x["column"],9)))
    return items[:top]


# ===== HTML 生成 =====
LV_EMOJI = {"high":"🔴","mid":"🟡","low":"🟢"}

def build_html(data, date_str, issue):
    items = data.get("items",[])
    high = sum(1 for i in items if i.get("level")=="high")
    alert = data.get("alert","")
    alert_html = f'<div class="alert"><b>⚠ 风险提示：</b>{html_mod.escape(alert)}</div>' if alert else ""

    cards = ""
    for i in items:
        lvl_t = LV_EMOJI.get(i["level"],"•"); lvl_c = i["level"]
        tags = " ".join(f'<span class="tag">{html_mod.escape(t)}</span>' for t in i.get("tags",[]))
        tags += f' <span class="tag lvl {lvl_c}">影响：{["高","中","低"][["high","mid","low"].index(lvl_c)]}</span>'
        cards += f"""
  <div class="card {lvl_c}">
    <h2>{i.get('column_icon','•')} {html_mod.escape(i['column'])}｜{html_mod.escape(i['title'])}</h2>
    <div class="tags">{tags}</div>
    <div class="sec"><span class="lab">发生什么</span>{html_mod.escape(i.get('what',''))}</div>
    <div class="sec"><span class="lab">对卖家影响</span>{html_mod.escape(i.get('impact',''))}</div>
    <div class="act">✅ 建议动作：{html_mod.escape(i.get('action',''))}</div>
    <div class="src">来源：{html_mod.escape(i.get('source',''))}</div>
  </div>"""

    checklist = "".join(
        f'<li><span class="box"></span><span>{html_mod.escape(i["action"])}</span></li>'
        for i in items if i.get("action")
    )
    chk = f"""
  <div class="check">
    <h2>✅ 今日行动清单（{date_str[-5:].replace("-","-")}）</h2>
    <ul>{checklist}</ul>
  </div>""" if checklist else ""

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>亚马逊运营每日资讯 · 第 {issue} 期（{date_str}）</title>
<style>
:root{{--o:#FF9900;--n:#232F3E;--bg:#F4F6F8;--h:#E74C3C;--m:#F39C12;--l:#27AE60;--ln:#E3E8EE;--t:#1F2733;--s:#6B7785}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",Segoe UI,sans-serif;background:var(--bg);color:var(--t);line-height:1.65;padding:24px 12px}}
.wrap{{max-width:720px;margin:0 auto}}
.hero{{background:linear-gradient(135deg,var(--n),#37475A);color:#fff;border-radius:16px;padding:24px 22px;box-shadow:0 6px 20px rgba(35,47,62,.18)}}
.hero .kicker{{font-size:12px;letter-spacing:2px;color:var(--o);font-weight:700}}
.hero h1{{font-size:23px;margin:6px 0 10px;font-weight:800}}
.hero .summary{{font-size:14px;color:#D7DEE6}}
.hero .meta{{margin-top:14px;font-size:12px;color:#AEB9C4;display:flex;gap:14px;flex-wrap:wrap}}
.hero .meta b{{color:#fff}}
.alert{{background:#FDECEA;border:1px solid #F5C6C0;border-left:4px solid var(--h);border-radius:10px;padding:12px 14px;margin:18px 0;font-size:13.5px}}.alert b{{color:var(--h)}}
.card{{background:#fff;border:1px solid var(--ln);border-radius:14px;padding:16px 18px;margin:14px 0;position:relative;overflow:hidden;box-shadow:0 2px 8px rgba(35,47,62,.05)}}.card::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:5px}}.card.high::before{{background:var(--h)}}.card.mid::before{{background:var(--m)}}.card.low::before{{background:var(--l)}}.card h2{{font-size:16.5px;font-weight:800;margin-bottom:8px;padding-right:8px}}.tags{{margin:0 0 10px;display:flex;gap:6px;flex-wrap:wrap}}.tag{{font-size:11px;padding:2px 8px;border-radius:20px;background:#EEF2F6;color:var(--s)}}.tag.lvl{{color:#fff;font-weight:700}}.tag.high{{background:var(--h)}}.tag.mid{{background:var(--m)}}.tag.low{{background:var(--l)}}.sec{{margin:8px 0;font-size:13.5px}}.sec .lab{{font-weight:800;color:var(--n);margin-right:6px}}.sec .lab::before{{content:"▎";color:var(--o);margin-right:4px}}.act{{background:#F0F8F1;border-radius:8px;padding:8px 10px;margin-top:8px;font-size:13px}}.src{{font-size:11.5px;color:var(--s);margin-top:9px;border-top:1px dashed var(--ln);padding-top:7px}}.check{{background:#fff;border:1px solid var(--ln);border-radius:14px;padding:16px 18px;margin:14px 0}}.check h2{{font-size:16.5px;font-weight:800;margin-bottom:10px;color:var(--n)}}.check ul{{list-style:none}}.check li{{font-size:13.5px;padding:7px 0;border-bottom:1px dashed var(--ln);display:flex;gap:9px}}.check li:last-child{{border-bottom:none}}.check .box{{width:17px;height:17px;border:2px solid var(--o);border-radius:4px;flex:0 0 auto;margin-top:2px}}.footer{{text-align:center;font-size:11.5px;color:var(--s);margin:22px 0 6px}}.footer b{{color:var(--n)}}a{{color:#FF9900;text-decoration:none}}</style></head><body><div class="wrap">
<div class="hero"><div class="kicker">CROSS-BORDER · AMAZON DAILY</div>
<h1>亚马逊运营每日资讯 · 第 {issue} 期</h1>
<div class="summary">{html_mod.escape(data.get('summary',''))}</div>
<div class="meta">
<span>📅 <b>{date_str}</b></span><span>📌 共 <b>{len(items)}</b> 条</span><span>🔴 高影响 <b>{high}</b> 条</span>
</div></div>
{alert_html}
{cards}
{chk}
<div class="footer"><b>亚马逊运营每日资讯</b> · 每天北京时间 08:00 更新 ｜ <a href="archive.html">📚 往期归档</a><br>由 run.py 自动生成</div></div></body></html>"""


def build_archive(history, latest_date):
    def e(s): return html_mod.escape(str(s))
    try: latest = datetime.date.fromisoformat(latest_date)
    except: latest = datetime.date.today()
    ws = latest - datetime.timedelta(days=6)
    week = [h for h in history if h.get("date") >= ws.isoformat()]
    wt = sum(len(h.get("items",[])) for h in week)
    wh = sum(1 for h in week for i in h.get("items",[]) if i.get("level")=="high")

    rows = "".join(f'<tr><td><a href="{e(h["date"])}.html">{e(h["date"])}</a></td><td>第{h.get("issue","?")}期</td><td>{len(h.get("items",[]))}</td><td>{"🔴"*sum(1 for i in h.get("items",[]) if i.get("level")=="high") or "—"}</td></tr>' for h in reversed(history))
    wl = "".join(f'<li><a href="{e(h["date"])}.html">{e(h["date"])}</a>·{len(h.get("items",[]))}条{" 🔴"+str(sum(1 for i in h.get("items",[]) if i.get("level")=="high")) if any(i.get("level")=="high" for i in h.get("items",[])) else ""}</li>' for h in reversed(week)) or "<li>本周暂无</li>"
    ms = {}; [ms.__setitem__(h["date"][:7], ms.get(h["date"][:7],0)+len(h.get("items",[]))) for h in history]
    mr = "".join(f'<tr><td>{e(m)}</td><td>{n}条</td></tr>' for m,n in sorted(ms.items(),reverse=True))

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>往期归档</title>
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#F4F6F8;color:#1F2733;padding:24px 12px;margin:0}}.wrap{{max-width:760px;margin:0 auto}}
.hero{{background:linear-gradient(135deg,#232F3E,#37475A);color:#fff;border-radius:16px;padding:22px;margin-bottom:10px}}.hero h1{{font-size:22px;margin:0}}.hero .sub{{font-size:13px;color:#D7DEE6;margin-top:6px}}
.card{{background:#fff;border:1px solid #E3E8EE;border-radius:14px;padding:16px 18px;margin:14px 0;box-shadow:0 2px 8px rgba(35,47,62,.05)}}.card h2{{font-size:16px;margin:0 0 10px;color:#232F3E}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}th,td{{text-align:left;padding:8px 6px;border-bottom:1px solid #EEF2F6}}th{{color:#6B7785;font-weight:700}}
a{{color:#2E6FB0;text-decoration:none}}a:hover{{text-decoration:underline}}.pill{{display:inline-block;background:#FF9900;color:#232F3E;font-weight:700;border-radius:20px;padding:2px 10px;font-size:12px}}ul{{margin:6px 0;padding-left:20px}}li{{font-size:13.5px;padding:3px 0}}.footer{{text-align:center;font-size:11.5px;color:#6B7785;margin:18px 0}}
</style></head><body><div class="wrap">
<div class="hero"><h1>📚 亚马逊运营每日资讯 · 往期归档</h1><div class="sub">共{len(history)}期 ｜ 最新:{e(latest_date)} ｜ 每天08:00更新</div></div>
<div class="card"><h2>🔁 本周复盘（{ws.isoformat()}~{latest.isoformat()}）</h2><p style="font-size:13.5px;margin:0 0 8px">近7天共<span class="pill">{wt}条</span> 高影响<span class="pill">{wh}条</span></p><ul>{wl}</ul></div>
<div class="card"><h2>📊 月度汇总</h2><table><tr><th>月份</th><th>条数</th></tr>{mr}</table></div>
<div class="card"><h2>🗂 完整往期列表</h2><table><tr><th>日期</th><th>期数</th><th>条数</th><th>高影响</th></tr>{rows}</table></div>
<div class="footer"><a href="index.html">← 返回最新一期</a></div></div></body></html>"""


def next_issue(today): return max(1,(today-BASE_DATE).days+1)

def load_history():
    if os.path.exists(HISTORY_FILE):
        try: return json.load(open(HISTORY_FILE,encoding="utf-8"))
        except: return []
    return []

def save_history(h):
    os.makedirs("archive",exist_ok=True)
    json.dump(h,open(HISTORY_FILE,"w",encoding="utf-8"),ensure_ascii=False,indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours",type=int,default=48)
    ap.add_argument("--top",type=int,default=8)
    args = ap.parse_args()

    today = datetime.date.today(); ds = today.strftime("%Y-%m-%d")
    issue = next_issue(today)
    print(f"===== 第{issue}期 · {ds} =====")

    # 采集
    items = collect(args.hours,args.top)
    high = sum(1 for i in items if i["level"]=="high")
    official = sum(1 for i in items if i.get("origin")=="official")
    summary = f"自动聚合{len(items)}条（含{official}条官方原文），其中{high}条高影响。" if items else "今日暂无高相关新资讯。"
    alert = "检测到高影响条目，推送前建议编辑核对事实与动作。" if high else ""

    # 写档案
    history = load_history(); record = {"date":ds,"issue":issue,"summary":summary,"alert":alert,"items":items}
    found=False
    for idx,h in enumerate(history):
        if h.get("date")==ds: history[idx]=record; found=True;break
    if not found: history.append(record)
    history.sort(key=lambda x:x.get("date","")); save_history(history)
    print(f"✅ 档案：{len(history)}期（今日{len(items)}条，官方{official}）")

    # 生成全部网页
    os.makedirs("site",exist_ok=True)
    for h in history:
        d={"summary":h["summary"],"alert":h["alert"],"items":h["items"]}
        with open(f"site/{h['date']}.html","w",encoding="utf-8") as f: f.write(build_html(d,h["date"],h["issue"]))
    lh = history[-1]
    ih = build_html({"summary":lh["summary"],"alert":lh["alert"],"items":lh["items"]},ds,issue)
    open("site/index.html","w",encoding="utf-8").write(ih)
    open("site/archive.html","w",encoding="utf-8").write(build_archive(history,ds))
    print(f"✅ 网页：site/index.html + {len(history)}个往期 + archive.html")
    print("===== 完成 =====")


if __name__ == "__main__":
    main()
