#!/usr/bin/env bash
# devcontainer 首次创建后运行。目标：换一台开发机也能得到同一套环境。
set -euo pipefail

echo "==> 安装 Node 依赖"
corepack enable
pnpm install --frozen-lockfile

echo "==> 安装 Python 侧依赖（进化管线 + heavy-runner）"
pip install --quiet --user -r evolution/requirements.txt -r apps/heavy-runner/requirements.txt

echo "==> 准备本地密钥文件"
# 密钥从宿主机环境变量透传进来，不进镜像也不进仓库
if [ ! -f apps/agent-core/.dev.vars ]; then
  cp apps/agent-core/.dev.vars.example apps/agent-core/.dev.vars
  if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}|" apps/agent-core/.dev.vars
    echo "    已从宿主环境写入 ANTHROPIC_API_KEY"
  else
    echo "    ⚠ 宿主机没有 ANTHROPIC_API_KEY，请手动填 apps/agent-core/.dev.vars"
  fi
fi

echo "==> 自检"
pnpm typecheck

cat <<'TIP'

环境就绪：
  pnpm dev        本地起 Worker  → http://localhost:8787
  pnpm typecheck  全仓类型检查

密钥只存在于容器内的 .dev.vars（已 gitignore）。
TIP
