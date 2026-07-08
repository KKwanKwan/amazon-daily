#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse,json,re,html as _h,datetime,os
import xml.etree.ElementTree as _ET,requests
from email.utils import parsedate_to_datetime

UA={"User-Agent":"Mozilla/5.0"}
TO=15;BD=datetime.date(2026,7,8);HF="archive/history.json"
OFS=[("About Amazon","https://www.aboutamazon.com/news/rss"),
     ("Practical Ecommerce","https://www.practicalecommerce.com/feed")]
GNQ=["Amazon seller policy update","Amazon FBA fee changes",
    "Amazon FBA changes 2026","Amazon global selling new marketplace",
    "亚马逊 卖家 政策","亚马逊 FBA 费用",
    "亚马逊 Prime Day","跨境电商 关税 欧盟",
    "亚马逊 AI 广告"]
CR=[
("物流与供应链",["tariff","customs","logistics","fulfillment",
  "shipping","cost","关税","清关","物流","海外仓",
  "运价","海运","小包","免税","成本","涨价"]),
("全球合规",["compliance","regulation","law",
  "privacy","recall","banned","suspended","fine","effective",
  "合规","认证","隐私","法律","法规",
  "披露","罚款","封号","召回","下架"]),
("政策与费用",["fee","FBA","commission","policy",
  "rule","费用","费率","佣金"]),
("流量与活动",["Prime","sale","deal",
  "advertising","traffic","大促","广告"]),
("工具与运营",["tool","AI","SOP",
  "automation","assistant"]),
("今日头条",["marketplace","expansion","latin",
  "brazil","mexico","拉美","巴西","墨西哥"])]
HW=["effective","tax","tariff","compliance","recall","banned",
  "suspended","fine","law","生效","新规","新法",
  "封号","冻结","召回","下架","诉讼",
  "制裁"]
MW=["fee","FBA","commission","subsidy","Prime","advertising"]
IMP={
"物流与供应链":"涉及跨境物流/关税。",
"全球合规":"涉及合规风险。",
"政策与费用":"涉及平台费用。",
"流量与活动":"涉及站内流量。",
"工具与运营":"涉及运营工具。",
"今日头条":"涉及市场拓展。"}
ACT={}
ACT["logistics|high"]="本周核算履约成本。"
ACT["compliance|high"]="本周排查合规风险。"
ACT["policy|high"]="重算主力SKU盈利。"
ACT["traffic|high"]="调整广告排期。"
ACT["tools|low"]="评估接入现有运营流程。"
ACT["headline|mid"]="联系账户经理了解入仓条件。"

def _n(t):return re.sub(r"[\s\W_]+","",t.lower())
def _cl(s):
 s=re.sub(r"<[^>]+>"," ",s or"")
 return _h.unescape(re.sub(r"\s+"," ",s)).strip()
def classify(t):
 t=t.lower()
 for col,wds in CR:
  if any(x.lower()in t for x in wds): return col
 return "headline"
def level(t,col):
 t=t.lower()
 if any(w.lower()in t for w in HW): return "high"
 if any(w.lower()in t for w in MW): return "mid"
 return "low"

def mk_item(title,link,src,pub,desc,origin):
 col=classify(title);lv=level(title,col)
 imp=IMP.get(col,"建议关注。")
 key=col+"|"+lv
 act=ACT.get(key) or ACT.get(col+"|mid") or "关注后续。"
 tag="" if origin=="official" else " (via Google News)"
 return {"level":lv,"column":col,"title":title,
  "tags":[ "#"+col, "#"+src ],
  "what": title+" "+desc.strip("."),
  "impact":imp,"action":act,
  "source": src+tag+" | "+pub,
  "link":link,"origin":origin,"needs_review":lv=="high"}

