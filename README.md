# funasr-api

基于 **FunASR** 的中文语音识别（ASR）API 部署项目。通过 GitHub Actions 自动部署 FunASR 语音识别服务，并借助 **Cloudflare Tunnel** 将服务暴露到公网，支持手动触发和定时自动运行。

---

## 目录

- [项目结构](#项目结构)
- [功能特性](#功能特性)
- [工作原理](#工作原理)
- [工作流配置说明](#工作流配置说明)
- [环境变量与密钥](#环境变量与密钥)
- [API 使用说明](#api-使用说明)
- [运行状态说明](#运行状态说明)
- [注意事项](#注意事项)

---

## 项目结构

```
funasr-api/
├── .github/
│   └── workflows/
│       └── funasr.yml   # GitHub Actions 部署工作流
└── README.md            # 项目说明文档
```

## 功能特性

- 🤖 自动部署 FunASR 语音识别服务（`paraformer-zh` 中文识别模型）
- 🌐 通过 Cloudflare Tunnel 提供公网访问，无需固定公网 IP
- ⏰ 支持手动触发与每 6 小时定时自动运行
- 🚀 pip 依赖缓存，加速重复部署

## 工作原理

整个部署流程运行在 GitHub Actions 的 `ubuntu-22.04` runner 上：

```
GitHub Actions Runner
    │
    ├── 启动 FunASR 服务（127.0.0.1:10095，paraformer-zh 模型）
    │        │
    │        └── Cloudflare Tunnel（cloudflared）反向代理
    │                 │
    │                 └── 公网域名访问服务
    │
    └── Keep runner alive（无限循环，保持服务持续运行）
```

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

### 部署流程（7 个步骤）

| 步骤 | 名称 | 作用 |
|------|------|------|
| 1 | Set up Python | 配置 Python 3.10 环境 |
| 2 | Cache pip dependencies | 缓存 pip 下载的依赖包，加速安装 |
| 3 | Install dependencies | 安装 `funasr`、`torch`、`torchaudio`、`modelscope`、`uvicorn`、`fastapi`、`python-multipart` |
| 4 | Start FunASR server | 后台启动 FunASR 服务（CPU 推理，`paraformer-zh` 模型，模型从 HuggingFace 下载），并轮询健康检查等待就绪 |
| 5 | Install cloudflared | 下载并安装 Cloudflare Tunnel 客户端 |
| 6 | Start cloudflared tunnel | 使用 Token 启动隧道，将本地服务暴露到公网 |
| 7 | Keep runner alive | 无限循环保持 runner 存活，从而维持服务持续运行 |

### 关键配置项

| 配置 | 当前值 | 说明 |
|------|--------|------|
| `runs-on` | `ubuntu-22.04` | 运行环境 |
| `timeout-minutes` | `360` | 任务超时上限（6 小时），超过后平台强制终止 |
| `SERVER_PORT` | `10095` | FunASR 服务监听端口 |
| `SERVER_HEALTH_URL` | `http://127.0.0.1:10095/health` | 健康检查地址 |
| 模型 | `paraformer`（HuggingFace） | 中文语音识别模型，`--model paraformer` |
| 健康检查轮询 | 60 次 × 5 秒 | 最长等待约 5 分钟 |

## 环境变量与密钥

| 名称 | 类型 | 位置 | 说明 |
|------|------|------|------|
| `SERVER_PORT` | 工作流变量 | 工作流 `env` | FunASR 服务端口（默认 `10095`） |
| `SERVER_HEALTH_URL` | 工作流变量 | 工作流 `env` | 健康检查地址 |
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

> 💡 具体可用的接口与参数以服务启动后访问根路径 `/` 返回的接口说明为准，不同 FunASR 版本的接口略有差异。

## 运行状态说明

> ⚠️ 工作流最终显示为 **cancelled**（已取消）**属于正常现象，并非部署失败**。

原因：末尾的 `Keep runner alive` 步骤是**无限循环**，只能通过以下两种方式终止：

1. 在 Actions 页面手动 **Cancel run** 取消运行；
2. 达到 `timeout-minutes`（6 小时）上限，被平台强制终止。

因此，运行记录中**前 6 个部署步骤全部为 `success`、仅最后一个步骤被取消**，即表示部署成功。

## 注意事项

1. **Runner 生命周期限制**：GitHub runner 在任务结束后会被销毁，服务随之停止。当前方案以"无限循环保持 runner 存活"的方式运行，受平台 6 小时上限约束。
2. **生产环境建议**：如需 7×24 稳定运行，建议改用**云主机 + systemd/Docker** 托管 FunASR 与 Cloudflare Tunnel，GitHub Actions 仅负责构建与部署。
3. **定时任务触发间隔**：GitHub 官方要求 cron 任务的最小间隔为 5 分钟，本配置的 6 小时间隔远高于该限制。
4. **并发排队**：由于 `cancel-in-progress: false`，若上一个运行尚未结束，新触发的定时任务将排队等待，可能导致定时任务"实际运行时间"晚于计划时间。
5. **依赖版本未锁定**：`pip install -U` 每次安装最新版本，如需可复现的部署，建议锁定依赖版本并配合 `requirements.txt`（此时 pip 缓存 key 会基于文件 hash 自动失效）。
