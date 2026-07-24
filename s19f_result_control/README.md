# s19f: Result Control — 收敛结果，验证收尾

[中文](README.md) · [English](README.en.md)

s01 → ... → s19 → s19b → s19c → s19d → s19e → `s19f` → [s20](../s20_comprehensive/)

> *"收敛结果，验证收尾"* — 大结果压成一句、截图只回路径、错误稳定化；再用 Observe→Act→Verify 把整个 Unity Agent 串起来。
>
> **Harness 层（s19 分支）**: 结果与上下文控制 —— 支线的收官章。

---

## 问题

s19e 管住了危险操作。最后一道坎在**返回值**。Unity 工具的 `CallToolResult` 可能带：

- 几万行的 Hierarchy JSON；
- 几百 KB 的截图 base64；
- 一大坨结构化 `structuredContent`。

原样塞进 LLM 上下文，一次调用就把 token 预算烧穿。这是 s08 上下文管理的延伸：**外部结果必须先收敛，再进上下文。**

而且这是**收官章**——前面五章（真异步客户端、动态发现、复用 loop、外部权限）攒的零件，要在这里拼成一个"config 驱动、skill 引导、Observe→Act→Verify"的完整 Unity Agent。

---

## 解决方案

### 结果收敛四件事

```
CallToolResult
  ├─ text block        → 原样取文本
  ├─ image block       → [image omitted: png, ~200000 chars]  ← 绝不回 base64
  ├─ structuredContent → 紧凑 JSON（无文本时兜底）
  └─ 整体              → 截断到 MAX_RESULT_CHARS，留清晰标记
  isError=True         → [unity-tool-error] tool=... : ... 稳定字符串
```

一句话：`CallToolResult` → **一个紧凑字符串**，图片只留元数据，超长截断，错误可预测。

### Observe → Act → Verify

```
  Observe            Act               Verify
  ────────           ────              ──────────────────
  读 editor state    建 Cube           等编译结束 (is_compiling=false)
  读 active scene    设 position       读 Console error 数
  读 Hierarchy       加 Rigidbody      重读被改对象
  读 Console(基线)   赋红色材质         必要时截图 / 存场景
```

这是**提示层的默认节奏**（写在 skill 里），不是硬编码状态机——模型自己决定何时观察、何时验证。本章提供两个小助手让常见验证一行搞定。

---

## 工作原理

### 截图只回路径，base64 绝不进上下文

```python
def _stringify_block(block):
    if hasattr(block, "text"):
        return str(block.text)
    if hasattr(block, "data"):                       # image / audio
        size = len(block.data or "")
        return f"[image omitted: {block.mimeType}, ~{size} base64 chars — not sent]"
    return str(block)
```

demo 里一张 ~200 KB 的假截图，输出只剩一行元数据，`base64 present? False`。真实截图走 `manage_camera`，返回**文件路径**（`Assets/Screenshots/...png`）——模型对路径推理，需要看图再单独用看图工具，绝不把 base64 灌进上下文。

### 截断 + 稳定错误

```python
def _truncate(text, limit=MAX_RESULT_CHARS):
    if len(text) <= limit: return text
    return text[:limit] + f"\n...[truncated {len(text)-limit} chars — narrow the query or page]"

def format_error(tool_name, exc, hint=""):
    return f"[unity-tool-error] tool={tool_name} type={type(exc).__name__}: {exc}. {hint}"
```

错误里必带**工具名 + 错误类型 + 可执行建议**，而不是一句 "Error"。模型据此能自我修复（"target not found → 换个 search_method 重试"）。

### wait_for_compile：等编译，不猜

```python
def wait_for_compile(state_reader, *, timeout=2.0, poll=0.05):
    while ...:
        text = state_reader()
        if '"is_compiling":false' in text and '"ready_for_tools":true' in text:
            return {"ready": True, ...}
        time.sleep(poll)
```

真实 Unity 的编译状态在**资源** `mcpforunity://editor/state`（字段 `data.compilation.is_compiling`、`data.advice.ready_for_tools`），不是某个 tool 的 action。所以 `wait_for_compile` 收一个 `state_reader` 回调，轮询到"编译结束且就绪"才返回。改脚本、加组件后必须先等它，再用新类型。

