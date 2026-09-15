# 法律AI每周资讯

两院法务周报流水线：官方源 / 公众号 / RSS 采集 → LLM 初筛与板块聚合 → 暖纸底 HTML 周报 → 归档发布 → 钉钉推送。

仓库：https://github.com/Tree1Liu/legal-ai-weekly

## 环境

- Python 3.10+（推荐 3.13）
- Windows 可用 `C:\python\python.exe`

```bash
pip install -r requirements.txt
copy config.example.yaml config.yaml
```

填写 `config.yaml`（或环境变量）：

- `ZGC_KEY`：LLM Hub API Key
- `dingtalk.webhook` 或 `DINGTALK_WEBHOOK`
- `cloudstudio.last_url`：部署后的周报分享链接（钉钉 `push_style: link` 依赖此项）

## 运行

```bash
# 全流程：采集 → 周报 → 归档 → 重建 deploy/ → 推送
python main.py --once

# 快讯 / 季度合集
python main.py --once --flash
python main.py --quarterly

# 归档与发布目录
python archive.py --backfill
python archive.py --build
python archive.py --list

# 本地控制面板 http://127.0.0.1:5050
python panel_server.py

# 定时（按 config schedule，默认周五 12:00）
python scheduler_job.py
```

## 目录

```
main.py / pipeline.py / archive.py   # 入口、流水线、归档发布
report_html.py                       # 周报 HTML（暖纸底 Tufte）
summarize.py / enrich.py / curate.py / sections_strategy.py
detail.py / review.py / utils.py / quarterly.py
push_dingtalk.py / push_miniprogram.py
panel_server.py + panel/             # 控制面板
sources/                             # gov / wechat / legal_tools / industry
config.example.yaml                  # 配置模板（勿提交真实 config.yaml）
data/                                # digests / archive / inbox / saved
deploy/                              # archive.py --build 生成（不入库）
```

## 说明

- 对内参考，不替代正式法律意见
- 真实密钥只放本机 `config.yaml`，已在 `.gitignore` 中排除
