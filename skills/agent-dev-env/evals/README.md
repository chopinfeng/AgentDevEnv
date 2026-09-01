# evals

两套评测，回答两个不同的问题。

| | 问什么 | 文件 |
|---|---|---|
| **任务 eval** | skill 触发之后，产出是否更好？ | `evals.json` + `grade.py` |
| **触发 eval** | skill 该触发时会触发吗？不该时会误触发吗？ | `trigger-evals.json` + `run_trigger_evals.sh` |

两者独立：description 写得再好，内容不行也没用；内容再好，不触发等于不存在。

## 任务 eval

5 条用例覆盖：新建项目脚手架、知识库权限边界、设备边界、上线前检查、自我改进的顺序纪律。

跑法：把同一条 prompt 分别交给**有 skill** 和**无 skill** 两个全新会话，产出写到各自目录，然后评分：

```bash
python3 grade.py <产出目录> --eval-id greenfield-scaffold
python3 grade.py <产出目录> --eval-id greenfield-scaffold --json   # 供聚合
```

基线必须是全新会话——写 skill 时残留的上下文会掩盖指令本身的缺口。

### 断言类型

`grade.py` 自动判三类，第四类交给人或 LLM：

| 类型 | 说明 |
|---|---|
| `command_succeeds` | 在产出目录跑命令看退出码。用于「骨架能不能构建」这类硬指标 |
| `content_matches` | glob 匹配的文件里存在正则 |
| `content_absent` | 都不存在正则。**用来抓反模式**，比正向断言更能暴露问题 |
| `custom` | 具名检查，见 `grade.py` 的 `CUSTOM_CHECKS` |
| `judge` | 主观，脚本只列出不打分 |

### 怎么看结果

**关键不是通过率高，是断言有没有区分度。**

- 两种配置都通过的断言 → **删掉换一条**。它不区分能力，只是虚高了有 skill 那组的分数
- 两种配置都失败 → 断言写坏了或用例太难，修断言
- 只有有 skill 那组通过 → **这就是 skill 的价值所在**，搞清楚为什么，别动它
- 波动大 → 用例 flaky 或指令有歧义

自检过：脚手架产出 5/5 通过，故意违反每条冻结项的反例 0/5，且能指出是哪个环境的 class_name 不一致。断言确实在判断，不是永远返回通过。

## 触发 eval

20 条，正例负例各 10。

```bash
./run_trigger_evals.sh              # 每条 3 次，取触发率，阈值 0.5
RUNS=1 ./run_trigger_evals.sh       # 快速冒烟
```

需要 `claude` CLI 与 `jq`。脚本把 skill 复制到临时目录的 `.claude/skills/`，用 `claude -p` 跑每条 query，从 stream-json 里找 Skill 工具调用。

**为什么每条跑多次**：模型有随机性，单次结果不可靠。

### 负例必须是「近似误判」

这一点决定了触发 eval 有没有用。负例要共享关键词但真实需求不同——比如「帮我写一个 MCP server」（MCP 但该让 mcp-builder 胜出）、「帮我搭 React 脚手架」（脚手架但与 agent 无关）、「我的 ESP32 连不上 WiFi」（ESP32 但是硬件调试）。

**明显无关的负例没有测试价值**。给这个 skill 写「帮我写个快排」当负例，测不出任何东西。

### 改 description 的原则

不要把失败 query 里的关键词直接塞进 description——那是过拟合。找到那类 query 代表的**概念范畴**，再用一句话表达。

另外注意：description 超长时是**从尾部截断**的，所以最关键的用例要放第一句。

## 扩展

加任务用例：在 `evals.json` 的 `evals` 数组里加一条，断言尽量用可程序化的三类。需要新的结构化检查就在 `grade.py` 的 `CUSTOM_CHECKS` 里加函数。

加触发用例：在 `trigger-evals.json` 里加。**正负例保持大致均衡**，且负例优先补近似误判。
