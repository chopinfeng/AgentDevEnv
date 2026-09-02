# 多主机拓扑：开发、构建、运行分处三台机器

「部署」常被默认成「CI 连到目标机执行命令」。一旦目标机在内网、或有多个异构目标（边缘 + 容器 + 设备），这个默认就不成立了。

## 先把三条轴拆开

| 轴 | 选项 |
|---|---|
| 开发在哪 | 本地 / devcontainer / 远程工作站 |
| 构建在哪 | 托管 runner / self-hosted runner |
| 运行在哪 | 公有云 API / 镜像仓库 / 内网机器 / 设备 |

混淆的典型代价：以为「部署到内网」就必须把 CI runner 装进内网。那是个可以避免的安全洞。

## 关键决定：推 还是 拉

**推模型** —— CI 主动连到目标机（SSH、云 API）。要求 CI 持有目标机凭证，且目标机对 CI 可达。

**拉模型** —— 目标机主动拉新版本。CI 只把产物推到镜像仓库或 release，够不着目标机也不需要够着。

| | 推 | 拉 |
|---|---|---|
| 目标机在 NAT/防火墙后 | 要开入站或打隧道 | **只需出站即可** |
| CI 里的凭证 | 需要 SSH 私钥 / VPN 凭证 | 不需要 |
| 目标机数量增长 | 每台都要配可达性 | 每台自己拉，天然水平扩展 |
| 部署时机 | 即时 | 有轮询延迟 |

**默认选拉模型**，除非目标是有公开 API 的托管平台（那种情况推更直接）。

## ⚠️ 公开仓库不要用 self-hosted runner

这条是硬约束，不是偏好。GitHub 官方：

> Self-hosted runners should almost never be used for public repositories on GitHub, because any user can open pull requests against the repository and compromise the environment.
> —— https://docs.github.com/en/actions/reference/security/secure-use

任何人 fork 后提一个 PR，就能在你的机器上执行任意代码，拿到该 runner 能访问的一切：密钥、内网、`GITHUB_TOKEN`。

私有仓库也要小心——任何有读权限、能 fork 并提 PR 的人同样能拿到 runner 环境。

**所以：公开仓库 + 内网目标 = 必须用拉模型。** 这不是权衡，是唯一安全解。

## 拉模型的实现要点

无论用什么工具，这几条决定了它是否可靠：

**按 digest 比对，不按 tag。** tag 会被覆盖（`edge`、`latest` 尤其），digest 不会。用 tag 判断新旧会导致重复部署或漏部署。

**先起新实例做健康检查，通过了再切流量。** 检查不过就保留旧版本——宁可停在旧版本，也不要把服务弄挂。

**健康检查失败时不要更新状态记录**，否则下一轮会以为已经部署成功而跳过重试。

**单次拉取失败不中断轮询。** 网络抖动是常态，一次失败就退出会让机器永久停在旧版本。

**生产钉具体版本，不要跟随浮动 tag。** 跟 `edge` 意味着 main 一合并就自动上生产，绕过了所有门禁。

## 密钥放在哪，比用什么工具更重要

托管平台的部署往往必须持有一枚长期密钥（例如 Cloudflare 至今不支持 GitHub Actions OIDC，wrangler 只接受 API Token）。既然躲不掉，就要管住它的暴露面：

- 放 **Environment secrets**，配必需审批与分支限制，而不是仓库级 secrets
- **绝不让它出现在 self-hosted runner 能触达的 job 里**——公开仓库的 fork PR 风险会直接放大成云账号被接管
- token 权限与账号范围都收到最小

支持 OIDC 的目标（AWS / Azure / GCP / Vault）就用 OIDC：短期 JWT 按次签发，绑定到 repo、分支、environment，CI 里不存长期密钥。需要在 job 上显式声明：

```yaml
permissions:
  id-token: write
  contents: read      # 设了 permissions 会覆盖默认值，要显式写出
```

## 各层的部署路径

| 层 | 产物 | 交付 | 说明 |
|---|---|---|---|
| 边缘 Worker | bundle | 推 | 托管平台有公开 API，CI 直接调 |
| 容器（Python 框架等） | 镜像 | 拉 | 推到镜像仓库，目标机定时拉 |
| 树莓派 | 镜像 | 拉 | 就是一台 Linux 机器，复用同一套 |
| MCU 固件 | 二进制 | 拉 | 双 app 分区 + 回滚，见下 |

**容器层最容易被漏掉。** 边缘部署有现成的 action 一行搞定，于是容器层常常停留在「本地 docker build」阶段，直到上生产才发现没有路径。

MCU 固件的 OTA 不用自己发明：ESP-IDF 提供双 app 分区（ota_0/ota_1）+ otadata，`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` 启用后，新固件首次启动需应用自检确认，否则 bootloader 自动回退。把 GitHub Releases 当分发源、设备自行拉取，是社区成熟做法——和容器的拉模型同构。

## 单机场景没有事实标准

Argo CD 与 Flux 都是 CNCF 毕业项目，但它们是 **Kubernetes 世界的答案**，对「一台内网服务器」过重。

非 K8s 的单机/小团队层缺少统治级方案，只能取舍：Coolify、Dokploy（都是 Docker 之上的面板）、Komodo（偏多主机巡检，agent 出站连中心）、或者就是一个定时拉取脚本 + systemd timer。

**不要用「盯 `:latest` 自动升级」当生产方案**——升级不可控且不可审阅。更稳的模式是把镜像 tag 钉到具体版本，用依赖更新机器人（如 Renovate）自动开 PR，让「升级」变成一次显式的 Git 变更，再由部署代理落地。

## 开发环境可移植

用 devcontainer 把开发环境固化，换机器不用重新配。要点：

- 密钥从宿主机环境变量透传，**不进镜像也不进仓库**
- `postCreateCommand` 里跑一次类型检查，环境坏了当场就知道
- 转发端口带上标签，多个服务时不用猜

这解决的是「在我机器上是好的」——因为大家的机器变成同一台了。
