# 在 User -- Agent Loop 的各个生命周期节点，注入Hooks，便于把扩展逻辑从主循环解耦；

"""
s04: Hooks — move extension logic out of the loop, onto hooks.

  User types query
       │
       ▼
  ┌──────────────────┐
  │ UserPromptSubmit │ ── trigger_hooks() before LLM
  └────────┬─────────┘
           ▼
  ┌────────────┐     ┌─────────────────────────────┐
  │  messages  │────▶│  LLM (stop_reason=tool_use?)│
  └────────────┘     │   No ──▶ Stop hooks ──▶ exit │
                     │   Yes ──▶ tool_use block ──┐ │
                     └────────────────────────────┘ │
                                                    ▼
                                          ┌──────────────────┐
                                          │ trigger_hooks()   │
                                          │  PreToolUse:      │
                                          │   permission_hook │
                                          │   log_hook        │
                                          └───────┬──────────┘
                                                  │ (not blocked)
                                          ┌───────▼──────────┐
                                          │ TOOL_HANDLERS[x]  │
                                          └───────┬──────────┘
                                                  │
                                          ┌───────▼──────────┐
                                          │ trigger_hooks()   │
                                          │  PostToolUse:     │
                                          │   large_output    │
                                          └───────┬──────────┘
                                                  │
                                          results ──▶ back to messages

"""

# ═══════════════════════════════════════════════════════════
#  NEW in s04: Hook System (s03 permission logic now via hooks)
# ═══════════════════════════════════════════════════════════
import os
from utils.load_config import cwd
from utils.tools import *
from rich import print

# ────────────── DENY / RISK command LIST ───────────────────────────────────────────
# fmt: off
# 高风险但不一定绝对禁止：命中后需要进一步询问/确认/拦截
if os.name == "nt":
    DENY_LIST = (
            "format",  # 格式化磁盘
            "diskpart",  # 磁盘分区工具，可能删除/修改分区
            "bcdedit",  # 修改 Windows 启动配置
            "reg delete",  # 删除注册表项
            "shutdown",  # 关机或重启系统
    )
    RISK_LIST = [
        "del /s",  # 递归删除文件
        "del /q",  # 静默删除文件，不提示确认
        "rd /s",  # 递归删除目录，rd 是 rmdir 的缩写
        "rmdir /s",  # 递归删除目录
        "remove-item",  # PowerShell 删除文件/目录命令
        "-recurse",  # PowerShell 递归操作参数
        "-force",  # PowerShell 强制操作参数
        "takeown",  # 获取文件/目录所有权
        "icacls",  # 修改文件/目录权限
        "c:\\windows",  # Windows 系统目录
        "system32",  # Windows 核心系统目录
        "curl ",  # 下载远程内容，可能配合执行脚本
        "wget ",  # 下载远程内容，可能配合执行脚本
        "| powershell",  # 管道执行 PowerShell
        "| cmd",  # 管道执行 cmd
    ]
else:
    DENY_LIST = (
            "sudo",  # 使用管理员权限执行命令
            "su ",  # 切换用户，可能获得更高权限
            "shutdown",  # 关机
            "reboot",  # 重启系统
            "mkfs",  # 格式化文件系统
            "dd if=",  # 底层磁盘复制/写入命令
            "rm -rf /",  # 强制递归删除根目录
            "> /dev/",  # 向设备文件写入内容
    )
    RISK_LIST = [
        "rm -rf",  # 强制递归删除文件/目录
        "rm -r",  # 递归删除文件/目录
        "chmod 777",  # 将权限改为所有人可读写执行
        "chmod -r",  # 递归修改权限
        "chown",  # 修改文件所有者
        "/etc/",  # 系统配置目录
        "/dev/",  # 设备文件目录
        "> /etc/",  # 向系统配置目录写入内容
        "> /dev/",  # 向设备文件写入内容
        "curl ",  # 下载远程内容
        "wget ",  # 下载远程内容
        "| bash",  # 下载内容后直接交给 bash 执行
        "| sh",  # 下载内容后直接交给 sh 执行
    ]

HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:  # teaching shortcut: block this tool call
            return result
    return None


# s03 permission check logic, now wrapped as a hook
# DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
# RISK_LIST = ["rm ", "> /etc/", "chmod 777"]




# 3 Gates Chain 检查工具权限。
def permission_hook(block) -> str | None:
    """PreToolUse: s03 check_permission() logic moved here."""

    command = block.input.get("command", "").lower()  # block.input，这是大模型生成的工具调用的参数
    path = block.input.get("path", "")

    # 检查 bash 命令是否有在 DENY_LIST 中的命令或 RISK_LIST 中的命令
    if block.name == "bash":
        for kw in DENY_LIST:
            if kw in command:
                print(f"\n[yellow]Blocked: '{kw}' is on the deny list[/yellow]")  # fmt: skip
                # 后续可以支持用户修改DENY_LIST
                return "Permission denied by deny list"

        if any(kw in command for kw in RISK_LIST):  # Gate 2
            print(f"\n[yellow]Potentially RISK_LIST command [/yellow]  Tool: {block.name}({block.input})") # fmt: skip
            choice = input("  Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"


    # 检查是否越出工作区操作
    elif block.name in ("write_file", "edit_file"):
        # (cwd / path) 表示 当前 "工作目录" + "对象相对路径"，   .resovle()表示转化为绝对目录。
        if not (cwd / path).resolve().is_relative_to(cwd):
            print(f"\n[yellow]Writing outside workspace[/yellow]  Tool: {block.name}({block.input})")  # fmt: skip
            choice = input("  Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"
    return None # Only return None: 才表示允许工具调用继续


def log_hook(block):
    """PreToolUse: log every tool call."""
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"[HOOK] {block.name}({args_preview})")
    return None


def large_output_hook(block, output):
    """PostToolUse: warn on large output."""
    if len(str(output)) > 100000:
        print(
            f"[HOOK] ⚠ Large output from {block.name}: {len(str(output))} chars"
        )
    return None


# UserPromptSubmit hook: log user input before it reaches the LLM
def context_inject_hook(query: str):
    print(f"[HOOK] UserPromptSubmit: working in {cwd}")
    return None


# Stop hook: print summary when loop is about to exit
def summary_hook(messages: list):
    tool_count = sum(
        1
        for m in messages
        for b in (m.get("content") if isinstance(m.get("content"), list) else [])
        if isinstance(b, dict) and b.get("type") == "tool_result"
    )
    print(f"[HOOK] Stop: session used {tool_count} tool calls")
    return None


register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)
