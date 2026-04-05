# Steam 游戏价格监测与提醒系统

一个面向个人自托管场景的 `FastAPI + SQLite + APScheduler` 应用，用来定时监控 Steam 游戏价格，并结合历史低价、多版本性价比与提醒规则，辅助判断“现在买 / 继续等 / 继续观察”。

详细功能与操作说明请查看：

- [USER_GUIDE.md](./USER_GUIDE.md)

## 已实现能力

- `POST /watch-items` 新增关注游戏，并在创建后立即完成首轮刷新
- `GET /watch-items` 查看关注单与当前价格状态
- `GET /games/{steam_appid}` 查看游戏详情、历史价格与提醒记录
- `GET /decision/{steam_appid}` 获取单个游戏的购买建议
- `POST /jobs/refresh` 手动刷新单个或全部关注项
- `GET /alerts` 查看提醒历史
- `POST /alerts/{alert_id}/retry` 重试失败提醒
- Web 页面：
  - `/watch-items/dashboard` 关注单
  - `/games/{steam_appid}/page` 游戏详情
  - `/alerts/page` 提醒中心
  - `/settings` 系统设置

## 项目结构

```text
Steam_Supervised/
├─ .runtime-venv/
├─ .venv/
├─ requirements.txt
├─ README.md
├─ USER_GUIDE.md
├─ run_server.py
├─ start.ps1
├─ stop.ps1
├─ steam_price_monitor/
│  ├─ main.py
│  ├─ models.py
│  ├─ scheduler.py
│  ├─ providers/
│  ├─ services/
│  ├─ templates/
│  └─ static/
└─ tests/
```

## 快速启动

```powershell
cd d:\Coding\PyFlies\Steam_Supervised
.\.runtime-venv\Scripts\python.exe .\run_server.py --reload --port 8001
```

这是当前推荐的启动方式：

- 终端会保持在前台，是否成功一眼就能看出来
- 修改代码后会自动热重载
- 不依赖后台脚本记录 PID，因此更适合当前这台机器

启动后访问：

- `http://127.0.0.1:8001/health`
- `http://127.0.0.1:8001/watch-items/dashboard`

## 可选脚本

项目仍然保留了 [start.ps1](./start.ps1) 和 [stop.ps1](./stop.ps1)，但当前不再作为默认推荐方式。
如果你的环境里后台脚本行为稳定，可以再使用它们。

如果你在开发中希望自动重载：

```powershell
.\.runtime-venv\Scripts\python.exe .\run_server.py --reload --port 8001
```

如果你一定要直接用 `uvicorn`，请保证当前目录就是 `Steam_Supervised`，或者显式加上 `--app-dir`：

```powershell
python -m uvicorn steam_price_monitor.main:app --reload --app-dir d:\Coding\PyFlies\Steam_Supervised
```

## 常用命令

运行测试：

```powershell
cd d:\Coding\PyFlies\Steam_Supervised
.\.runtime-venv\Scripts\python.exe -m pytest .\tests -o cache_dir=.\.pytest-cache
```

当前项目已经在测试层内置了 Windows 临时目录兼容补丁：

- `pytest` 会优先使用项目目录下的 [`.tmp`](./.tmp) 作为临时根目录
- 测试缓存会写入项目目录下的 [`.pytest-cache`](./.pytest-cache)
- 这一兼容只作用于测试，不影响应用本身的运行逻辑

最近一次本地验证结果：

```text
11 passed in 0.94s
```

手动前台启动：

```powershell
cd d:\Coding\PyFlies\Steam_Supervised
.\.runtime-venv\Scripts\python.exe .\run_server.py --port 8010
```

## 环境变量

可选环境变量都以 `SPM_` 开头：

- `SPM_DATABASE_URL`
- `SPM_SCHEDULER_ENABLED`
- `SPM_REFRESH_INTERVAL_MINUTES`
- `SPM_FULL_SYNC_HOUR`
- `SPM_ALERT_COOLDOWN_HOURS`
- `SPM_STEAM_COUNTRY_CODE`
- `SPM_STEAM_LANGUAGE`
- `SPM_REQUEST_TIMEOUT_SECONDS`
- `SPM_XIAOHEIHE_ENABLED`
- `SPM_XIAOHEIHE_BASE_URL`
- `SPM_SMTP_HOST`
- `SPM_SMTP_PORT`
- `SPM_SMTP_USERNAME`
- `SPM_SMTP_PASSWORD`
- `SPM_SMTP_SENDER`
- `SPM_NOTIFICATION_EMAIL`
- `SPM_SMTP_USE_TLS`
- `SPM_SMTP_USE_SSL`

## SMTP 配置说明

当前版本同时支持两种典型方式：

- `587 + STARTTLS`
  - `SMTP Port = 587`
  - `启用 TLS = 勾选`
  - `直接使用 SSL = 不勾选`
- `465 + SSL`
  - `SMTP Port = 465`
  - `启用 TLS = 不勾选`
  - `直接使用 SSL = 勾选`

## 数据源说明

- Steam Provider 默认启用，使用 `store.steampowered.com/api/appdetails`
- 小黑盒 Provider 作为补充源预留，默认关闭；配置 `SPM_XIAOHEIHE_BASE_URL` 后可接入你的适配接口