def fetch_official(name,url,hours):
 try:r=requests.get(url,timeout=TO,headers=UA);r.raise_for_status()
 except Exception as e:print(" ! ["+name+"] "+str(e));return{}
 try:root=_ET.fromstring(r.content)
 except Exception as e:print(" ! ["+name+"] parse "+str(e));return{}
 cut=datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=hours)
 out={}
 for it in root.iter("item"):
  t=_cl(it.findtext("title",""));lk=(it.findtext("link","")or"").strip()
  pub=it.findtext("pubDate","");desc=_cl(it.findtext("description",""))[:200]
  if not t or not lk or len(t)<8:continue
  try:
    dt=parsedate_to_datetime(pub).astimezone(datetime.timezone.utc)
    if dt<cut:continue
  except:pass
  out[_n(t)]=mk_item(t,lk,name,pub,desc,"official")
 print(" ok ["+name+"]:"+str(len(out)));return out

def fetch_gn(q,hours):
 url="https://news.google.com/rss/search?q="+requests.utils.quote(q)+"&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
 try:r=requests.get(url,timeout=TO,headers=UA);r.raise_for_status()
 except:return{}
 try:root=_ET.fromstring(r.content)
 except:return{}
 cut=datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=hours);out={}
 for it in root.iter("item"):
  t=_cl(it.findtext("title",""));lk=(it.findtext("link","")or"").strip();pub=it.findtext("pubDate","")
  src=it.findtext("source") or ""
  if not src:src="GN"
  desc=_cl(it.findtext("description",""))[:200]
  body=t.rsplit(" - ",1)[0] if " - "in t else t
  if len(body)<8:continue
  try:
    dt=parsedate_to_datetime(pub).astimezone(datetime.timezone.utc)
    if dt<cut:continue
  except:pass
  k=_n(body)
  if k not in out:out[k]=mk_item(body,lk,src,pub,desc,"google")
 return out

def collect(hours,top):
 m={}
 for n,u in OFS:m.update(fetch_official(n,u,hours))
 for q in GNQ:
  for k,v in fetch_gn(q,hours).items():m.setdefault(k,v)
 items=list(m.values())
 ord_map={"headline":0,"policy":1,"traffic":2,"logistics":3,"compliance":4,"tools":5}
 items.sort(key=lambda x:({"high":0,"mid":1,"low":2}[x["level"]],ord_map.get(x["column"],9)))
 return items[:top]

# ===== CSS =====
CSS=(
 "body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:#F4F6F8;color:#1F2733;line-height:1.65;padding:24px 12px;margin:0}.wrap{max-width:720px;margin:0 auto}.hero{background:linear-gradient(135deg,#232F3E,#37475A);color:#fff;border-radius:16px;padding:24px 22px;box-shadow:0 6px 20px rgba(35,47,62,.18)}.hero .kicker{font-size:12px;letter-spacing:2px;color:#FF9900;font-weight:700}.hero h1{font-size:23px;margin:6px 0 10px;font-weight:800}.hero .summary{font-size:14px;color:#D7DEE6}.hero .meta{margin-top:14px;font-size:12px;color:#AEB9C4;display:flex;gap:14px;flex-wrap:wrap}.hero .meta b{color:#fff}.alert{background:#FDECEA;border:1px solid #F5C6C0;border-left:4px"
 " solid #E74C3C;border-radius:10px;padding:12px 14px;margin:18px 0;font-size:13.5px}.alert b{color:#E74C3C}.card{background:#fff;border:1px solid #E3E8EE;border-radius:14px;padding:16px 18px;margin:14px 0;position:relative;overflow:hidden;box-shadow:0 2px 8px rgba(35,47,62,.05)}.card::before{content:'';position:absolute;left:0;top:0;bottom:0;width:5px}.card.high::before{background:#E74C3C}.card.mid::before{background:#F39C12}.card.low::before{background:#27AE60}.card h2{font-size:16.5px;font-weight:800;margin-bottom:8px;padding-right:8px}.tags{margin:0 0 10px;display:flex;gap:6px;flex-wrap:wrap}.tag{font-size:11px;padding:2px 8px;border-radius:20px;background:#EEF2F6;color:#6B7785}.tag.lvl{"
 "color:#fff;font-weight:700}.tag.high{background:#E74C3C}.tag.mid{background:#F39C12}.tag.low{background:#27AE60}.sec{margin:8px 0;font-size:13.5px}.sec .lab{font-weight:800;color:#232F3E;margin-right:6px}.sec .lab:before{content:'\\25ce ';color:#FF9900;margin-right:4px}.act{background:#F0F8F1;border-radius:8px;padding:8px 10px;margin-top:8px;font-size:13px}.src{font-size:11.5px;color:#6B7785;margin-top:9px;border-top:1px dashed #E3E8EE;padding-top:7px}.srclink{color:#2E6FB0;font-weight:600;text-decoration:none;border-bottom:1px dashed #2E6FB0}.srclink:hover{color:#FF9900;border-bottom-color:#FF9900}.check{background:#fff;border:1px solid #E3E8EE;border-radius:14px;padding:16px 18px;margin:"
 "14px 0}.check h2{font-size:16.5px;font-weight:800;margin-bottom:10px;color:#232F3E}.check ul{list-style:none}.check li{font-size:13.5px;padding:7px 0;border-bottom:1px dashed #E3E8EE;display:flex;gap:9px;align-items:flex-start;flex-wrap:wrap}.check li:last-child{border-bottom:none}.check .box{width:17px;height:17px;border:2px solid #FF9900;border-radius:4px;flex:0 0 auto;margin-top:2px}.check small{color:#6B7785;font-weight:400;margin-left:4px}.check small a{color:#2E6FB0;text-decoration:none}.check small a:hover{color:#FF9900;text-decoration:underline}.footer{text-align:center;font-size:11.5px;color:#6B7785;margin:22px 0 6px}.footer b{color:#232F3E}a{color:#FF9900;text-decoration:none}"
)

