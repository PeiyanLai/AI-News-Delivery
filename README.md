# AI News Delivery

每天自动抓取高质量 AI 资讯源，按事件去重聚合，生成中文摘要与产品经理视角的洞察，通过静态 Dashboard 和每日邮件送达。需求见 [REQUIREMENTS.md](REQUIREMENTS.md)。

## 架构

```
GitHub Actions（每日 07:00 北京时间）
   └─ python -m pipeline.main run
        抓取（RSS / HN API / 网页解析，单源失败不阻塞）
        → 跨天去重（data/seen_urls.json）
        → 事件聚合（embedding 相似度聚类）
        → 摘要（fast model，逐事件）
        → 分级 + 洞察卡片 + 今日导读/看点（smart model，每日一次，带最近 14 天档案做趋势判断）
        → data/YYYY-MM-DD.json（档案，可回溯）
        → docs/（静态 Dashboard，GitHub Pages 托管）
        → 邮件简报（Resend，可选）
```

## 首次部署（三步）

1. **配置 Secrets**：仓库 Settings → Secrets and variables → Actions，添加
   - `OPENAI_API_KEY`（必需）
   - 邮件（可选，不配则跳过）：SMTP 方式加 `SMTP_USER`（完整邮箱地址）和 `SMTP_PASS`（邮箱的 SMTP 授权码，不是登录密码）；或改用 Resend（`config/settings.yaml` 里 `email.provider: resend`）加 `RESEND_API_KEY`
2. **启用 GitHub Pages**：Settings → Pages → Source 选 `Deploy from a branch`，分支选默认分支的 `/docs` 目录。部署后把地址填入 `config/settings.yaml` 的 `site.base_url`（用于邮件底部链接）。
3. **手动触发一次**：Actions → Daily AI briefing → Run workflow，验证全链路。之后每天自动运行。

## 本地运行

```bash
pip install -r requirements.txt

# 无需任何 key 的端到端演示（示例数据 + mock LLM）
python -m pipeline.main run --mock --fixtures pipeline/fixtures/sample_articles.json --no-email

# 真实抓取 + mock LLM（验证各源可达性）
python -m pipeline.main run --mock --no-email

# 完整运行
export OPENAI_API_KEY=sk-...
python -m pipeline.main run
```

生成结果：`data/<日期>.json`（数据）与 `docs/`（网站，浏览器直接打开 `docs/index.html`）。

## 配置说明

| 文件 | 用途 |
|------|------|
| `config/settings.yaml` | 模型选择、聚类阈值、关注方向、洞察卡片上限、邮件收件人等 |
| `config/sources.yaml` | 信息源清单；加一个 RSS 源只需加一段配置，`enabled: false` 可停用 |
| `config/prompts/event_summary.md` | 事件摘要 prompt（fast model） |
| `config/prompts/daily_analysis.md` | 分级标准与洞察卡片六维度定义（smart model）——想增删洞察维度改这里 |

## 已知限制（MVP）

- 中文媒体源（量子位/机器之心）依赖其 RSS 端点，若失效需改用网页解析或 RSSHub；新智元暂未启用（无稳定 RSS）。
- 摘要基于 RSS 提供的正文/摘要，不抓全文。
- 每源抓取失败会在当日 Dashboard 和邮件中标注，连续失败需人工检查 `config/sources.yaml`。
