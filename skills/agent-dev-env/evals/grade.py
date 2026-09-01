#!/usr/bin/env python3
"""对 eval 产出做可程序化的断言校验。

四类断言里三类能自动判：
    command_succeeds  在产出目录跑命令，看退出码
    content_matches   某个 glob 匹配的文件里存在正则
    content_absent    都不存在正则（用来抓反模式，比正向断言更能暴露问题）
    custom            具名检查，见 CUSTOM_CHECKS

judge 类是主观判断，本脚本只列出来交给人或 LLM 评，不自动打分。

用法：
    python3 grade.py <产出目录> --eval-id greenfield-scaffold
    python3 grade.py <产出目录> --eval-id greenfield-scaffold --json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

EVALS = pathlib.Path(__file__).parent / "evals.json"


# ── custom 检查 ───────────────────────────────────────────────

def do_classname_consistent(root: pathlib.Path) -> tuple[bool, str]:
    """三环境的 DO class_name 与 migrations tag 必须一致。

    不一致会触发数据迁移 —— 这是 skill 反复强调的冻结项，
    也是最容易在「给每个环境单独写配置」时踩到的坑。
    """
    cfgs = list(root.rglob("wrangler.jsonc")) + list(root.rglob("wrangler.json"))
    if not cfgs:
        return False, "找不到 wrangler 配置"

    raw = cfgs[0].read_text(encoding="utf-8")
    stripped = re.sub(r"^\s*//.*$", "", raw, flags=re.M)
    try:
        cfg = json.loads(stripped)
    except json.JSONDecodeError as e:
        return False, f"配置不是合法 JSONC: {e}"

    def names(block: dict) -> set[str]:
        return {
            b.get("class_name", "")
            for b in (block.get("durable_objects") or {}).get("bindings", [])
        }

    top = names(cfg)
    if not top:
        return False, "顶层没有 durable_objects 绑定"

    envs = cfg.get("env") or {}
    for env_name, env_cfg in envs.items():
        got = names(env_cfg)
        # 环境块没写 durable_objects 时会继承顶层，这也是一致的
        if got and got != top:
            return False, f"env.{env_name} 的 class_name {got} 与顶层 {top} 不一致"

    return True, f"class_name 一致：{top}，覆盖环境 {list(envs) or '仅顶层'}"


CUSTOM_CHECKS = {"do_classname_consistent": do_classname_consistent}


# ── 断言执行 ─────────────────────────────────────────────────

SKIP_DIRS = {"node_modules", ".git", ".wrangler", "dist", "__pycache__", ".venv"}


def expand_braces(pattern: str) -> list[str]:
    """展开 `**/*.{ts,py}` 这类花括号 —— pathlib.glob 不支持，不展开会静默匹配 0 个文件。"""
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m:
        return [pattern]
    out = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(pattern[: m.start()] + alt.strip() + pattern[m.end():]))
    return out


def iter_files(root: pathlib.Path, glob: str):
    seen = set()
    for pat in expand_braces(glob):
        for p in root.glob(pat):
            if not p.is_file() or p in seen:
                continue
            if SKIP_DIRS & set(p.parts):
                continue
            seen.add(p)
            yield p


def run_assertion(root: pathlib.Path, a: dict) -> dict:
    kind = a.get("type")
    name = a.get("name", "?")

    if kind == "judge":
        return {"name": name, "type": kind, "passed": None,
                "evidence": "主观断言，需人工或 LLM 评判：" + a.get("criterion", "")}

    if kind == "command_succeeds":
        cmd = a["cmd"]
        try:
            r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True,
                               text=True, timeout=900)
            ok = r.returncode == 0
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
            return {"name": name, "type": kind, "passed": ok,
                    "evidence": f"`{cmd}` 退出码 {r.returncode}" +
                                (f" | {' / '.join(tail)}" if tail and not ok else "")}
        except subprocess.TimeoutExpired:
            return {"name": name, "type": kind, "passed": False, "evidence": f"`{cmd}` 超时"}

    if kind in ("content_matches", "content_absent"):
        pat = re.compile(a["pattern"])
        hits = []
        scanned = 0
        for f in iter_files(root, a["glob"]):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            if pat.search(text):
                hits.append(str(f.relative_to(root)))

        # content_absent 在没有文件可扫时会平凡通过 —— 那是假阳性，不是证据。
        # 断言必须建立在真的看过内容之上，否则空产出会拿满分。
        if kind == "content_absent" and scanned == 0:
            return {"name": name, "type": kind, "passed": False,
                    "evidence": f"glob {a['glob']} 未匹配到任何文件，无法判定（不计通过）"}

        found = bool(hits)
        ok = found if kind == "content_matches" else not found
        if kind == "content_matches":
            ev = f"命中 {hits[:3]}" if found else f"扫了 {scanned} 个文件，无一匹配 /{a['pattern']}/"
        else:
            ev = (f"扫了 {scanned} 个文件均未出现（符合预期）" if ok
                  else f"出现了不该有的模式：{hits[:3]}")
        return {"name": name, "type": kind, "passed": ok, "evidence": ev}

    if kind == "custom":
        fn = CUSTOM_CHECKS.get(a["check"])
        if not fn:
            return {"name": name, "type": kind, "passed": False,
                    "evidence": f"未知的 custom 检查 {a['check']}"}
        ok, ev = fn(root)
        return {"name": name, "type": kind, "passed": ok, "evidence": ev}

    return {"name": name, "type": kind, "passed": False, "evidence": f"未知断言类型 {kind}"}


def main() -> None:
    ap = argparse.ArgumentParser(description="校验 eval 产出")
    ap.add_argument("output_dir", help="被测 agent 的产出目录")
    ap.add_argument("--eval-id", required=True, help="evals.json 里的 id")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非可读文本")
    args = ap.parse_args()

    root = pathlib.Path(args.output_dir).resolve()
    if not root.is_dir():
        sys.exit(f"产出目录不存在：{root}")

    spec = json.loads(EVALS.read_text(encoding="utf-8"))
    ev = next((e for e in spec["evals"] if e["id"] == args.eval_id), None)
    if ev is None:
        ids = ", ".join(e["id"] for e in spec["evals"])
        sys.exit(f'没有 id 为 "{args.eval_id}" 的 eval。可选：{ids}')

    results = [run_assertion(root, a) for a in ev["assertions"]]

    if args.json:
        print(json.dumps({"eval_id": args.eval_id, "expectations": results},
                         ensure_ascii=False, indent=2))
        return

    auto = [r for r in results if r["passed"] is not None]
    passed = sum(1 for r in auto if r["passed"])
    print(f"\n{args.eval_id}  —  自动断言 {passed}/{len(auto)} 通过\n")
    for r in results:
        mark = "· 待评" if r["passed"] is None else ("✓ 通过" if r["passed"] else "✗ 未过")
        print(f"  {mark}  {r['name']}")
        print(f"          {r['evidence']}")
    if len(auto) < len(results):
        print(f"\n  另有 {len(results) - len(auto)} 条主观断言需人工/LLM 评判。")


if __name__ == "__main__":
    main()
