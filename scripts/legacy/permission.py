"""
DEPRECATED MODULE.

This module implements beta version of permission check in hooks.py.

Use:
    utils.hooks

instead.

Deprecated since:
    2026-07-16

"""

# ═══════════════════════════════════════════════════════════
#  NEW in s03: Three-Gate Permission Pipeline
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
# fmt: on


# Gate 1: Hard deny list — always forbidden
def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        # if pattern in command:
        if pattern in command.lower():  # 减少大小写敏感
            return f"Blocked: '{pattern}' is on the deny list"  # 后续可以支持用户修改DENY_LIST
    return None


# Gate 2: Rule matching — context-dependent checks
# PERMISSION_RULES包含了一系列字典，每个字典对应一类工具的权限规则。
# 每一类工具权限规则是一个lambda函数，接受一组字典形式的args；实际上接受的是block.input，这是大模型生成的工具调用的参数。
PERMISSION_RULES = [
    {
        "tools": ["write_file", "edit_file"],
        # fmt: off
        "check": lambda args: not (cwd / args.get("path", "")).resolve().is_relative_to(cwd),
        # fmt: on
        "message": "Writing outside workspace",
    },
    {
        "tools": ["bash"],
        "check": lambda args: any(
            # kw in args.get("command", "") for kw in ["rm ", "> /etc/", "chmod 777"]
            kw in args.get("command", "").lower() for kw in RISK_LIST # fmt: skip
        ),
        "message": "Potentially destructive command",
    },
]


def check_rules(tool_name: str, args: dict) -> str | None:
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](args):
            return rule["message"]
    return None


# Gate 3: User approval — wait for confirmation after rule match
def ask_user(tool_name: str, args: dict, reason: str) -> str:
    # print(f"\n\033[33m⚠  {reason}\033[0m")
    print(f"\n[red] {reason}[/red]")
    print(f"   Tool: {tool_name}({args})")
    choice = input("   Allow? [y/N] ").strip().lower()
    return "allow" if choice in ("y", "yes") else "deny"


# Pipeline: all three gates chained
def check_permission(block) -> bool:
    if block.name == "bash":
        reason = check_deny_list(
            block.input.get("command", "")
        )  # Gate 1 触发时将直接阻止执行
        if reason:
            # print(f"\n\033[31m⛔ {reason}\033[0m")
            print(f"\n[red] Denied: {reason}[/red]")
            return False
    reason = check_rules(
        block.name, block.input
    )  # Gate 2 触发时，返回组织原因交给用户判断。
    if reason:
        decision = ask_user(block.name, block.input, reason)  # Gate 3
        if decision == "deny":
            return False
    return True
