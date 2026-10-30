# DeepSeek Harness 使用指南

video-shotcraft 以 DSH 原生 filesystem skill 方式运行。安装器会把整个仓库（镜头配方卡、
Remotion 组件与 demo、已验收模板、音频资产、动效工作台、剪映导出与社交发布模块）复制到
`$DSH_HOME/skills/video-shotcraft`，默认即 `~/.dsh/skills/video-shotcraft`；DSH 扫描到
`SKILL.md` 后就会把它注册成名为 `video-shotcraft` 的 skill。

## 安装

Windows PowerShell：

```powershell
git clone https://github.com/wlllyj/video-shotcraft-dsh.git
cd video-shotcraft-dsh
.\install-dsh.ps1
```

macOS / Linux：

```bash
git clone https://github.com/wlllyj/video-shotcraft-dsh.git
cd video-shotcraft-dsh
bash install-dsh.sh
```

两个脚本都用自身所在目录定位仓库，不依赖当前工作目录；它们先执行
`python scripts/dsh_manager.py install`，再执行 `doctor` 并把结论打印出来。

也可以直接调用管理器，自己指定安装位置：

```bash
python scripts/dsh_manager.py install
python scripts/dsh_manager.py --dsh-home /path/to/dsh-home install
```

`dsh_home` 的解析顺序是 `--dsh-home` > `$DSH_HOME` > `~/.dsh`。

前置条件：Python 3.10+ 用来跑安装管理器；Node.js、npm、npx 用来做 Remotion 渲染、模板和
动效工作台。node/npm/npx 不在 PATH 上时不要紧，`doctor` 会给出明确结论（见下一节）。

## 诊断

```bash
python scripts/dsh_manager.py doctor
python scripts/dsh_manager.py --json doctor
python scripts/dsh_manager.py doctor --source-only --skip-runtime
```

- `doctor` 依次检查 SKILL.md 与 frontmatter、manifest 一致性、安装副本是否存在、所有权标记
  `.dsh-package.json` 是否有效，以及 runtime 报告（Python 版本、node/npm/npx、可选 Python
  模块）。
- `--json` 输出单个 JSON 对象，便于脚本消费。
- `--source-only` 只校验仓库源，不要求已经安装。
- `--skip-runtime` 跳过 runtime 报告，只校验打包完整性（CI 用这一档）。
- `--dsh-home` 可以和以上任意一种用法配合，检查非默认的安装位置。

非 JSON 模式下会打印 `[OK] DSH 检查通过` 或 `[FAIL] DSH 检查失败`，随后是 `  target: …`
和逐条 `  ERROR: …` / `  WARN: …`。退出码：`0` 通过、`1` 检查失败、`2` 打包错误。

如果 `node`、`npm`、`npx` 不在 PATH 上，`doctor` 会先探测 DSH 自带的 node
（`<dsh_home>/dsh-runtimes/*/dependencies/node/bin/node.exe`）：探到就降级为 WARN 并给出该
绝对路径，提示加入 PATH 或直接用绝对路径调用；没探到才是 ERROR。`npm` / `npx` 没有这种回退，
缺了就是 ERROR。

所以在一台没装 Node 的机器上，**安装会成功，但紧接着的 `doctor` 会以退出码 `1` 结束**——
`install-dsh.ps1` / `install-dsh.sh` 以 doctor 的退出码收尾，此时会打印「安装完成，但 doctor
报告存在问题」。这是环境缺依赖，不是安装失败：装上 Node（或把 npm/npx 加进 PATH）后重跑
`doctor` 即可。只校验打包完整性时用 `--skip-runtime`，它不检查 runtime，正常情况退出码为 `0`。

## 使用

装好之后不需要记命令，用自然语言说就行：

```text
用 video-shotcraft 检查这个前端项目，推荐适合的宣传片制作模式。
用 video-shotcraft 的 Ink Press 模板，为当前产品做一支 30 秒宣传片。
用 video-shotcraft 的 spotlight-hero-card 做一个独立产品特写镜头。
```

