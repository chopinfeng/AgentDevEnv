# 多主机部署拓扑

开发在一台机器、构建在另一台、运行在第三台——这三件事常被混为一谈，分开看才有清晰的选择。

## 三条独立的轴

| 轴 | 选项 | 本仓库现状 |
|---|---|---|
| **开发在哪** | 本地 / devcontainer / 远程工作站 | `.devcontainer/` 保证换机器环境一致 |
| **构建在哪** | GitHub 托管 runner / self-hosted runner | 全部用托管 runner |
| **运行在哪** | 公有云 API / 镜像仓库 / 内网机器 / 设备 | Workers 推送；容器与设备见下 |

混淆的代价：以为「部署到内网」就必须把 runner 装进内网，于是在公开仓库上装了 self-hosted runner——那是个严重的安全洞。

## 交付方式：推 还是 拉

这是整套拓扑里最关键的一个决定。

**推模型**：CI 主动连到目标机（SSH、云 API）。
需要 CI 持有目标机凭证，且目标机对 CI 可达。适合有公开 API 的托管平台。

**拉模型**：目标机主动拉新版本。
CI 只把产物推到镜像仓库，够不着也不需要够着目标机。

| | 推 | 拉 |
|---|---|---|
| 目标机在 NAT/防火墙后 | 要开入站或打隧道 | **直接可用**，只需出站 |
| CI 里的凭证 | 需要 SSH 私钥 / VPN 凭证 | 不需要 |
| 公开仓库的 fork PR 风险 | self-hosted runner 会被攻击 | **影响不到目标机** |
| 部署时机 | 即时 | 有轮询延迟（本仓库默认 5 分钟） |

## ⚠️ 公开仓库不要用 self-hosted runner

GitHub 官方明确说 self-hosted runner「几乎永远不应该」用于公开仓库：任何人 fork 后提一个 PR，就能在你的机器上执行任意代码，并拿到该 runner 能访问的一切——密钥、内网、`GITHUB_TOKEN`。

> Self-hosted runners should almost never be used for public repositories on GitHub, because any user can open pull requests against the repository and compromise the environment.
> —— [GitHub Docs, Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)

私有仓库也要小心：任何有读权限、能 fork 并提 PR 的人同样能拿到 runner 环境。

**本仓库是公开的，所以默认走拉模型。**

## 本仓库的三条部署路径

### 1. 边缘 Worker → Cloudflare（推）

`deploy-staging.yml` / `deploy-prod.yml`。托管 runner 调 Cloudflare API，不涉及私有网络，公开仓库安全。

**这条路必然有一枚长期密钥。** Cloudflare 至今不支持 GitHub Actions OIDC 免密钥部署——[相关请求](https://github.com/cloudflare/workers-sdk/discussions/11434)自 2025-11 提出至今无官方回应，wrangler 仍只接受 `CLOUDFLARE_API_TOKEN`。

所以这枚 token 的存放位置是整套拓扑里最敏感的一点：

- 只放 **GitHub Environment secrets**，配上必需审批与分支限制
- **绝不能出现在 self-hosted runner 能触达的 job 里**——否则公开仓库的 fork PR 风险会直接放大成 Cloudflare 账号被接管
- 用 Custom token 模板把权限收到最小，账号范围也收到最小

> 若要部署 Cloudflare Containers：镜像构建默认捆绑在 `wrangler deploy` 里且**需要本地 Docker**。CI 里改用 `wrangler containers build --push` 把构建与部署拆开；或者让配置里的 `image` 直接指向已推送的 registry 引用，那样部署时不需要 Docker。

### 2. heavy-runner 容器 → 任意机器（拉）

```
GitHub 托管 runner              目标机（内网 / 家里 / 云上都行）
──────────────────              ────────────────────────────────
build-container.yml
  构建镜像
  推到 GHCR            ────►    pull-agent.sh（systemd timer 每 5 分钟）
  （GITHUB_TOKEN 认证）           比对 digest → 有新版本才动
                                 起新容器 → 健康检查 → 通过才切流量
                                 不通过则保留旧容器并报错
```

目标机上安装：

```bash
sudo cp deploy/pull-agent.sh /usr/local/bin/
sudo cp deploy/heavy-runner.{service,timer} /etc/systemd/system/
sudo tee /etc/heavy-runner.conf >/dev/null <<'EOF'
IMAGE=ghcr.io/<owner>/AgentDevEnv/heavy-runner
TAG=edge
ENV_FILE=/etc/heavy-runner.env
EOF
sudo systemctl enable --now heavy-runner.timer
```

要点：
- **按 digest 比对而不是 tag**——tag 会被覆盖，digest 不会，避免重复部署或漏部署
- **健康检查不过就保留旧容器**，宁可停留在旧版本也不要挂掉
- `TAG=edge` 跟随 main，生产建议钉具体版本（`TAG=1.4.0`），升级时改配置

### 3. 设备（ESP32 / 树莓派）

树莓派可以直接复用上面的拉取代理（它就是一台 Linux 机器）。

ESP32 的固件更新是另一回事，**本仓库尚未实现**。但机制是现成的，ESP-IDF 一等公民支持：

- **双 app 分区**（ota_0 / ota_1）+ otadata；启用回滚时分区表不应含 factory 分区
- 新固件写入非活动分区，`esp_ota_set_boot_partition()` 切换启动分区
- **回滚**由 `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` 启用：新固件首次启动被标记并监控，应用自检通过后要主动确认，否则 bootloader 自动回退到上一个可用版本
- **防回滚**用 `CONFIG_BOOTLOADER_APP_SECURE_VERSION`（注意：仅在 eFuse 编码方案为 NONE 时有效）

社区已有把 **GitHub Releases 当固件分发源**的成熟做法（`esp-github-ota`），推 tag 即构建发布，设备自行拉取——和上面容器的拉模型是同一个思路。

## 折中：让托管 runner 临时进内网

如果确实想要推模型的即时反馈，又不愿在目标机开入站端口，可以让 GitHub 托管 runner 在 job 内临时加入一个覆盖网络（如 Tailscale 的 ephemeral auth key，跑完自动清理节点），再照常 SSH 过去。

代价：**凭据仍然在 CI 侧**，这一点没有改善。它解决的是网络可达性，不是凭据集中风险。

（Cloudflare Tunnel 解决的是另一个问题——把内网 HTTP 服务发布到公网。可以组合但不是部署通道。）

## 如果仓库是私有的

那 self-hosted runner 是可选项，`deploy-selfhosted.yml.example` 是模板（去掉 `.example` 启用）。它的防护：没有 `pull_request` 触发器、只接受 tag/commit 不接受分支名、绑定 environment 可加人工审批。

即便如此，拉模型在多数情况下仍然更省事——不用在目标机上维护 runner 进程。

## 开发环境可移植

`.devcontainer/` 让任意一台机器得到同一套环境（Node 22 + Python 3.12 + Docker + gh）。密钥从宿主机环境变量透传，不进镜像也不进仓库。

VS Code / Cursor 打开仓库时会提示「Reopen in Container」；也可以用 GitHub Codespaces。
