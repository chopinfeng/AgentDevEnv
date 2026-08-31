"""进化管线 v1：DSPy + GEPA 离线优化 MAIN_AGENT_PROMPT。

流程（由 .github/workflows/evolve.yml 定时触发）：
  1. 从 R2 拉取线上 trace（AI Gateway / Logpush 归档）+ Supabase 里的人工反馈，
     合并 evalset/ 构成训练与评估集。
  2. dspy.GEPA 反思式进化 prompt。
  3. 胜出的候选写回 packages/prompts/src/index.ts（递增版本号），以 PR 提交。
  4. PR 上的评估门禁（LLM-as-judge + 硬指标）不达标则自动关闭。

产物永不直接进生产 —— 一律走 PR + 评估 + 人工审批。
"""

import json
import pathlib

EVALSET = pathlib.Path(__file__).parent / "evalset" / "seed.jsonl"
PROMPTS_TS = pathlib.Path(__file__).parents[1] / "packages" / "prompts" / "src" / "index.ts"


def load_evalset() -> list[dict]:
    return [json.loads(line) for line in EVALSET.read_text().splitlines() if line.strip()]


def main() -> None:
    examples = load_evalset()
    print(f"loaded {len(examples)} eval examples")
    # TODO:
    #   import dspy
    #   lm = dspy.LM("anthropic/claude-sonnet-5")
    #   dspy.configure(lm=lm)
    #   optimizer = dspy.GEPA(metric=..., auto="medium")
    #   optimized = optimizer.compile(program, trainset=...)
    #   然后把 optimized prompt 写回 PROMPTS_TS 并递增版本号
    print("evolution pipeline skeleton — wire up DSPy+GEPA here")


if __name__ == "__main__":
    main()