def esc(s):return _h.escape(str(s))

def build_card(item):
 lc=item["level"];icons={"high":"🔴","mid":"🟠","low":"🟢"};ic=icons.get(lc,"")
 tags=" ".join('<span class="tag">'+esc(t)+'</span>' for t in item.get("tags",[]))
 lm=["High","Mid","Low"];ix=["high","mid","low"].index(lc)
 tags=tags+' <span class="tag lvl '+lc+'">影响:'+lm[ix]+'</span>'
 link=item.get("link","")
 st=esc(item.get("source",""))
 if link:
  sr='<div class="src">Source: <a href="'+esc(link)+'" target="_blank" rel="noopener" class="srclink">'+st+' 🔗</a></div>'
 else:
  sr='<div class="src">Source: '+st+'</div>'
 p=[]
 p.append('<div class="card '+lc+'">')
 p.append('<h2>'+esc(item["column"])+' | '+esc(item["title"])+'</h2>')
 p.append('<div class="tags">'+tags+'</div>')
 p.append('<div class="sec"><span class="lab">What</span>'+esc(item.get("what",""))+'</div>')
 p.append('<div class="sec"><span class="lab">Impact</span>'+esc(item.get("impact",""))+'</div>')
 p.append('<div class="action">✅ Action: '+esc(item.get("action",""))+'</div>')
 p.append(sr)
 p.append('</div>')
 return "".join(p)

def build_checklist(items):
 groups={};order=[]
 for it in items:
  act=(it.get("action")or"").strip()
  if not act: continue
  if act not in groups:
   groups[act]=[];order.append(act)
  groups[act].append(it)
 if not groups: return ""
 r=[]
 r.append('<div class="check">')
 r.append('<h2>✅ Action List ('+str(len(groups))+' groups)</h2>')
 r.append('<ul>')
 for act in order:
  r.append('<li><span class="box"></span><span>'+esc(act)+'</span>')
  for it in groups[act]:
   lk=it.get("link","")
   if lk:
    ts=(it.get("title")or"")[:28]
    r.append(' <small>(<a href="'+esc(lk)+'" target="_blank" rel="noopener">'+esc(ts)+'...🔗</a>)</small>')
  r.append('</li>')
 r.append('</ul>')
 r.append('</div>')
 return"".join(r)

