#!/usr/bin/env python3
"""安装、校验并卸载本仓库对应的 DSH filesystem skill。

真源：`_research/dsh-adaptation-contract.md` §4。
设计要点：
- 解析 SKILL.md 前必须做换行归一化（本仓库历史上是 Windows CRLF 检出）；
- 安装走「临时目录 → 复制 → 写标记 → 原子 rename」，失败回滚；
- 同名非本工具管理的目录默认拒绝，`--force` 时先备份再替换。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MARKER = ".dsh-package.json"
MARKER_SCHEMA = "dsh-skill-install/v1"
MANIFEST_SCHEMA = "dsh-skill-package/v1"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# DSH 标准 preset 的 tool-result-pruner：thresholdChars 8192 / headChars 4096 / tailChars 1024。
# 超长 body 会被掐掉中间，模型只能看到头尾，故打包时按此阈值卡住。
BODY_LIMIT = 8192
TRUE_VALUES = {"true", "yes", "on", "1"}
FALSE_VALUES = {"false", "no", "off", "0"}
# 复制到安装目录时跳过的内容（构建产物、缓存、版本库）。
IGNORED = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
}


class PackageError(RuntimeError):
    """可向用户解释的打包/安装失败。"""


def ensure_utf8_stdio() -> None:
    """把 stdout/stderr 切到 UTF-8。

    Windows 控制台默认是 GBK，未设 PYTHONIOENCODING 时中文消息会 UnicodeEncodeError。
    被重定向到非文本流（如测试里的 StringIO）时直接跳过。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def normalize_newlines(text: str) -> str:
    """把 CRLF / 单独 CR 统一成 LF。

    本仓库 SKILL.md 曾以 CRLF 检出，只认 `---\\n` 的解析器会静默失效——这是必须修的坑。
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def as_bool(value: Any) -> bool:
    """按 DSH 的 frontmatterBoolean 语义判断布尔值。

    接受真正的布尔值、`1`/`0`、以及大小写不敏感的 true|yes|on / false|no|off。
    行内注释（`true  # 说明`）取首个 token 即可，不影响判断。
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip()
    token = text.split()[0].lower() if text else ""
    if token in TRUE_VALUES:
        return True
    if token in FALSE_VALUES:
        return False
    return False


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


class _Nested:
    """占位节点：`key:` 后面为空时，还不知道该填映射还是序列。"""


def _parse_yaml_block(block: str) -> dict[str, Any]:
    """解析 frontmatter 用到的 YAML 子集：嵌套映射 + 块状序列。

    只需覆盖 name / description / user-invocable / metadata.dsh.* 这些键，
    因此不引入 PyYAML（打包脚本要求零第三方依赖）。不支持 flow style（`{...}` / `[...]`）。
    """
    root: dict[str, Any] = {}
    # 每项：(该层键所在行的缩进, 容器, 父容器, 父容器里的键名)
    stack: list[tuple[int, Any, Any, Any]] = [(-1, root, None, None)]

    for raw_line in block.split("\n"):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        layer_indent, container, parent, key = stack[-1]

        if line.startswith("- "):
            # 序列项：先把占位节点实体化成 list
            if isinstance(container, _Nested):
                container = []
                parent[key] = container
                stack[-1] = (layer_indent, container, parent, key)
            if isinstance(container, list):
                container.append(_unquote(line[2:].strip()))
            continue

        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name = name.strip()
        if not name:
            continue
        value = value.strip()

        if isinstance(container, _Nested):
            container = {}
            parent[key] = container
            stack[-1] = (layer_indent, container, parent, key)
        if not isinstance(container, dict):
            continue

        if value == "":
            child = _Nested()
            container[name] = child
            stack.append((indent, child, container, name))
        else:
            container[name] = _unquote(value)

    return root


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str] | None:
    """返回 (frontmatter 字段, body)；无法解析返回 None。

    规则与 DSH 一致：首行必须逐字节是 `---`（归一化后即 `---`），后面要有独占一行的收尾 `---`。
    """
    lines = normalize_newlines(text).split("\n")
    if not lines or lines[0] != "---":
        return None
    closing = None
    for index in range(1, len(lines)):
        if lines[index] == "---":
            closing = index
            break
    if closing is None:
        return None
    fields = _parse_yaml_block("\n".join(lines[1:closing]))
    body = "\n".join(lines[closing + 1:])
    return fields, body


