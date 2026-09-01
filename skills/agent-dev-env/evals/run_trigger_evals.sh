#!/usr/bin/env bash
# 触发 eval：检验 description 能否在该触发时触发、不该触发时不触发。
#
# 原理：把 skill 装进一个临时工作目录的 .claude/skills/，用 claude -p 跑每条 query，
# 从 stream-json 里找 Skill 工具调用。
#
# 注意用 stream-json 而不是 json —— 后者只给汇总（cost/usage），
# 不含工具调用记录，检测不到触发。
#
# 每条跑 N 次取触发率（模型有随机性，单次结果不可靠），阈值 0.5。
#
# 用法：
#   ./run_trigger_evals.sh                  # 默认每条跑 3 次
#   RUNS=1 ./run_trigger_evals.sh           # 快速冒烟
#   MODEL=claude-sonnet-5 ./run_trigger_evals.sh

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$HERE")"
SKILL_NAME="$(basename "$SKILL_DIR")"
RUNS="${RUNS:-3}"
MODEL="${MODEL:-}"

command -v claude >/dev/null || { echo "需要 claude CLI"; exit 1; }
command -v jq >/dev/null || { echo "需要 jq"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/.claude/skills"
cp -r "$SKILL_DIR" "$WORK/.claude/skills/$SKILL_NAME"

total=0; correct=0
declare -a FAILS=()

# 逐条读取，避免把整个 JSON 塞进内存
while IFS=$'\t' read -r query should covers; do
  hits=0
  for _ in $(seq 1 "$RUNS"); do
    # </dev/null 是必须的 —— 否则 claude 会吃掉本循环的 stdin，导致只跑第一条
    fired="$(cd "$WORK" && claude -p "$query" \
              --output-format stream-json --verbose \
              ${MODEL:+--model "$MODEL"} \
              --max-turns 2 </dev/null 2>/dev/null \
            | jq -rc 'select(.type=="assistant") | .message.content[]?
                      | select(.type=="tool_use" and .name=="Skill") | .input.skill' 2>/dev/null \
            | grep -Fx "$SKILL_NAME" | head -1)"
    [ -n "$fired" ] && hits=$((hits + 1))
  done

  rate=$(awk -v h="$hits" -v r="$RUNS" 'BEGIN{printf "%.2f", h/r}')
  triggered=$(awk -v x="$rate" 'BEGIN{print (x>=0.5)?"true":"false"}')
  total=$((total + 1))

  if [ "$triggered" = "$should" ]; then
    correct=$((correct + 1))
    printf '  ✓ %-5s %s  %s\n' "$rate" "$([ "$should" = true ] && echo 正例 || echo 负例)" "${query:0:44}"
  else
    printf '  ✗ %-5s %s  %s\n' "$rate" "$([ "$should" = true ] && echo 正例 || echo 负例)" "${query:0:44}"
    FAILS+=("[$covers] $query")
  fi
done < <(jq -r '.evals[] | [.query, (.should_trigger|tostring), .covers] | @tsv' "$HERE/trigger-evals.json")

echo
echo "触发准确率：$correct/$total（每条 $RUNS 次，阈值 0.5）"

if [ ${#FAILS[@]} -gt 0 ]; then
  echo
  echo "判错的用例——改 description 时优先看这些："
  printf '  - %s\n' "${FAILS[@]}"
  echo
  echo "改 description 的原则：不要把失败 query 里的关键词直接塞进去（会过拟合），"
  echo "找到那类 query 代表的概念范畴，再用一句话表达。"
fi