def build_page(data,date_str,issue):
 items=data.get("items",[])
 hi=sum(1 for i in items if i.get("level")=="high")
 alert=data.get("alert","")
 ah=[]
 if alert:
  ah.append('<div class="alert"><b>Warning: </b>'+esc(alert)+'</div>')
 cards=[build_card(i) for i in items]
 chk=build_checklist(items)
 o=[]
 o.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">')
 o.append('<meta name="viewport" content="width=device-width,initial-scale=1.0">')
 o.append('<title>'+esc("Amazon Daily News #"+str(issue)+" ("+date_str+")")+'</title>')
 o.append('<style>'+CSS+'</style></head><body><div class="wrap">')
 o.append('<div class="hero"><div class="kicker">AMAZON DAILY NEWS</div>')
 o.append('<h1>'+esc("Amazon Daily News #"+str(issue))+'</h1>')
 o.append('<div class="summary">'+esc(data.get("summary",""))+'</div>')
 o.append('<div class="hero meta">')
 o.append('<span>📅 <b>'+date_str+'</b></span>')
 o.append('<span>📌 <b>'+str(len(items))+'</b> items</span>')
 o.append('<span>🔴 <b>'+str(hi)+'</b> high</span>')
 o.append('</div></div>')
 o.extend(ah)
 o.extend(cards)
 o.append(chk)
 o.append('<div class="footer"><b>Amazon Daily</b> | updated daily at 08:00 CST | ')
 o.append('<a href="archive.html">'+esc("📚 Archive")+'</a>')
 o.append('<br>auto-generated by run.py</div>')
 o.append('</div></body></html>')
 return"".join(o)

def build_archive(history,latest_date):
 def e(s):return _h.escape(str(s))
 try:ld=datetime.date.fromisoformat(latest_date)
 except:ld=datetime.date.today()
 ws=ld-datetime.timedelta(days=6)
 week=[h for h in history if h.get("date")>=ws.isoformat()]
 wt=sum(len(h.get("items",[]))for h in week)
 wh=sum(1 for h in week for i in h.get("items",[])if i.get("level")=="high")
 o=[]
 o.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">')
 o.append('<meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Archive</title><style>')
 acss="body{font-family:-apple-system,'PingFang SC',sans-serif;background:#F4F6F8;color:#1F2733;padding:24px 12px;margin:0}"
 acss+=".wrap{max-width:760px;margin:0 auto}.hero{background:linear-gradient(135deg,#232F3E,#37475A);color:#fff;border-radius:16px;padding:22px;margin-bottom:10px}"
 acss+=".hero h1{font-size:22px;margin:0}.hero sub{font-size:13px;color:#D7DEE6;margin-top:6px}"
 acss+=".card{background:#fff;border:1px solid #E3E8EE;border-radius:14px;padding:16px 18px;margin:14px 0;box-shadow:0 2px 8px rgba(35,47,62,.05)}"
 acss+=".card h2{font-size:16px;margin:0 0 10px;color:#232F3E}table{width:100%;border-collapse:collapse;font-size:13.5px}"
 acss+="th,td{text-align:left;padding:8px 6px;border-bottom:1px solid #EEF2F6}th{color:#6B7785;font-weight:700}"
 acss+="a{color:#2E6FB0;text-decoration:none}a:hover{text-decoration:underline}"
 acss+=".pill{display:inline-block;background:#FF9900;color:#232F3E;font-weight:700;border-radius:20px;padding:2px 10px;font-size:12px}"
 acss+="ul{margin:6px 0;padding-left:20px}li{font-size:13.5px;padding:3px 0}.footer{text-align:center;font-size:11.5px;color:#6B7785;margin:18px 0}"
 o.append(acss+'</style></head><body><div class="wrap">')
 o.append('<div class="hero"><h1>'+e("📚 Archive")+'</h1>')
 o.append('<div class="sub">'+e(str(len(history))+" issues | latest: "+latest_date)+" | 08:00 daily</div></div>")
 o.append('<div class="card"><h2>'+e("🔁 This Week")+'('+ws.isoformat()+"~"+ld.isoformat()+')</h2>')
 o.append("<p style='font-size:13.5px;margin:0 0 8px'>"+str(wt)+" items <span class='pill'>"+str(wh)+" high</span></p><ul>")
 wl=[]
 for h in reversed(week):
  nhi=sum(1 for i in h.get("items",[])if i.get("level")=="high")
  wl.append('<li><a href="'+e(h['date'])+'.html">'+e(h['date'])+'</a> '
           +str(len(h.get('items',[])))+" items"
           +("🔴"*nhi if nhi else "")+"</li>")
 if not wl:wl.append("<li>No data this week</li>")
 o.extend(wl);o.append("</ul></div>")
 o.append('<div class="card"><h2>'+e("📊 Monthly")+"</h2><table><tr><th>Month</th><th>Items</th></tr>")
 ms={};[ms.__setitem__(h["date"][:7],ms.get(h["date"][:7],0)+len(h.get("items",[])))for h in history]
 for m,n in sorted(ms.items(),reverse=True):
  o.append("<tr><td>"+e(m)+"</td><td>"+str(n)+"</td></tr>")
 o.append("</table></div>")
 o.append('<div class="card"><h2>'+e("📂 All Issues")+"</h2><table><tr><th>Date</th><th>#</th><th>Items</th><th>High</th></tr>")
 for h in reversed(history):
  nhi=sum(1 for i in h.get("items",[])if i.get("level")=="high")
  o.append("<tr><td><a href='"+e(h['date'])+".html'>"+e(h['date'])+"</a></td>"
             +"<td>#"+str(h.get('issue','?'))+"</td><td>"
             +str(len(h.get('items',[])))+"</td><td>"
             +("🔴"*nhi if nhi else "-")+"</td></tr>")
 o.append("</table></div>")
 o.append("<div class='footer'><a href='index.html'>"+e("← Back")+"</a></div>")
 o.append("</div></body></html>")
 return"".join(o)

