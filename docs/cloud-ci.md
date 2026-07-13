# 云平台集成与 CI/CD 说明

本文档用于说明本项目如何满足课程中的“云平台集成与 CI/CD 流水线”要求。当前方案采用“本地/局域网控制真车 + 云服务增强 + GitHub Actions 自动检查”的组合，既能适配小车必须在同一热点内控制的限制，也能在答辩时清楚展示云端能力。

## 1. 总体方案

系统分为三层：

1. Web 与后端：电脑运行 FastAPI 后端和 Web 页面，负责控制小车、展示摄像头、SLAM 建图导航、告警和报告。
2. 真车与 ROS2：小车在同一热点内提供控制、摄像头和导航相关服务。
3. 云平台：腾讯云 MySQL 持久化运行数据，腾讯云 ASR 完成语音识别，大模型 API 解析自然语言任务。

由于真车控制依赖局域网 IP、热点和 ROS2 运行状态，项目不把小车控制后端直接部署到云服务器；云端主要承担数据持久化、语音识别、智能任务解析和自动化质量检查。

## 2. 腾讯云 MySQL 数据库

### 2.1 功能作用

腾讯云 MySQL 用于保存运行数据，便于答辩展示“云端持久化”和后续数据分析：

- `robot_alarm`：告警记录，例如急停、传感器异常、视觉异常。
- `robot_report`：巡逻报告、导航到达记录、任务完成记录。
- `robot_vision_event`：视觉识别事件，例如人员、宠物、火焰、烟雾等。
- `robot_sensor_sample`：温湿度、光照、气体、PM2.5 等传感器采样。

### 2.2 本地启用方式

Windows PowerShell：

```powershell
cd F:\北交大2周项目\icar-smart-home
$env:ICAR_DB_HOST="你的腾讯云数据库地址"
$env:ICAR_DB_PORT="你的腾讯云数据库端口"
$env:ICAR_DB_USER="你的数据库用户名"
$env:ICAR_DB_PASSWORD="你的数据库密码"
$env:ICAR_DB_NAME="icar"
python scripts\db_check.py
.\scripts\start_backend.ps1
```

Ubuntu / Jetson：

```bash
cd /path/to/icar-smart-home
export ICAR_DB_HOST="你的腾讯云数据库地址"
export ICAR_DB_PORT="你的腾讯云数据库端口"
export ICAR_DB_USER="你的数据库用户名"
export ICAR_DB_PASSWORD="你的数据库密码"
export ICAR_DB_NAME="icar"
python3 scripts/db_check.py
./scripts/start_backend.sh
```

### 2.3 检查接口

后端启动后访问：

```text
http://127.0.0.1:8000/api/db/health
```

如果返回 `available: true`，说明云数据库已连通；如果返回 `database disabled`，说明当前没有设置数据库环境变量，系统会自动使用本地模拟/文件模式。

### 2.4 腾讯云侧注意事项

- 数据库密码不能写入 GitHub、README 或截图中。
- 腾讯云数据库安全组/白名单需要允许当前电脑所在公网 IP 访问。
- 校园网、手机热点和认证网关可能导致数据库连接失败，答辩前建议提前测试。

## 3. 腾讯云 ASR 语音识别

### 3.1 功能作用

Web 控制页面可以采集浏览器麦克风音频，后端调用腾讯云一句话识别，把语音转换成文字。后续再由大模型把文字转换成机器人任务。

示例流程：

1. 用户在 Web 页面点击语音调试。
2. 用户说“小比，开始巡逻”。
3. 浏览器上传音频到后端。
4. 后端调用腾讯云 ASR，得到识别文本。
5. 后端把文本交给大模型解析成任务。

### 3.2 环境变量

```powershell
$env:TENCENT_SECRET_ID="你的 SecretId"
$env:TENCENT_SECRET_KEY="你的 SecretKey"
$env:TENCENT_ASR_APP_ID="你的腾讯云账号 APPID"
$env:TENCENT_ASR_REGION="ap-beijing"
$env:TENCENT_ASR_ENGINE_MODEL_TYPE="16k_zh"
```

可选热词：

```powershell
$env:TENCENT_ASR_HOTWORD_ID=""
$env:TENCENT_ASR_HOTWORD_LIST=""
```

### 3.3 检查接口

```text
http://127.0.0.1:8000/api/voice/health
```

重点看：

- `tencent_configured: true`：腾讯云 ASR 密钥已配置。
- `wake_phrases`：当前唤醒词列表。
- `tool_names`：语音指令可调用的机器人工具列表。

