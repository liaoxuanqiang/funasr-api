# funasr-api

基于 **FunASR** 的中文语音识别（ASR）API 部署项目。通过 GitHub Actions 自动部署 FunASR 语音识别服务，并借助 **Cloudflare Tunnel** 将服务暴露到公网，支持手动触发和定时自动运行。同时内置 **Progressive Web App（PWA）** 语音识别界面（参考 [FunASR 官方 Demo](https://huggingface.co/spaces/funasr/demo)），支持上传 / 录制音频并一键转写，可安装到手机与桌面。

---

## 目录

- [项目结构](#项目结构)
- [功能特性](#功能特性)
- [工作原理](#工作原理)
- [工作流配置说明](#工作流配置说明)
- [环境变量与密钥](#环境变量与密钥)
- [API 使用说明](#api-使用说明)
- [PWA 使用说明](#pwa-使用说明)
- [运行状态说明](#运行状态说明)
- [注意事项](#注意事项)

---

## 项目结构

```
funasr-api/
├── .github/
│   └── workflows/
│       └── funasr.yml   # GitHub Actions 部署工作流
├── Caddyfile            # PWA 网关配置（静态站点 + FunASR API 反向代理）
├── pwa/                 # PWA 前端（HTML / CSS / JS / Manifest / Service Worker）
│   ├── index.html       # 主界面（上传 / 录音、模型选择、转写结果）
│   ├── app.js           # 前端逻辑（API 探测、录音、转写）
│   ├── sw.js            # Service Worker（离线缓存）
│   ├── manifest.webmanifest  # PWA 清单（可安装）
│   ├── offline.html     # 离线降级页
│   ├── generate_icons.py     # 图标生成脚本（纯标准库）
│   └── icons/           # 应用图标（icon-192 / icon-512）
└── README.md            # 项目说明文档
```

## 功能特性

- 🤖 自动部署 FunASR 语音识别服务（`paraformer-zh` 中文识别模型）
- 📱 内置 **PWA** 语音识别界面：上传 / 拖拽 / 录音音频，选择模型即可转写，支持安装到手机与桌面、离线缓存
- 🌐 通过 Cloudflare Tunnel 提供公网访问，无需固定公网 IP
- ⏰ 支持手动触发与每 6 小时定时自动运行
- 🚀 pip 依赖缓存，加速重复部署
- 🔀 Caddy 网关统一出口：`/` 提供 PWA 界面，`/health`、`/recognize`、`/v1/*` 等 API 路径反向代理到 FunASR 服务

## 工作原理

整个部署流程运行在 GitHub Actions 的 `ubuntu-22.04` runner 上：

```
GitHub Actions Runner
    │
    ├── 启动 FunASR 服务（127.0.0.1:10097，paraformer-zh 模型）
    │
    ├── 启动 Caddy PWA 网关（侦听 127.0.0.1:10095，即隧道源站）
    │        ├── 静态服务：PWA 前端（根路径 /）
    │        └── 反向代理：/health、/asr、/recognize、/v1/* 等 → FunASR (127.0.0.1:10097)
    │
    ├── Cloudflare Tunnel（cloudflared）→ 公网域名
    │
    └── Keep runner alive（无限循环，保持服务持续运行）
```

> 💡 为什么网关放在源站端口：当前隧道以 `--token` 运行，属于**远程托管（Remote Managed）**隧道，
> 其入口规则由 Cloudflare 控制台远程配置决定并指向 `localhost:10095`，工作流无法在本地覆盖。
> 因此将 **Caddy 网关**绑定在 `10095`（PWA + API 代理），FunASR 服务内移至 `10097`。

## 工作流配置说明

工作流文件：`.github/workflows/funasr.yml`

### 触发方式

| 触发方式 | 配置 | 说明 |
|---------|------|------|
| 手动触发 | `workflow_dispatch` | 在仓库 **Actions** 页面点击 **Run workflow** 执行 |
| 定时调度 | `schedule: cron '0 */6 * * *'` | 每 6 小时自动运行一次 |

> ⚠️ **时区提示**：GitHub Actions 的 cron 调度使用 **UTC 时间**。`0 */6 * * *` 表示在 UTC 的 0、6、12、18 点整运行，对应北京时间（UTC+8）的 8、14、20 点及次日 2 点。

### 并发控制

```yaml
concurrency:
  group: funasr-deploy
  cancel-in-progress: false
```

- 同一时间只允许一个部署任务运行，避免多个 runner 竞争同一端口/隧道。
- `cancel-in-progress: false`：新触发的运行不会取消正在进行的旧运行，而是排队等待。

### 部署流程（10 个步骤）

| 步骤 | 名称 | 作用 |
|------|------|------|
| 1 | Checkout repository | 检出仓库代码（提供 `pwa/` 前端与 `Caddyfile`） |
| 2 | Set up Python | 配置 Python 3.10 环境 |
| 3 | Cache pip dependencies | 缓存 pip 下载的依赖包，加速安装 |
| 4 | Install dependencies | 安装 `funasr`、`torch`、`torchaudio`、`modelscope`、`uvicorn`、`fastapi`、`python-multipart` |
| 5 | Start FunASR server | 后台启动 FunASR 服务（内网端口 `10097`，CPU 推理，`paraformer-zh` 模型，模型从 HuggingFace 下载），并轮询健康检查等待就绪 |
| 6 | Install Caddy | 下载并安装 Caddy 静态服务器 / 反向代理 |
| 7 | Start PWA gateway | 在源站端口 `10095` 启动 Caddy 网关：根路径 `/` 提供 PWA 界面，`/health`、`/asr`、`/recognize`、`/v1/*` 等反向代理到 FunASR，并执行 PWA 资源 / 代理连通性检查 |
| 8 | Install cloudflared | 下载并安装 Cloudflare Tunnel 客户端 |
| 9 | Start cloudflared tunnel | 使用 Token 启动隧道，将 `10095` 网关暴露到公网 |
| 10 | Keep runner alive | 无限循环保持 runner 存活，从而维持服务持续运行 |

### 关键配置项

| 配置 | 当前值 | 说明 |
|------|--------|------|
| `runs-on` | `ubuntu-22.04` | 运行环境 |
| `timeout-minutes` | `360` | 任务超时上限（6 小时），超过后平台强制终止 |
| `SERVER_PORT` | `10095` | Caddy PWA 网关监听端口（**隧道源站端口**，不可随意改动） |
| `ASR_PORT` | `10097` | FunASR 服务内网监听端口（仅本机可访问） |
| `SERVER_HEALTH_URL` | `http://127.0.0.1:10095/health` | 经网关的健康检查地址（验证 PWA 网关 → FunASR 链路） |
| 模型 | `paraformer`（HuggingFace） | 中文语音识别模型，`--model paraformer` |
| FunASR 健康检查轮询 | 60 次 × 5 秒 | 最长等待约 5 分钟 |
| PWA 网关健康检查轮询 | 30 次 × 2 秒 | 最长等待约 1 分钟 |

## 环境变量与密钥

| 名称 | 类型 | 位置 | 说明 |
|------|------|------|------|
| `SERVER_PORT` | 工作流变量 | 工作流 `env` | Caddy PWA 网关端口（默认 `10095`，即隧道源站） |
| `ASR_PORT` | 工作流变量 | 工作流 `env` | FunASR 服务内网端口（默认 `10097`） |
| `SERVER_HEALTH_URL` | 工作流变量 | 工作流 `env` | 经网关的健康检查地址 |
| `CLOUDFLARE_TUNNEL_TOKEN` | **GitHub Secrets** | 仓库 Settings → Secrets and variables → Actions | Cloudflare Tunnel 的认证 Token |

### 配置 Cloudflare Tunnel Token（推荐）

工作流通过 `${{ secrets.CLOUDFLARE_TUNNEL_TOKEN }}` 读取隧道 Token，未配置 Secret 时会回退使用工作流内嵌的旧 Token（不推荐，存在泄露风险）。建议：

1. 在 [Cloudflare Zero Trust Dashboard](https://one.dash.cloudflare.com/) 创建 Tunnel 并获取 Token。
2. 在仓库 **Settings → Secrets and variables → Actions** 中添加 Secret，名称为 `CLOUDFLARE_TUNNEL_TOKEN`。
3. 如旧 Token 曾泄露，请在 Cloudflare 控制台**重置**。

## API 使用说明

服务部署成功后，可通过 Cloudflare Tunnel 提供的公网域名访问 FunASR 服务：

### 健康检查

```bash
curl https://<你的隧道域名>/health
```

### 语音识别

```bash
curl -X POST "https://<你的隧道域名>/recognize" \
  -F "file=@audio.wav" \
  -F "model=paraformer-zh" \
  -F "device=cpu"
```

> 💡 具体可用的接口与参数以服务启动后的接口为准，不同 FunASR 版本的接口略有差异
> （新版为 OpenAI 兼容接口 `/v1/audio/transcriptions`，旧版为 `/recognize`）。PWA 前端会自动探测并适配这两种接口。
> 注意：根路径 `/` 现在由 PWA 界面占用，不再返回 API 说明。

## PWA 使用说明

部署成功后，直接访问公网隧道域名即打开 PWA 语音识别界面（参考 [FunASR 官方 Demo](https://huggingface.co/spaces/funasr/demo)）：

1. **上传音频**：点击虚线框选择音频文件，或将音频拖拽到页面中（支持 wav / mp3 / m4a / ogg / flac 等）。
2. **录制音频**：点击「开始录音」使用麦克风录制，再次点击「停止录音」结束。
3. **选择模型与语言**：模型默认 `paraformer-zh`（中文标点），若服务端还加载了 `sensevoice` 等模型会自动出现在下拉框中；语言默认自动检测。
4. **转写**：点击「转写文字」，结果与耗时展示在下方，可一键复制。

PWA 特性：

- 📲 **可安装**：手机（Chrome/Edge/Safari）或桌面浏览器打开后，可通过地址栏的“安装应用”图标或页面右上角的「安装 App」按钮安装到桌面/主屏，获得独立窗口体验。
- 📴 **离线缓存**：`sw.js` 会缓存静态资源，断网时仍可打开应用（转写需要联网调用服务端）。
- 🔁 **接口自适应**：前端启动时探测 `/v1/models` 与 `/health`，自动在 OpenAI 兼容接口与旧版 `/recognize` 之间切换。

### 前端本地调试

```bash
# 用任意静态服务器托管 pwa/ 目录即可（转写请求为相对路径 /health、/v1/* 等）
cd pwa && python -m http.server 8080
```

## 运行状态说明

> ⚠️ 工作流最终显示为 **cancelled**（已取消）**属于正常现象，并非部署失败**。

原因：末尾的 `Keep runner alive` 步骤是**无限循环**，只能通过以下两种方式终止：

1. 在 Actions 页面手动 **Cancel run** 取消运行；
2. 达到 `timeout-minutes`（6 小时）上限，被平台强制终止。

因此，运行记录中**前 9 个部署步骤全部为 `success`、仅最后一个步骤被取消**，即表示部署成功。

## 注意事项

1. **Runner 生命周期限制**：GitHub runner 在任务结束后会被销毁，服务随之停止。当前方案以"无限循环保持 runner 存活"的方式运行，受平台 6 小时上限约束。
2. **源站端口不可随意改动**：隧道为远程托管（`--token`），Cloudflare 控制台的入口规则指向 `localhost:10095`。`SERVER_PORT` 必须保持 `10095`（Caddy 网关），否则隧道将无法访问服务。若需更换端口，请在 Cloudflare 控制台同步修改。
3. **生产环境建议**：如需 7×24 稳定运行，建议改用**云主机 + systemd/Docker** 托管 FunASR、Caddy 与 Cloudflare Tunnel，GitHub Actions 仅负责构建与部署。
4. **定时任务触发间隔**：GitHub 官方要求 cron 任务的最小间隔为 5 分钟，本配置的 6 小时间隔远高于该限制。
5. **并发排队**：由于 `cancel-in-progress: false`，若上一个运行尚未结束，新触发的定时任务将排队等待，可能导致定时任务"实际运行时间"晚于计划时间。
6. **依赖版本未锁定**：`pip install -U` 每次安装最新版本，如需可复现的部署，建议锁定依赖版本并配合 `requirements.txt`（此时 pip 缓存 key 会基于文件 hash 自动失效）。