def load_manifest(root: Path = ROOT) -> dict[str, Any]:
    path = root / "dsh" / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"无法读取 DSH manifest：{path}: {exc}") from exc
    name = data.get("name") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("schema") != MANIFEST_SCHEMA or not isinstance(name, str):
        raise PackageError(f"无效的 DSH manifest：{path}")
    if not NAME_RE.fullmatch(name):
        raise PackageError(f"Skill 名称必须是 kebab-case：{name!r}")
    return data


def dsh_home(value: str | None) -> Path:
    """解析 DSH_HOME：--dsh-home > $DSH_HOME > ~/.dsh。"""
    raw = value or os.environ.get("DSH_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".dsh"


def validate_source(root: Path, manifest: dict[str, Any]) -> list[str]:
    """按契约 §4 的顺序检查源包，返回中文问题列表（空 = 通过）。"""
    issues: list[str] = []
    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        return [f"缺少 {skill_file}"]
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"无法读取 {skill_file}：{exc}"]

    parsed = parse_frontmatter(text)
    if parsed is None:
        return ["SKILL.md 缺少合法 frontmatter：首行必须是独占一行的 ---，且后面要有独占一行的收尾 ---"]
    fields, body = parsed

    expected_name = manifest.get("name")
    name = fields.get("name")
    if not isinstance(name, str) or not name.strip():
        issues.append("SKILL.md frontmatter 缺少 name")
    else:
        if not NAME_RE.fullmatch(name):
            issues.append(f"SKILL.md name 不是合法的 kebab-case：{name!r}")
        if name != expected_name:
            issues.append(f"SKILL.md name 应为 {expected_name!r}，实际为 {name!r}")

    description = fields.get("description")
    if not isinstance(description, str) or not description.strip():
        issues.append("SKILL.md 缺少 description")

    if not as_bool(fields.get("user-invocable")):
        issues.append("SKILL.md 缺少 user-invocable: true")

    body_length = len(body.strip())
    if body_length >= BODY_LIMIT:
        issues.append(f"SKILL.md body {body_length} 字符，超过 DSH 工具结果修剪阈值 8192")

    return issues


def ignore_paths(_directory: str, names: list[str]) -> list[str]:
    """copytree 的 ignore 回调：跳过 IGNORED 与字节码/egg-info。"""
    ignored = []
    for name in names:
        if name in IGNORED or name.endswith((".pyc", ".pyo", ".egg-info")):
            ignored.append(name)
    return ignored


