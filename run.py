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
        # 来源链接：有原文直链则可点击，Google News 聚合也带链接
        link = i.get("link","")
        src_text = i.get("source","")
        if link:
            src_html = f'来源：<a href="{html_mod.escape(link)}" target="_blank" rel="noopener" class="src-link">{html_mod.escape(src_text)} 🔗</a>'
        else:
            src_html = f'来源：{html_mod.escape(src_text)}'
        cards += f"""
  <div class="card {lvl_c}">
    <h2>{i.get('column_icon','•')} {html_mod.escape(i['column'])}｜{html_mod.escape(i['title'])}</h2>
    <div class="tags">{tags}</div>
    <div class="sec"><span class="lab">发生什么</span>{html_mod.escape(i.get('what',''))}</div>
    <div class="sec"><span class="lab">对卖家影响</span>{html_mod.escape(i.get('impact',''))}</div>
    <div class="act">✅ 建议动作：{html_mod.escape(i.get('action',''))}</div>
    <div class="src">{src_html}</div>
  </div>"""

    # 行动清单：去重（同一条动作只出现一次），并附带来源链接
    seen_actions = set()
    unique_checks = []
    for i in items:
        act = (i.get("action") or "").strip()
        if not act or act in seen_actions:
            continue
        seen_actions.add(act)
        link = i.get("link","")
        title_short = (i.get("title") or "")[:35]
        if link:
            unique_checks.append(
                f'<li><span class="box"></span><span>{html_mod.escape(act)} '
                f'<small>(<a href="{html_mod.escape(link)}" target="_blank" rel="noopener">'
                f'{html_mod.escape(title_short)}… 🔗</a>)</small></span></li>')
        else:
            unique_checks.append(f'<li><span class="box"></span><span>{html_mod.escape(act)}</span></li>')

    checklist = "".join(unique_checks)
    chk = f"""
  <div class="check">
    <h2>✅ 今日行动清单（{date_str[-5:].replace("-","-")}）· 共 {len(seen_actions)} 项独立行动</h2>
    <ul>{checklist}</ul>
  </div>""" if checklist else ""

    return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>亚马逊运营每日资讯 · 第 {issue} 期（{date_str}）</title>
<style>
:root{{--o:#FF9900;--n:#232F3E;--bg:#F4F6F8;--h:#E74C3C;--m:#F39C12;--l:#27AE60;--ln:#E3E8EE;--t:#1F2733;--s:#6B7785}}
*{{box-sizing:border-box;margin:0;padding:
