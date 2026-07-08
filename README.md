# 亚马逊运营每日资讯 · 自动推送

每天 **北京时间 08:00** 自动采集亚马逊 / 跨境电商最新资讯，生成网页并发布到 GitHub Pages。

## 你每天要看的
- **最新一期**：`https://你的用户名.github.io/仓库名/`
- **往期归档**（本周复盘 / 月度汇总 / 完整列表）：网页底部「📚 查看往期归档」

## 它怎么自动跑的
1. `collector.py` —— 采集资讯（官方 RSS 原文直链 + Google News 广度补充）
2. `run_daily.py` —— 生成网页，并写入往期档案 `archive/history.json`
3. `.github/workflows/daily_push.yml` —— GitHub Actions 每天 08:00 自动运行并部署网页

## 新手怎么部署
完全不用懂代码，照着《零基础部署步骤图解.md》点 6 步即可：建仓库 → 传整个文件夹 → Pages 选 GitHub Actions → 点一次 Run workflow → 拿网址。

> 默认只出网页；邮件 / 微信提醒为可选项，需额外配置。
