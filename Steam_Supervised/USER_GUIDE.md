# Steam 游戏价格监测与提醒系统使用手册

## 1. 系统简介

这是一个为个人自托管场景设计的 Steam 游戏价格监测工具。它的目标不是只告诉你“降价了”，而是尽量回答两个更有价值的问题：

- 这个价格现在值不值得买
- 如果同一游戏有多个版本，哪个更划算

系统目前已经支持：

- 管理自己的关注单
- 定时采集 Steam 游戏价格
- 保存历史价格快照
- 输出 `Buy / Wait / Watch` 决策建议
- 记录并发送价格提醒
- 在 Web 面板中查看价格、历史、提醒和设置

---

## 2. 页面说明

### 2.1 关注单

地址：

- `http://127.0.0.1:8000/watch-items/dashboard`

这里是主页面，可以：

- 添加新的关注游戏
- 设置目标价
- 设置优先级
- 查看当前价、折扣和建议
- 进入游戏详情页

### 2.2 游戏详情

地址格式：

- `/games/{steam_appid}/page`

这里会显示：

- 当前建议状态
- 当前价、90 天低价、180 天低价
- 历史价格轨迹
- 多版本对比结果
- 最近提醒记录

### 2.3 提醒中心

地址：

- `/alerts/page`

这里用来查看所有提醒历史，包括：

- 提醒类型
- 对应价格
- 发送状态
- 失败原因

### 2.4 系统设置

地址：

- `/settings`

这里可以调整：

- 定时刷新频率
- 每日全量同步时间
- 邮件提醒配置
- 是否启用小黑盒补充源

---

## 3. 决策结果说明

系统会给出三种建议：

### 3.1 Buy

表示当前价格已经满足入手条件，例如：

- 已达到你的目标价
- 已进入系统监控到的低位区间

### 3.2 Wait

表示现在虽然有折扣，但还不算最佳买点，例如：

- 当前价仍明显高于近 180 天低价

### 3.3 Watch

表示继续观察，例如：

- 当前没有足够价格历史
- 当前没有明显折扣
- 还没到你的目标价

---

## 4. 多版本比价

如果一个游戏有多个购买版本，例如：

- 标准版
- 豪华版
- 捆绑包

可以通过以下方式让系统比较性价比：

- 用 `base_game_appid` 把它们关联到同一个基础游戏
- 用 `value_score` 表示内容价值

系统会根据“当前价格 / 价值系数”计算归一化价格，归一化价格越低，表示越划算。

---

## 5. 提醒规则

当前支持的提醒包括：

- 达到目标价
- 刷新监控期内新低
- 首次进入显著折扣区间
- 决策从非 `Buy` 升级为 `Buy`

系统会做去重：

- 同一游戏
- 同一提醒类型
- 同一价格
- 在冷却时间内只提醒一次

默认冷却时间是 24 小时。

---

## 6. 安装与启动

进入项目目录后，建议始终使用项目自己的虚拟环境：

```powershell
cd d:\Coding\PyFlies\Steam_Supervised
.\.runtime-venv\Scripts\python.exe -m pip install -r requirements.txt
```

推荐直接前台启动服务：

```powershell
.\.runtime-venv\Scripts\python.exe .\run_server.py --reload --port 8001
```

这种方式更适合当前项目环境：

- 启动是否成功可以直接在当前终端看到
- 修改代码后会自动热重载
- 不依赖后台脚本记录 PID

启动后访问：

- `http://127.0.0.1:8001/health`
- `http://127.0.0.1:8001/watch-items/dashboard`

如果你看到浏览器一直转圈、终端里出现 `ModuleNotFoundError: No module named 'steam_price_monitor'`，基本就是启动目录不对。此时优先使用 `run_server.py`，它会自动带上正确的 `app_dir`。

后台脚本仍然保留，但现在只作为可选方案：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

对应停止：

```powershell
powershell -ExecutionPolicy Bypass -File .\stop.ps1
```

如果你明确想用后台脚本并启用热重载：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Reload
```

运行测试：

```powershell
.\.runtime-venv\Scripts\python.exe -m pytest .\tests -o cache_dir=.\.pytest-cache
```

---

## 7. 常见操作流程

### 7.1 添加第一个关注游戏

步骤：

1. 打开关注单页面
2. 输入 `Steam AppID`
3. 填写目标价
4. 点击“加入关注并立即刷新”

系统会自动：

- 创建关注项
- 拉取首轮价格
- 生成建议
- 必要时触发提醒

### 7.2 手动刷新单个游戏

请求：

```http
POST /jobs/refresh
Content-Type: application/json

{
  "steam_appid": 730
}
```

### 7.3 刷新全部关注项

请求：

```http
POST /jobs/refresh
Content-Type: application/json

{}
```

### 7.4 重试失败提醒

请求：

```http
POST /alerts/{alert_id}/retry
```

---

## 8. API 简表

- `POST /watch-items`
  新增或更新关注项
- `GET /watch-items`
  获取关注单
- `GET /games/{steam_appid}`
  获取游戏详情
- `GET /decision/{steam_appid}`
  获取购买建议
- `POST /jobs/refresh`
  手动触发刷新
- `GET /alerts`
  获取提醒列表
- `POST /alerts/{alert_id}/retry`
  重试失败提醒

---

## 9. SMTP 配置

你可以在 `/settings` 页面配置邮件提醒。

### 9.1 587 + STARTTLS

适合大多数邮箱服务商：

- `SMTP Host`：服务商提供的 SMTP 地址
- `SMTP Port`：`587`
- `SMTP 用户名`：邮箱账号
- `SMTP 密码`：邮箱密码或授权码
- `发件人`：发信邮箱
- `启用 TLS`：勾选
- `直接使用 SSL`：不勾选

### 9.2 465 + SSL

适合要求 SSL 直连的服务商：

- `SMTP Port`：`465`
- `启用 TLS`：不勾选
- `直接使用 SSL`：勾选

### 9.3 提醒状态说明

- `pending`
  已生成提醒，但没有实际发出邮件
- `sent`
  邮件发送成功
- `failed`
  邮件发送失败，可手动重试

---

## 10. 环境变量

系统支持以下环境变量：

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

---

## 11. 常见问题

### 11.1 页面能打开，但没有价格

可能原因：

- `steam_appid` 填错
- 网络无法访问 Steam 接口
- 当前区域下没有可用价格

### 11.2 有提醒记录，但没收到邮件

先检查提醒中心中的状态：

- `pending`：通常说明 SMTP 配置还不完整
- `failed`：通常说明连接、认证或 TLS/SSL 配置有问题

### 11.3 为什么有折扣但不是 Buy

因为系统不会只看“是否打折”，还会综合考虑：

- 目标价
- 历史低价
- 当前是否处于监控期低位
- 历史样本是否足够

---

## 12. 推荐下一步

如果你准备继续把它做成长期自用工具，推荐下一步优先完善：

- 编辑 / 删除关注项
- 浏览器推送或 IM 机器人提醒
- 更完整的历史价格来源
- 更强的多商店比价能力