## 4. 大模型任务解析

### 4.1 功能作用

大模型用于理解自然语言命令，并转换成后端可执行的工具调用。比如：

- “小比，前进一点” -> 手动控制小车前进。
- “小比，停止” -> 急停或停止导航。
- “小比，去厨房” -> 导航到指定点位。
- “小比，开始巡逻” -> 启动预设巡逻路线。

### 4.2 环境变量

项目使用兼容 OpenAI Chat Completions 格式的大模型接口，默认示例为 DeepSeek：

```powershell
$env:OPENAI_API_KEY="你的大模型 API Key"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:OPENAI_MODEL="deepseek-v4-pro"
$env:OPENAI_TEMPERATURE="0.5"
$env:OPENAI_THINKING_TYPE="disabled"
```

如果使用其他兼容接口，只需要替换 `OPENAI_BASE_URL` 和 `OPENAI_MODEL`。

## 5. GitHub Actions CI

### 5.1 工作流文件

CI 文件位于：

```text
.github/workflows/ci.yml
```

触发方式：

- 推送到 `main` 或 `yyh` 分支。
- 向 `main` 或 `yyh` 发起 Pull Request。
- 在 GitHub Actions 页面手动点击 `Run workflow`。

### 5.2 自动检查内容

CI 默认运行在模拟模式，不依赖真车、不依赖热点、不依赖腾讯云密钥：

1. 安装 Python 3.12。
2. 安装 `backend/requirements.txt`。
3. 编译后端、脚本和测试代码。
4. 运行 `python scripts/check_project.py` 检查关键文件和配置。
5. 运行 `python -m unittest discover -s tests -v` 执行单元测试。
6. 运行 `python scripts/test_migrated_features.py` 检查摄像头候选、TCP 控制帧、蜂鸣、灯光、循迹、SLAM 页面和 API。

这样可以证明：每次提交后，项目核心代码结构和离线功能都会被自动验证。

### 5.3 可选云配置检查

工作流里还有 `optional-cloud-check`。它不会阻塞主测试结果，主要用于展示云平台配置是否齐全。

如果在 GitHub 仓库中配置了 Secrets，它会额外检查：

- 腾讯云 ASR 是否配置。
- 大模型 API 是否配置。
- 腾讯云 MySQL 是否配置，并尝试运行 `scripts/db_check.py`。

## 6. GitHub Secrets 配置

进入 GitHub 仓库：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

建议添加：

```text
ICAR_DB_HOST
ICAR_DB_PORT
ICAR_DB_USER
ICAR_DB_PASSWORD
ICAR_DB_NAME
TENCENT_SECRET_ID
TENCENT_SECRET_KEY
TENCENT_ASR_APP_ID
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_MODEL
```

注意：

- Secrets 只存在 GitHub 后台，不会出现在代码里。
- 截图答辩时不要展示 Secret 明文。
- 如果担心数据库公网访问不稳定，可以只展示本地 `db_check.py` 成功截图，CI 中让云检查保持可选。

## 7. 本地模拟 CI 检查

提交前可以在本地运行：

```powershell
cd F:\北交大2周项目\icar-smart-home
python -m compileall backend\app scripts tests
python scripts\check_project.py
python -m unittest discover -s tests -v
python scripts\test_migrated_features.py
```

如果全部通过，再提交到 GitHub。

## 8. 答辩讲法

可以这样概括：

> 本项目完成了云平台集成与 CI/CD 流水线。云平台方面，系统接入腾讯云 MySQL 保存告警、巡逻报告、视觉事件和传感器采样；接入腾讯云 ASR 完成语音识别；接入兼容 OpenAI 格式的大模型 API，将自然语言转换成小车控制、巡逻和导航任务。CI/CD 方面，项目使用 GitHub Actions，在每次提交和 Pull Request 时自动安装依赖、检查项目结构、执行单元测试和核心功能测试。由于真车控制依赖同一局域网和 ROS2 环境，部署采用本地 Web 后端控制真车，云端用于智能能力和数据持久化增强。

如果老师追问为什么没有把后端部署到云服务器，可以回答：

> 小车控制链路依赖热点局域网、ROS2、摄像头和底盘服务，云服务器无法直接访问局域网中的小车端口。为了保证真车控制稳定，我们采用本地部署控制层，云端承担数据存储、语音识别和大模型任务解析，这是更符合硬件实训场景的架构。