### 收官：config + skill + 结构化验收

零件拼成 Agent 的三根线：

- **config 驱动**：`unity:` 段控制连接、工具分组、权限、验证开关（见 [s19e](../s19e_external_permissions/) 的策略、[s19b](../s19b_real_mcp_client/) 的 URL 覆盖）。
- **skill 引导**：把 Observe→Act→Verify、场景操作范围、API 真实性、安全规范写进 `skills/unity-agent/SKILL.md`，Unity 入口只注入一句"处理 Unity 任务先 load_skill"。
- **结构化验收**：端到端跑完输出一个可核对的 summary——名字、instance id、scene、transform、组件表、材质、Console error 数、截图路径、是否保存、每步成败。

---

## 相对 s19 的变更

| 组件 | s19 | s19f |
|------|-----|------|
| 结果处理 | 直接返回字符串 | CallToolResult → 紧凑字符串，图片剥离，截断 |
| 截图 | — | 只回路径 + 元数据，base64 不进上下文 |
| 错误 | 裸字符串 | 稳定格式：工具名 + 类型 + 诊断建议 |
| 验证 | — | Observe→Act→Verify 助手（等编译 / 读 Console） |
| 领域行为 | 无 | skill 注入领域规范，config 驱动 |
| 收尾 | — | 结构化 E2E summary（可核对每一步） |

---

## 试一下

```sh
cd learn-claude-code
python s19f_result_control/code.py
```

观察重点：

1. **base64 剥离**：一张 ~200 KB 假截图，输出只剩 `[image omitted ...]`，`base64 present? False`。
2. **截断**：超长文本被切到 `MAX_RESULT_CHARS` 并留 `...[truncated N chars]`。
3. **稳定错误**：`isError` 结果和异常都变成 `[unity-tool-error] tool=... type=...` 一行。
4. **验证节奏**：假编译器轮询 3 次后 `ready=True`，Console error 数 = 0。
5. **收官**：打印出端到端 summary 的形状。

---

## 接下来

这条 s19 支线到此收官：**s19b 真异步客户端 → s19c 动态发现 → s19d 复用 loop → s19e 外部权限 → s19f 结果控制**，五章把 s19 的 mock MCP 变成了接真实 Unity 的生产级 Agent。

回到主线 [s20 Comprehensive](../s20_comprehensive/)——把前面所有机制归到一个循环。你在这条支线学到的 sync-over-async、动态发现、复用 loop、外部权限、结果收敛，同样适用于任何真实 MCP server（Jira、Figma、数据库……），不止 Unity。

<details>
<summary>深入：这段代码在生产里长什么样</summary>

- 真实格式化见 [`scripts/unity_agent/result_formatter.py`](../scripts/unity_agent/result_formatter.py)：`format_result` 处理 text / image / embedded resource / structuredContent，`MAX_RESULT_CHARS=20000`，图片走 `_IMAGE_PLACEHOLDER`；与 s08 的 large-output hook、context compact 兼容。
- 真实验证见 [`scripts/unity_agent/verification.py`](../scripts/unity_agent/verification.py)：`wait_for_compile(state_reader)` 读 `mcpforunity://editor/state`，`read_console_errors(caller)` 按 `data` 列表长度数错误。
- 真实收尾见 [`scripts/unity_agent/bootstrap.py`](../scripts/unity_agent/bootstrap.py)（runtime + 静态诊断工具 + system 附录）与 [`scripts/skills/unity-agent/`](../scripts/skills/unity-agent/)（领域规范）；真机垂直验收（Observe→Act→Verify 全流程）由这套 runtime 驱动，直接连真实 Unity MCP 跑。
- 真机验收结果：在真实 Unity 里建了红色 AgentCube@[0,1,0] + Rigidbody，Console 0 错误，存了场景，截了图——17 步全过。截图默认被 `.gitignore` 忽略，session_state 记录每步 operation id。

</details>
