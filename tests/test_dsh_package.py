"""DSH 打包完整性测试（标准库 unittest，零第三方依赖）。

从仓库根运行：
    python -m unittest discover -s tests -v

覆盖契约 §5 的五组用例，另加换行归一化、runtime 降级、CLI 退出码等回归点。
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("dsh_manager", ROOT / "scripts" / "dsh_manager.py")
assert SPEC and SPEC.loader, "无法加载 scripts/dsh_manager.py"
dsh_manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dsh_manager)


def make_fixture_root(directory: Path, body: str | None = None, newline: str = "\n") -> Path:
    """在 directory 里拼一个最小可校验的仓库根（只需 SKILL.md + dsh/manifest.json）。

    validate_source / load_manifest 只读这两个文件，因此不必复制 60 MB 的完整仓库。
    """
    fixture = directory / "repo"
    (fixture / "dsh").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "dsh" / "manifest.json", fixture / "dsh" / "manifest.json")
    if body is None:
        shutil.copyfile(ROOT / "SKILL.md", fixture / "SKILL.md")
    else:
        content = (
            "---\n"
            "name: video-shotcraft\n"
            "description: 测试用 skill。\n"
            "user-invocable: true\n"
            "---\n"
            "\n" + body + "\n"
        )
        (fixture / "SKILL.md").write_bytes(content.replace("\n", newline).encode("utf-8"))
    return fixture


class ManifestAndFrontmatterTests(unittest.TestCase):
    """用例 1：manifest 与 frontmatter 一致。"""

    def test_manifest_matches_frontmatter(self):
        manifest = dsh_manager.load_manifest(ROOT)
        self.assertEqual(manifest["name"], "video-shotcraft")
        self.assertEqual(manifest["schema"], "dsh-skill-package/v1")
        self.assertEqual(dsh_manager.validate_source(ROOT, manifest), [])

    def test_frontmatter_declares_invocation_and_compatibility(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        parsed = dsh_manager.parse_frontmatter(text)
        self.assertIsNotNone(parsed, "SKILL.md frontmatter 无法解析")
        fields, body = parsed
        self.assertEqual(fields.get("user-invocable"), "true")
        dsh_meta = fields.get("metadata", {}).get("dsh", {})
        self.assertEqual(dsh_meta.get("compatibility"), "native")
        self.assertEqual(dsh_meta.get("requires"), ["node", "npm", "npx"])

    def test_body_under_pruner_threshold(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        fields, body = dsh_manager.parse_frontmatter(text)
        self.assertLess(len(body.strip()), 8192)

    def test_description_non_empty(self):
        fields, _ = dsh_manager.parse_frontmatter((ROOT / "SKILL.md").read_text(encoding="utf-8"))
        self.assertTrue(str(fields.get("description", "")).strip())


class NewlineNormalizationTests(unittest.TestCase):
    """回归：参考实现只认 `---\\n`，在 CRLF 检出下会静默失效。"""

    def test_crlf_frontmatter_is_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_fixture_root(Path(directory), body="正文", newline="\r\n")
            raw = (fixture / "SKILL.md").read_bytes()
            self.assertIn(b"\r\n", raw)
            manifest = dsh_manager.load_manifest(fixture)
            self.assertEqual(dsh_manager.validate_source(fixture, manifest), [])

    def test_bare_cr_frontmatter_is_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_fixture_root(Path(directory), body="正文", newline="\r")
            parsed = dsh_manager.parse_frontmatter((fixture / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed[0].get("name"), "video-shotcraft")

    def test_normalize_newlines(self):
        self.assertEqual(dsh_manager.normalize_newlines("a\r\nb\rc\nd"), "a\nb\nc\nd")


class ValidateSourceTests(unittest.TestCase):
    """用例 4：body 超限与各类 frontmatter 缺陷都能被抓出来。"""

    def test_oversized_body_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_fixture_root(Path(directory), body="x" * 9000)
            manifest = dsh_manager.load_manifest(fixture)
            issues = dsh_manager.validate_source(fixture, manifest)
            self.assertTrue(issues, "body 灌到 9000 字符后应当报错")
            self.assertTrue(any("8192" in issue for issue in issues), issues)
            self.assertTrue(any("9000" in issue for issue in issues), issues)

    def test_body_just_under_threshold_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_fixture_root(Path(directory), body="x" * 8000)
            manifest = dsh_manager.load_manifest(fixture)
            self.assertEqual(dsh_manager.validate_source(fixture, manifest), [])

    def test_missing_skill_md_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_fixture_root(Path(directory))
            (fixture / "SKILL.md").unlink()
            manifest = dsh_manager.load_manifest(fixture)
            issues = dsh_manager.validate_source(fixture, manifest)
            self.assertEqual(len(issues), 1)
            self.assertIn("SKILL.md", issues[0])

    def test_missing_closing_fence_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_fixture_root(Path(directory))
            (fixture / "SKILL.md").write_text(
                "---\nname: video-shotcraft\ndescription: 没有收尾分隔符\n\n正文\n",
                encoding="utf-8",
            )
            manifest = dsh_manager.load_manifest(fixture)
            issues = dsh_manager.validate_source(fixture, manifest)
            self.assertTrue(any("frontmatter" in issue for issue in issues), issues)

    def test_missing_user_invocable_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_fixture_root(Path(directory))
            (fixture / "SKILL.md").write_text(
                "---\nname: video-shotcraft\ndescription: 缺 user-invocable\n---\n\n正文\n",
                encoding="utf-8",
            )
            manifest = dsh_manager.load_manifest(fixture)
            issues = dsh_manager.validate_source(fixture, manifest)
            self.assertTrue(any("user-invocable" in issue for issue in issues), issues)

    def test_name_mismatch_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_fixture_root(Path(directory))
            (fixture / "SKILL.md").write_text(
                "---\nname: other-skill\ndescription: 名字不一致\nuser-invocable: true\n---\n\n正文\n",
                encoding="utf-8",
            )
            manifest = dsh_manager.load_manifest(fixture)
            issues = dsh_manager.validate_source(fixture, manifest)
            self.assertTrue(any("other-skill" in issue for issue in issues), issues)


class LifecycleTests(unittest.TestCase):
    """用例 2：install → doctor → install(updated) → uninstall → absent。"""

    def test_install_update_doctor_and_uninstall(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            first = dsh_manager.install(ROOT, home)
            self.assertEqual(first["action"], "installed")
            target = home / "skills" / "video-shotcraft"
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertTrue((target / dsh_manager.MARKER).is_file())

            # 运行环境检查依赖宿主 PATH（本机 node/npm/npx 都不在），故生命周期只验打包完整性。
            report = dsh_manager.doctor(ROOT, home, skip_runtime=True)
            self.assertTrue(report["ok"], report)
            self.assertTrue(report["installed"])

            marker = json.loads((target / dsh_manager.MARKER).read_text(encoding="utf-8"))
            self.assertEqual(marker["schema"], "dsh-skill-install/v1")
            self.assertEqual(marker["name"], "video-shotcraft")
            self.assertEqual(marker["version"], "1.0.0-dsh.1")
            self.assertEqual(Path(marker["source"]), ROOT.resolve())
            self.assertTrue(marker["installed_at"])

            second = dsh_manager.install(ROOT, home)
            self.assertEqual(second["action"], "updated")
            self.assertFalse((home / "skills" / ".video-shotcraft.previous").exists())

            removed = dsh_manager.uninstall(ROOT, home)
            self.assertEqual(removed["action"], "removed")
            self.assertFalse(target.exists())

            again = dsh_manager.uninstall(ROOT, home)
            self.assertEqual(again["action"], "absent")

    def test_install_skips_vcs_and_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            dsh_manager.install(ROOT, home)
            target = home / "skills" / "video-shotcraft"
            for unwanted in (".git", "node_modules", "__pycache__"):
                self.assertFalse((target / unwanted).exists(), unwanted)
            self.assertTrue((target / "SKILL.md").is_file())

    def test_install_copies_full_directory_tree(self):
        """安装的必须是完整目录树，不能只有 SKILL.md。

        （真机教训：panel CLI 的 `skill add <file>` 只复制单文件，装出来是残缺的。）
        """
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            dsh_manager.install(ROOT, home)
            target = home / "skills" / "video-shotcraft"
            for relative in (
                "SKILL.md",
                "dsh/manifest.json",
                "references/pipeline.md",
                "references/delivery-closeout.md",
                "assets",
                "gallery/api/library.json",
                "template/package.json",
            ):
                self.assertTrue((target / relative).exists(), f"安装副本缺少 {relative}")

    def test_doctor_without_install_reports_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            report = dsh_manager.doctor(ROOT, Path(directory), skip_runtime=True)
            self.assertFalse(report["ok"])
            self.assertFalse(report["installed"])
            self.assertTrue(any("尚未安装" in error for error in report["errors"]), report)


class CollisionTests(unittest.TestCase):
    """用例 3：同名非管理目录的保护与 --force 备份。"""

    def test_collision_requires_force_and_backup_preserves_files(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "skills" / "video-shotcraft"
            target.mkdir(parents=True)
            (target / "user.txt").write_text("keep", encoding="utf-8")

            with self.assertRaises(dsh_manager.PackageError):
                dsh_manager.install(ROOT, home)
            # 拒绝时不得动用户的目录
            self.assertEqual((target / "user.txt").read_text(encoding="utf-8"), "keep")
            self.assertFalse((target / dsh_manager.MARKER).exists())

            result = dsh_manager.install(ROOT, home, force=True)
            self.assertEqual(result["action"], "backed-up-and-installed")
            backup = Path(result["backup"])
            self.assertTrue(backup.is_dir())
            self.assertEqual((backup / "user.txt").read_text(encoding="utf-8"), "keep")
            self.assertTrue((target / dsh_manager.MARKER).is_file())
            self.assertFalse((target / "user.txt").exists())

    def test_uninstall_skips_unmanaged_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "skills" / "video-shotcraft"
            target.mkdir(parents=True)
            (target / "user.txt").write_text("keep", encoding="utf-8")
            result = dsh_manager.uninstall(ROOT, home)
            self.assertEqual(result["action"], "skipped-unmanaged")
            self.assertTrue((target / "user.txt").is_file())

    def test_second_backup_gets_unique_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "skills" / "video-shotcraft"
            target.mkdir(parents=True)
            (target / "user.txt").write_text("keep", encoding="utf-8")
            first = dsh_manager.install(ROOT, home, force=True)
            # 撤掉标记，让安装副本重新变成"非管理目录"，再 force 一次
            (Path(first["target"]) / dsh_manager.MARKER).unlink()
            second = dsh_manager.install(ROOT, home, force=True)
            self.assertNotEqual(first["backup"], second["backup"])
            self.assertTrue(Path(second["backup"]).is_dir())


class RuntimeReportTests(unittest.TestCase):
    """runtime 报告：node 可降级为 warning，npm/npx 如实报 error。"""

    def test_missing_command_is_error(self):
        manifest = {"runtime": {"commands": ["dsh-definitely-not-a-real-command"]}}
        with tempfile.TemporaryDirectory() as directory:
            errors, warnings = dsh_manager.runtime_report(manifest, Path(directory))
        self.assertTrue(any("dsh-definitely-not-a-real-command" in error for error in errors), errors)

    def test_bundled_node_is_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            node = home / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
            node.parent.mkdir(parents=True)
            node.write_text("", encoding="utf-8")
            found = dsh_manager.find_bundled_node(home)
            self.assertEqual(found, [node])

    def test_node_degrades_to_warning_when_bundled_node_exists(self):
        if shutil.which("node") is not None:
            self.skipTest("本机 node 在 PATH 中，走不到降级分支")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            node = home / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"
            node.parent.mkdir(parents=True)
            node.write_text("", encoding="utf-8")
            errors, warnings = dsh_manager.runtime_report({"runtime": {"commands": ["node"]}}, home)
            self.assertEqual(errors, [])
            self.assertTrue(any(str(node) in warning for warning in warnings), warnings)

    def test_optional_python_module_is_warning(self):
        manifest = {"runtime": {"optional_python_modules": ["dsh_definitely_missing_module"]}}
        with tempfile.TemporaryDirectory() as directory:
            errors, warnings = dsh_manager.runtime_report(manifest, Path(directory))
        self.assertEqual(errors, [])
        self.assertTrue(any("dsh_definitely_missing_module" in warning for warning in warnings), warnings)

    def test_python_version_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            errors, _ = dsh_manager.runtime_report({"runtime": {"python": "99.0"}}, Path(directory))
        self.assertTrue(any("Python" in error for error in errors), errors)


class CliTests(unittest.TestCase):
    """CLI 契约：退出码 0/1/2、--json 输出、全局选项放在子命令之后也要生效。"""

    def run_cli(self, *arguments, home: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "dsh_manager.py"), "--dsh-home", str(home), *arguments],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

    def test_install_doctor_uninstall_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            installed = self.run_cli("install", home=home)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertIn("installed:", installed.stdout)

            doctor = self.run_cli("doctor", "--skip-runtime", home=home)
            self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
            self.assertIn("[OK] DSH 检查通过", doctor.stdout)
            self.assertIn("target:", doctor.stdout)

            removed = self.run_cli("uninstall", home=home)
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertIn("removed:", removed.stdout)

    def test_doctor_json_is_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.run_cli("install", home=home)
            # --json 放在子命令之后，验证全局选项对子解析器也生效
            result = self.run_cli("doctor", "--json", "--skip-runtime", home=home)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["name"], "video-shotcraft")
            self.assertEqual(payload["errors"], [])

    def test_doctor_failure_exit_code_is_one(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli("doctor", "--skip-runtime", home=Path(directory))
            self.assertEqual(result.returncode, 1)
            self.assertIn("[FAIL] DSH 检查失败", result.stdout)

    def test_package_error_exit_code_is_two(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "skills" / "video-shotcraft"
            target.mkdir(parents=True)
            (target / "user.txt").write_text("keep", encoding="utf-8")
            result = self.run_cli("install", home=home)
            self.assertEqual(result.returncode, 2)
            self.assertIn("非本工具管理", result.stderr)

    def test_source_only_skips_install_check(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_cli("doctor", "--source-only", "--skip-runtime", home=Path(directory))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_human_readable_output_has_readable_chinese(self):
        """锁住中文输出的编码。

        历史故障：`dsh_manager.py` 曾整份双重编码（UTF-8 字节被按 CP1252 解码后又存成 UTF-8），
        用户看到的是「[OK] DSH」后面跟一串 CP1252 乱码字符，而当时的断言只比较 ASCII 前缀所以测试全绿。
        这里同时断言「正常中文存在」与「没有双重编码残留字符」。

        乱码字符用 \\uXXXX 转义写，避免本文件自身带上这些字符而被编码检查误报。
        """
        mojibake_chars = (
            "\u00c3", "\u00e6", "\u00e5", "\u00e8", "\u00e9", "\u00ef",
            "\u00bc", "\u00e2", "\u00e3", "\u00a5", "\u00a4", "\ufffd",
        )
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)

            installed = self.run_cli("install", home=home)
            self.assertEqual(installed.returncode, 0, installed.stderr)

            doctor = self.run_cli("doctor", "--skip-runtime", home=home)
            self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
            self.assertIn("检查通过", doctor.stdout)
            for char in mojibake_chars:
                self.assertNotIn(
                    char, doctor.stdout, f"doctor 输出含疑似双重编码字符 {char!r}：{doctor.stdout!r}"
                )

            updated = self.run_cli("install", home=home)
            self.assertEqual(updated.returncode, 0, updated.stderr)
            self.assertIn("updated:", updated.stdout)

            removed = self.run_cli("uninstall", home=home)
            self.assertEqual(removed.returncode, 0, removed.stderr)
            for char in mojibake_chars:
                self.assertNotIn(
                    char, removed.stdout, f"uninstall 输出含疑似双重编码字符 {char!r}：{removed.stdout!r}"
                )

    def test_package_error_message_is_readable_chinese(self):
        """错误消息同样必须是可读中文（stderr 路径也要归一化正确）。"""
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "skills" / "video-shotcraft"
            target.mkdir(parents=True)
            result = self.run_cli("install", home=home)
            self.assertEqual(result.returncode, 2)
            self.assertIn("非本工具管理的同名目录", result.stderr)
            self.assertNotIn("\ufffd", result.stderr)


class RepositoryConsistencyTests(unittest.TestCase):
    """用例 5：仓库自洽（gallery 索引与 template 清单）。"""

    def test_gallery_card_count_matches_cards(self):
        library = json.loads((ROOT / "gallery" / "api" / "library.json").read_text(encoding="utf-8"))
        self.assertEqual(library["stats"]["cardCount"], len(library["cards"]))

    def test_template_manifest_declares_remotion_and_render(self):
        package = json.loads((ROOT / "template" / "package.json").read_text(encoding="utf-8"))
        self.assertIn("remotion", package["dependencies"])
        self.assertIn("render", package["scripts"])

    def test_shell_entrypoints_are_executable(self):
        """所有 .sh 都必须带可执行位和 shebang，否则 ./install-dsh.sh 会 Permission denied。

        仓库既有约定是 .sh 一律 100755（gallery/fetch-media.sh、shot-polish/tsc-demos.sh），
        新增的 install-dsh.sh 曾经漏成 100644。Windows 上 core.filemode=false，磁盘 chmod
        不会被 git 记录，只有索引里的 mode 算数，所以查索引而不是查文件系统权限位。
        """
        if not (ROOT / ".git").exists():
            self.skipTest("不在 git 工作树中，跳过索引 mode 校验")
        result = subprocess.run(
            ["git", "ls-files", "-s", "*.sh"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode != 0:
            self.skipTest(f"git 不可用：{result.stderr.strip()}")

        entries = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(entries, "仓库里一个 .sh 都没匹配到，检查 glob 是否失效")
        for line in entries:
            meta, path = line.split("\t")
            mode = meta.split()[0]
            self.assertEqual(mode, "100755", f"{path} 的索引 mode 是 {mode}，应为 100755")
            first_line = (ROOT / path).read_text(encoding="utf-8").split("\n", 1)[0]
            self.assertTrue(
                first_line.startswith("#!"),
                f"{path} 缺 shebang，可执行位对直接运行没有意义",
            )


if __name__ == "__main__":
    unittest.main()
