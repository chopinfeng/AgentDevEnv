"""AgentDevEnv —— 树莓派本地 Agent host。

与 ESP32 的定位差别：Pi 5（8–16 GB）算力足够跑 Agent 循环本身，
所以它既可以当设备（暴露 GPIO/摄像头等能力），也可以当本地 host。

关于本地推理的实测边界（2026-08 核实，Ollama on Pi 5）：
    Gemma3:1b   ~12 tok/s
    Qwen2.5:1.5b ~10 tok/s
    3B 类模型    4–6 tok/s，且长 prompt（5000+ token）场景会超时

结论：**本地模型只适合窄任务**（唤醒词后的意图分类、离线兜底应答），
Agent 主推理仍应走云端。这个脚本默认走云，local 模式仅作离线降级。
AI HAT+ 2（40 TOPS / 8 GB 独立 RAM / 支持 1–7B）是值得跟踪的变量，
但官方未公布 token/s，上线前必须自行实测。

用法：
    python agent_host.py --mode device      # 当设备：暴露 Pi 的能力给云端 Agent
    python agent_host.py --mode local       # 离线兜底：本地 Ollama 跑窄任务
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess

import websockets

AGENT_WS = "wss://api.yourdomain.com/agents/main-agent/home"
DEVICE_ID = "pi-01"

# ── 设备模式：把 Pi 的本地能力暴露成工具 ──────────────────────

TOOLS = [
    {
        "name": "system_stats",
        "description": "读取本机 CPU 温度、内存占用与运行时长。",
        "schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_shell",
        "description": "在本机执行一条只读 shell 命令并返回输出。仅限白名单命令。",
        "schema": {
            "type": "object",
            "properties": {"cmd": {"type": "string"}},
            "required": ["cmd"],
        },
    },
]

# 白名单：设备工具直接暴露 shell 是高风险面，只放只读命令。
# 云端 Agent 不可信 —— 它的输入可能来自任意用户。
SHELL_ALLOW = {"uptime", "df", "free", "vcgencmd", "hostname", "vmstat"}


def system_stats() -> str:
    parts = []
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            parts.append(f"CPU 温度 {int(f.read()) / 1000:.1f}°C")
    except OSError:
        pass
    try:
        parts.append(subprocess.run(["uptime"], capture_output=True, text=True, timeout=5).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return " | ".join(parts) or "读取失败"


def run_shell(cmd: str) -> tuple[bool, str]:
    argv = cmd.split()
    if not argv:
        return False, "空命令"
    if argv[0] not in SHELL_ALLOW:
        return False, f"命令 {argv[0]} 不在白名单内。允许：{', '.join(sorted(SHELL_ALLOW))}"
    if shutil.which(argv[0]) is None:
        return False, f"本机没有 {argv[0]}"
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return True, (r.stdout or r.stderr).strip()[:2000]
    except subprocess.SubprocessError as e:
        return False, str(e)


def dispatch(tool: str, args: dict) -> tuple[bool, str]:
    if tool == "system_stats":
        return True, system_stats()
    if tool == "run_shell":
        return run_shell(str(args.get("cmd", "")))
    return False, f"unknown tool {tool}"


async def run_device() -> None:
    """min 方言，与 ESP32 固件同一套协议。"""
    url = f"{AGENT_WS}?role=device&dialect=min&device={DEVICE_ID}"

    async for ws in websockets.connect(url, ping_interval=20):
        try:
            await ws.send(json.dumps({"t": "hello", "device": DEVICE_ID, "tools": TOOLS}))
            print(f"[device] connected as {DEVICE_ID}, {len(TOOLS)} tools")

            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("t") != "invoke":
                    continue
                ok, data = dispatch(msg["tool"], msg.get("args") or {})
                await ws.send(json.dumps({"t": "result", "id": msg["id"], "ok": ok, "data": data}))

        except websockets.ConnectionClosed:
            print("[device] disconnected, reconnecting…")
            continue


# ── 本地模式：离线窄任务兜底 ──────────────────────────────────

async def run_local(prompt: str) -> None:
    """本地 Ollama。仅用于断网时的窄任务，不要指望它做工具调用。"""
    if shutil.which("ollama") is None:
        raise SystemExit("未安装 ollama。参考 https://ollama.com/download/linux")

    r = subprocess.run(
        ["ollama", "run", "qwen2.5:1.5b", prompt],
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(r.stdout.strip() or r.stderr.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description="Raspberry Pi agent host")
    ap.add_argument("--mode", choices=["device", "local"], default="device")
    ap.add_argument("--prompt", default="用一句话自我介绍", help="local 模式的输入")
    args = ap.parse_args()

    if args.mode == "device":
        asyncio.run(run_device())
    else:
        asyncio.run(run_local(args.prompt))


if __name__ == "__main__":
    main()