def issue_of(today):return max(1,(today-BD).days+1)

def load_h():
 if os.path.exists(HF):
  try:return json.load(open(HF,encoding="utf-8"))
  except:return []
 return[]
def save_h(h):
 os.makedirs("archive",exist_ok=True)
 json.dump(h,open(HF,"w",encoding="utf-8"),ensure_ascii=False,indent=2)

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument("--hours",type=int,default=48)
 ap.add_argument("--top",type=int,default=8)
 args=ap.parse_args()
 today=datetime.date.today();ds=today.strftime("%Y-%m-%d");issue=issue_of(today)
 print("=== Issue #"+str(issue)+" | "+ds+" ===")
 items=collect(args.hours,args.top)
 hi=sum(1 for i in items if i.get("level")=="high")
 of=sum(1 for i in items if i.get("origin")=="official")
 sm=str(len(items))+" items ("+str(of)+" official), "+str(hi)+" high" if items else "No new items"
 al="Check high-impact items." if hi else ""
 history=load_h();rec={"date":ds,"issue":issue,"summary":sm,"alert":al,"items":items}
 found=False
 for idx,hh in enumerate(history):
  if hh.get("date")==ds:history[idx]=rec;found=True;break
 if not found:history.append(rec)
 history.sort(key=lambda x:x.get("date",""));save_h(history)
 print("ok history="+str(len(items)))
 os.makedirs("site",exist_ok=True)
 for hh in history:
  dd={"summary":hh["summary"],"alert":hh["alert"],"items":hh["items"]}
  open("site/"+hh['date']+".html","w",encoding="utf-8").write(build_page(dd,hh["date"],hh["issue"]))
 lhx=history[-1]
 open("site/index.html","w",encoding="utf-8").write(
   build_page({"summary":lhx["summary"],"alert":lhx["alert"],"items":lhx["items"]},ds,issue))
 open("site/archive.html","w",encoding="utf-8").write(build_archive(history,ds))
 print("ok site updated")
 print("=== done ===")

if __name__=="__main__":main()