完整制作流程会创建或修改 Remotion 工程，可能执行页面截图、`npm` 安装和渲染。成片交付后
skill 会主动打开动效工作台（`node workbench/scripts/open.mjs <工程>`，地址
http://localhost:5198），并按需导出剪映工程，或在用户明确要求时发布到社交平台。

安全边界：开工前先确认目标项目目录、输出目录和制作模式；不读取或拍摄登录凭据、客户数据、
内部资料或未授权页面；页面上出现的敏感数据必须虚构或脱敏后才能入镜。

## 本地 Gallery

仓库自带静态 Gallery。动态样片 mp4 不在 git 里，本地预览时先拉取：

```bash
gallery/fetch-media.sh
cd gallery && python -m http.server 4178
```

打开 http://localhost:4178/library.html 即可按类别浏览、搜索、多选复制镜头卡名。没有本地
样片的卡片以文字说明和 demo 源码为准。镜头卡与样片的实际数量以
`gallery/api/library.json` 的 `stats` 为准（该文件由仓库脚本从镜头卡生成，会随镜头库更新）。

## 更新与卸载

```bash
git pull
python scripts/dsh_manager.py install
python scripts/dsh_manager.py doctor
python scripts/dsh_manager.py uninstall
```

- 重复 `install` 会替换本工具管理的旧副本：旧副本先改名为 `.<name>.previous`，成功后再
  删除。
- 同名目录若不是本工具安装的（没有 `.dsh-package.json` 标记），默认拒绝覆盖；
  `install --force` 会先生成 `<name>.backup-<UTC 时间戳>` 备份再安装，备份里原有文件保持
  不变。
- `uninstall` 只删除带有效所有权标记的目录，非管理目录返回 `skipped-unmanaged`，不会误删
  手工放进去的 skill。

## DSH 约定与限制

以下几点是在本机实测 DSH 行为后得到的结论，直接决定了这个 skill 为什么这样打包：

1. **没有 `{skill_dir}` 占位符替换。** DSH 不做任何 skill 目录占位符替换——`{skill_dir}`、
   `${SKILL_DIR}`、`{baseDir}` 都不存在。它会在注入的 `<skill_resources>` 里给出
   `Base directory for this skill: <绝对路径>` 一行，并指示模型把相对路径相对该目录解析。
   所以 SKILL.md 里的 `references/…`、`assets/…`、`template/…` 这类相对路径都是**相对 skill
   目录**写的，不是相对当前工作目录、也不是相对仓库根。

2. **SKILL.md body 必须控制在 8192 字符以内。** DSH 标准 preset 的 tool-result-pruner
   配置是 `thresholdChars: 8192 / headChars: 4096 / tailChars: 1024`：body 一旦超过 8192
   字符，模型看到的 skill 指令会被**掐掉中间**，只保留头 4096 字符 + 尾 1024 字符，中间换成
   一段修剪标记。注意这不是「截断到 8192」，而是**丢掉中间**——指令会残缺且很难察觉。
   `dsh_manager.py doctor` 按这个阈值校验 body 长度，超限时报出实际字符数。

3. **`metadata.dsh.compatibility` / `metadata.dsh.requires` 是惰性字段。** DSH 完全不读
   `metadata.dsh.*`，不做版本门禁、不做依赖门禁，也不会因此拒绝加载；`metadata` 只是被原样
   携带（连 `skills/list` 摘要里都没有）。真正的前置检查是
   `python scripts/dsh_manager.py doctor`，它才检查 Python 版本、node/npm/npx 和可选模块。
   保留这两个字段只是为了文档与外部工具可读，不要指望 DSH 执行它们。

4. **热重载：下一轮对话即生效，不需要重启 DSH。** 目录一旦出现在被扫描的 skill 根下，DSH
   的文件监听会触发失效重算，下一轮对话的 skill 目录随之更新（约 200ms 防抖）。安装或更新
   完成后直接开始下一句对话即可。反过来，把 `SKILL.md` 改名（例如 `SKILL.md.disabled`）就能
   让它从目录里消失，不必删除整个目录。

5. **没有「按 profile 分开的 skills 目录」。** 所有 profile 共用同一个 `<dsh_home>/skills`
   （本机即 `~/.dsh/skills`）。不存在 `profiles/<name>/skills/` 这种按 profile 隔离的 skill
   目录，装一次就对所有 profile 生效。

