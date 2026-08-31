"""重执行层：跑 Python / 长驻进程系框架的容器服务。

部署目标：Cloudflare Containers（首选）或阿里云 FC / ACK（兜底）。

与边缘侧对称的框架 seam：边缘的 remote 适配器把一轮对话 POST 到 /turn，
这里按 framework 字段分发给具体实现。换框架 = 换 framework 值，
契约（/turn 的请求与响应形状）不变，因此 Worker、wrangler.jsonc、CI 全都不动。

契约定义见 packages/agent-kernel/src/types.ts。
"""

from typing import Callable, Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="heavy-runner")


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    ts: int = 0


class TurnRequest(BaseModel):
    framework: str
    session_id: str
    message: str
    history: list[Message] = []
    memory: str = ""


class TurnResponse(BaseModel):
    reply: str
    memory: str | None = None


# ── 框架实现：签名一致，可自由增删 ────────────────────────────

def run_langgraph(req: TurnRequest) -> TurnResponse:
    # TODO: 构建 LangGraph 图，用 req.history / req.memory 驱动
    raise NotImplementedError("langgraph 适配器待接线")


def run_claude_code(req: TurnRequest) -> TurnResponse:
    # TODO: 调用 Claude Agent SDK（需完整 Node/Linux 环境，建议跑在 Sandbox 内）
    raise NotImplementedError("claude-code 适配器待接线")


def run_pi(req: TurnRequest) -> TurnResponse:
    # TODO: 调用 Pi coding agent
    raise NotImplementedError("pi 适配器待接线")


FRAMEWORKS: dict[str, Callable[[TurnRequest], TurnResponse]] = {
    "langgraph": run_langgraph,
    "claude-code": run_claude_code,
    "pi": run_pi,
}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "frameworks": sorted(FRAMEWORKS)}


@app.post("/turn", response_model=TurnResponse)
def turn(req: TurnRequest) -> TurnResponse:
    handler = FRAMEWORKS.get(req.framework)
    if handler is None:
        raise ValueError(
            f'未知框架 "{req.framework}"。可选：{", ".join(sorted(FRAMEWORKS))}'
        )
    return handler(req)