def read_marker(target: Path) -> dict[str, Any] | None:
    """读取安装副本的所有权标记；缺失或 schema 不符返回 None。"""
    try:
        data = json.loads((target / MARKER).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != MARKER_SCHEMA:
        return None
    return data


def is_managed(target: Path, name: str) -> bool:
    data = read_marker(target)
    return bool(data and data.get("name") == name)


def _direct_child(target: Path, skills_root: Path) -> None:
    """拒绝操作 skills 根目录以外的一级路径（防路径穿越）。"""
    if target.parent.resolve() != skills_root.resolve():
        raise PackageError(f"拒绝操作 skills 根目录以外的路径：{target}")


def _free_path(candidate: Path) -> Path:
    """重名时依次追加 -1 / -2 …，返回第一个不存在的路径。"""
    if not candidate.exists() and not candidate.is_symlink():
        return candidate
    index = 1
    while True:
        alternative = candidate.with_name(f"{candidate.name}-{index}")
        if not alternative.exists() and not alternative.is_symlink():
            return alternative
        index += 1


def backup_path(target: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return _free_path(target.with_name(f"{target.name}.backup-{stamp}"))


def install(root: Path, home: Path, force: bool = False) -> dict[str, str]:
    """安装或更新 skill 到 <dsh_home>/skills/<name>。"""
    manifest = load_manifest(root)
    issues = validate_source(root, manifest)
    if issues:
        raise PackageError("源包校验失败：\n- " + "\n- ".join(issues))

    name = manifest["name"]
    skills_root = home / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    target = skills_root / name
    _direct_child(target, skills_root)

    exists = target.exists() or target.is_symlink()
    managed = exists and is_managed(target, name)
    if exists and not managed and not force:
        raise PackageError(
            f"发现非本工具管理的同名目录：{target}。确认可以覆盖后使用 --force（会先备份原目录）。"
        )

    temp_parent = Path(tempfile.mkdtemp(prefix=f".{name}.install-", dir=str(skills_root)))
    staged = temp_parent / name
    backup: Path | None = None
    previous: Path | None = None
    try:
        shutil.copytree(root, staged, ignore=ignore_paths)
        marker = {
            "schema": MARKER_SCHEMA,
            "name": name,
            "version": manifest.get("version", ""),
            "source": str(root.resolve()),
            "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (staged / MARKER).write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        action = "installed"
        if exists:
            if managed:
                # 旧副本是本工具装的：挪到 .<name>.previous，成功后删除。
                previous = _free_path(target.with_name(f".{name}.previous"))
                target.rename(previous)
                action = "updated"
            else:
                # 用户自己的同名目录：先备份，绝不静默覆盖。
                backup = backup_path(target)
                target.rename(backup)
                action = "backed-up-and-installed"

        try:
            staged.rename(target)
        except Exception:
            # 替换失败：把旧副本还原回原位，避免安装目录凭空消失。
            restore = previous or backup
            if restore is not None and restore.exists() and not target.exists():
                restore.rename(target)
            raise

        if previous is not None and previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
    finally:
        if temp_parent.exists():
            shutil.rmtree(temp_parent, ignore_errors=True)

    result = {"name": name, "action": action, "target": str(target)}
    if backup is not None:
        result["backup"] = str(backup)
    return result


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def find_bundled_node(home: Path) -> list[Path]:
    """探测 DSH 自带的 node：<dsh_home>/dsh-runtimes/*/dependencies/node/bin/node.exe。"""
    try:
        candidates = sorted(home.glob("dsh-runtimes/*/dependencies/node/bin/node.exe"))
    except OSError:
        return []
    return [path for path in candidates if path.is_file()]


def runtime_report(manifest: dict[str, Any], home: Path) -> tuple[list[str], list[str]]:
    """运行环境报告，返回 (errors, warnings)。

    本机 node/npm/npx 都不在 PATH：node 可用 DSH 自带那份，故降级为 warning；
    npm/npx 确实没有（DSH 自带 node 不带 npm/npx），仍如实报 error。
    """
    errors: list[str] = []
    warnings: list[str] = []
    runtime = manifest.get("runtime") or {}

    minimum = str(runtime.get("python", "")).strip()
    parts = minimum.split(".")
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        wanted = (int(parts[0]), int(parts[1]))
        if sys.version_info[:2] < wanted:
            current = f"{sys.version_info[0]}.{sys.version_info[1]}"
            errors.append(f"需要 Python {wanted[0]}.{wanted[1]}+，当前为 {current}")

    for module in runtime.get("python_modules") or []:
        if not _module_available(module):
            errors.append(f"缺少 Python 模块：{module}")

    for command in runtime.get("commands") or []:
        if shutil.which(command) is not None:
            continue
        bundled = find_bundled_node(home) if command == "node" else []
        if bundled:
            warnings.append(
                f"未在 PATH 中找到 node；可使用 DSH 自带 node：{bundled[0]}，"
                "需加入 PATH 或用绝对路径调用"
            )
        else:
            errors.append(f"PATH 中未找到命令：{command}")

    for module in runtime.get("optional_python_modules") or []:
        if not _module_available(module):
            warnings.append(f"缺少可选 Python 模块：{module}（相关功能不可用，其余功能不受影响）")

    return errors, warnings


def doctor(
    root: Path,
    home: Path,
    source_only: bool = False,
    skip_runtime: bool = False,
) -> dict[str, Any]:
    """检查源包、安装副本与运行环境；ok = 没有任何 error。"""
    manifest = load_manifest(root)
    errors = validate_source(root, manifest)
    warnings: list[str] = []

    target = home / "skills" / manifest["name"]
    installed = False
    if not source_only:
        installed = (target / "SKILL.md").is_file()
        if not installed:
            errors.append(f"尚未安装：{target}")
        elif not is_managed(target, manifest["name"]):
            errors.append(f"安装目录缺少有效所有权标记 {MARKER}：{target}")

    if not skip_runtime:
        runtime_errors, runtime_warnings = runtime_report(manifest, home)
        errors.extend(runtime_errors)
        warnings.extend(runtime_warnings)

    return {
        "ok": not errors,
        "name": manifest["name"],
        "version": manifest.get("version", ""),
        "target": str(target),
        "installed": installed,
        "errors": errors,
        "warnings": warnings,
    }


def uninstall(root: Path, home: Path) -> dict[str, str]:
    """只删除带有效所有权标记的安装副本。"""
    manifest = load_manifest(root)
    name = manifest["name"]
    skills_root = home / "skills"
    target = skills_root / name
    _direct_child(target, skills_root)

    if not target.exists() and not target.is_symlink():
        action = "absent"
    elif is_managed(target, name):
        # 符号链接只删链接本身，不递归进去删用户真实目录。
        if target.is_symlink():
            target.unlink()
        else:
            shutil.rmtree(target)
        action = "removed"
    else:
        action = "skipped-unmanaged"
    return {"name": name, "action": action, "target": str(target)}


def _add_common_options(target: argparse.ArgumentParser) -> None:
    """让子命令也接受全局选项（如 `doctor --json`）。

    default=SUPPRESS 是关键：否则子解析器的默认值会覆盖顶层已解析出来的取值。
    """
    target.add_argument("--repo-root", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    target.add_argument("--dsh-home", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    target.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    target.add_argument("--skip-runtime", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="DeepSeek Harness skill 打包管理器")
    result.add_argument("--repo-root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    result.add_argument("--dsh-home", help="DSH_HOME；默认读取环境变量 DSH_HOME 或 ~/.dsh")
    result.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    result.add_argument(
        "--skip-runtime",
        action="store_true",
        help="跳过运行环境检查（CI 只校验打包完整性时使用）",
    )
    commands = result.add_subparsers(dest="command", required=True)

    install_command = commands.add_parser("install", help="安装或更新 skill")
    install_command.add_argument("--force", action="store_true", help="备份并替换非本工具管理的同名目录")
    _add_common_options(install_command)

    doctor_command = commands.add_parser("doctor", help="检查源包、安装副本与运行环境")
    doctor_command.add_argument("--source-only", action="store_true", help="不检查安装副本")
    _add_common_options(doctor_command)

    uninstall_command = commands.add_parser("uninstall", help="仅删除由本工具管理的安装副本")
    _add_common_options(uninstall_command)
    return result


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    args = parser().parse_args(argv)
    root = Path(args.repo_root).resolve()
    home = dsh_home(args.dsh_home)

    try:
        if args.command == "install":
            result: dict[str, Any] = install(root, home, force=args.force)
            code = 0
        elif args.command == "doctor":
            result = doctor(root, home, source_only=args.source_only, skip_runtime=args.skip_runtime)
            code = 0 if result["ok"] else 1
        else:
            result = uninstall(root, home)
            code = 0
    except PackageError as exc:
        result = {"ok": False, "error": str(exc)}
        code = 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif "error" in result:
        print(f"错误：{result['error']}", file=sys.stderr)
    elif args.command == "doctor":
        print("[OK] DSH 检查通过" if result["ok"] else "[FAIL] DSH 检查失败")
        print(f"  target: {result['target']}")
        for message in result["errors"]:
            print(f"  ERROR: {message}")
        for message in result["warnings"]:
            print(f"  WARN: {message}")
    else:
        print(f"{result['action']}: {result['target']}")
        if result.get("backup"):
            print(f"backup: {result['backup']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