6. **扫描只认一层深。** DSH 只识别 `skills/<name>/SKILL.md`（一层目录）和
   `skills/<name>.md`（顶层文件）。嵌套的 `**/SKILL.md`（例如 `skills/vendor/pkg/SKILL.md`）
   **不会**被发现。所以安装位置必须是 `<dsh_home>/skills/video-shotcraft/SKILL.md`，不能再
   多套一层子目录。

补充两条实测事实：skill 根下的 `.system` 子目录会被跳过；同名 skill 按 rank 先到先得，
项目级 `<project>/.dsh/skills` 是 rank 100，用户级 `<dsh_home>/skills` 是 rank 400，所以
项目级会盖掉用户级。

## 本仓库与上游的差异

先说基线，否则很容易把上游的东西当成 fork 的增量：本仓库的 tracked 内容与上游
`Vincentwei1021/video-shotcraft` 的 `#121`（`5a2e98d`）**逐字节相同**，本 fork 目前还没有
自己的提交——DSH 适配全部是工作区里新增的文件。所以「差异」要分两类看。

### 一、本 fork 真正新增（上游 main 里没有）

DSH 适配与打包层，共八个文件：

| 路径 | 作用 |
| --- | --- |
| `dsh/manifest.json` | skill 包清单（schema、版本、目标目录、runtime 声明） |
| `scripts/dsh_manager.py` | `install` / `doctor` / `uninstall` 管理器 |
| `install-dsh.ps1`、`install-dsh.sh` | Windows 与 macOS/Linux 的一键入口 |
| `tests/test_dsh_package.py` | 打包一致性、frontmatter、runtime 报告的单测 |
| `.github/workflows/checks.yml` | 打包层 CI：compileall + 打包单测 + 打包完整性 |
| `docs/deepseek-harness.md` | 本文 |
| `NOTICE` | 版权与改动声明 |

`checks.yml` 刻意不重复上游 `pr-checks.yml` 已有的 gallery 生成物校验和 demo
`tsc` 编译——同一个 PR 上跑两遍只是白烧 runner。它只补上游没有的 Python 打包校验。

以上路径在上游 `main` 中全部不存在，可以用
`git cat-file -e upstream/main:<路径>` 逐条复核。

另外工作区里还有两个上游没有的 skill 内容文档：`references/assets.md`（完整资产清单）与
`references/delivery-closeout.md`（交付收尾流程）。它们属于 skill 正文的补充，不是 DSH
适配层，这里只提一句以免与上面混为一类。

### 二、上游已有、本仓库原样保留（不是 fork 的增量）

下面这些常被误认为是 fork 加的东西，其实是**上游自己的特性**——只是
`kingselyjoe/video-shotcraft-dsh`（2026-08-19 的早期 fork 快照）里还没有，对比时容易看错：

- `workbench/`：交付后自动打开的动效工作台（多轨时间线 + 素材库 + 属性面板 + Remotion
  实时预览 + 一键导出），移植自 video-talkcraft，上游 `#72` 引入。
- `publish/`：成片一键发布到社交平台（Upload-Post），上游 `#93` 引入。
- `jianying-export/`：导出剪映工程，含 `smoke_test.py` 冒烟测试，上游 `#36` 引入。
- `shot-polish/`：镜头重设计的工作台与素材，含 `tsc-demos.sh` 类型检查脚本，上游 `#95` 引入。
- `assets/lib/ClipCard.tsx`：把外部 mp4 包成「卡片主角」，让 spotlight-hero-card 这类为
  DOM/SVG 主体设计的卡片也能驱动真实素材，上游 `#39` 引入。
- `demos/_legacy/`：冻结的已下架镜头实现，只为解析旧工程的 `demo:<Stem>` cardId，上游 `#95`
  引入；不进入素材库与画廊。

判断某个路径到底属于哪一类，用 `git cat-file -e upstream/main:<路径>` 或
`git log --oneline upstream/main -- <路径>` 直接查，比对着另一份 fork 猜要可靠。
