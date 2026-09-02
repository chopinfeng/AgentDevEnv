#!/usr/bin/env bash
# 目标机上的拉取式部署代理。
#
# 为什么是拉取而不是推送：
#   本仓库是**公开**的。GitHub 官方明确说 self-hosted runner「几乎永远不应该」
#   用在公开仓库上 —— 任何人提一个 fork PR 就能在你的机器上执行任意代码。
#   所以不要在目标机上装 runner。反过来让目标机主动拉，攻击面小得多：
#     - 只需出站连接，不开任何入站端口，NAT/防火墙后也能工作
#     - CI 里不需要存目标机的 SSH 私钥或 VPN 凭证
#     - fork PR 影响不到这台机器
#
# 用法（在目标机上）：
#   ./pull-agent.sh once          跑一次就退出（配合 cron / systemd timer）
#   ./pull-agent.sh watch         常驻轮询
#
# 需要的环境变量：
#   IMAGE       镜像地址，如 ghcr.io/<owner>/<repo>/heavy-runner
#   TAG         要跟随的 tag，默认 edge（main 分支最新）
#   GHCR_USER / GHCR_TOKEN   私有镜像才需要；公开镜像可不填
set -euo pipefail

IMAGE="${IMAGE:?需要设置 IMAGE，例如 ghcr.io/owner/repo/heavy-runner}"
TAG="${TAG:-edge}"
CONTAINER="${CONTAINER:-heavy-runner}"
PORT="${PORT:-8080}"
INTERVAL="${INTERVAL:-60}"
STATE_FILE="${STATE_FILE:-$HOME/.heavy-runner-digest}"

log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

login_if_needed() {
  if [ -n "${GHCR_TOKEN:-}" ]; then
    echo "$GHCR_TOKEN" | docker login ghcr.io -u "${GHCR_USER:?私有镜像需要 GHCR_USER}" --password-stdin >/dev/null
  fi
}

# 用 digest 而不是 tag 判断是否有新版本 —— tag 会被覆盖，digest 不会
remote_digest() {
  docker manifest inspect "$IMAGE:$TAG" 2>/dev/null \
    | sha256sum | cut -d' ' -f1
}

deploy_once() {
  login_if_needed

  local remote current
  remote="$(remote_digest)" || { log "拉取 manifest 失败，跳过本轮"; return 0; }
  current="$(cat "$STATE_FILE" 2>/dev/null || true)"

  if [ "$remote" = "$current" ]; then
    log "已是最新（$TAG），无需动作"
    return 0
  fi

  log "发现新版本，开始更新"
  docker pull "$IMAGE:$TAG"

  # 先起新的再停旧的，减少不可用窗口；失败则保留旧容器
  local new="${CONTAINER}-new"
  docker rm -f "$new" 2>/dev/null || true
  docker run -d --name "$new" \
    --env-file "${ENV_FILE:-$HOME/heavy-runner.env}" \
    -p "$((PORT + 1)):8080" \
    --restart unless-stopped \
    "$IMAGE:$TAG"

  log "健康检查新容器"
  local ok=0
  for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$((PORT + 1))/health" >/dev/null 2>&1; then ok=1; break; fi
    sleep 2
  done

  if [ "$ok" -ne 1 ]; then
    log "❌ 新版本健康检查未通过，回滚：保留旧容器，删除新容器"
    docker logs --tail 30 "$new" || true
    docker rm -f "$new" >/dev/null 2>&1 || true
    return 1
  fi

  log "健康检查通过，切换流量"
  docker rm -f "$CONTAINER" 2>/dev/null || true
  docker rm -f "$new" >/dev/null
  docker run -d --name "$CONTAINER" \
    --env-file "${ENV_FILE:-$HOME/heavy-runner.env}" \
    -p "$PORT:8080" \
    --restart unless-stopped \
    "$IMAGE:$TAG"

  echo "$remote" > "$STATE_FILE"
  log "✅ 已更新到 $IMAGE:$TAG"
  docker image prune -f >/dev/null 2>&1 || true
}

case "${1:-once}" in
  once)  deploy_once ;;
  watch) log "开始轮询，每 ${INTERVAL}s 一次"; while true; do deploy_once || true; sleep "$INTERVAL"; done ;;
  *)     echo "用法: $0 [once|watch]" >&2; exit 2 ;;
esac
