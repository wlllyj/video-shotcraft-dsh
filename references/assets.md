# 资产使用方式（完整清单）

SKILL.md 只保留摘要。需要用到具体组件、脚本、音频或导出模块时读本文件。

## `assets/lib/` 组件

**copy 进新项目**后自由修改，不 import 本库。

| 组件 | 用途 |
|---|---|
| PageCam | 2.5D 页面相机——一切"真实页面"镜头的地基 |
| ClipCard | 把外部视频素材 mp4 包成可被镜头卡运镜骨架驱动的"卡片主角"，含 OffthreadVideo 交叉淡化循环（素材短于镜头时无缝续播） |
| DigitRoll | 数字滚轮 |
| FlashCut | 闪切 |
| Caption | 字幕 |
| FlatPanel | 平面板（需 three 依赖） |
| VerticalTicker | 3D 无限滚动墙（纯 CSS `perspective`/`rotateX`，不需 three） |
| `helpers/` | `rand.ts` / `shake.ts` / `camera.tsx` / `motion.ts` |

只有 `FlatPanel` 与 `helpers/camera.tsx` 需要 `three` + `@react-three/fiber`（`camera.tsx` 还用到
`@remotion/three` 之外的 `useThree`/`useFrame`）；`PageCam`、`ClipCard`、`DigitRoll`、`FlashCut`、
`Caption`、`VerticalTicker`、`helpers/rand`/`shake`/`motion` 仅需 `remotion` + `react`。

## `assets/scripts/`

- `capture-template.mjs`：复制后改顶部 CONFIG（BASE / 路由 / 选择器）。
- `smoke-render-demos.py`：demo 渲染冒烟测试，见下文「测试」。

## `assets/audio/` 音效

直接复制使用，免费商用授权，见 `assets/audio/ATTRIBUTION.md`。

- `audio/bgm/`：节奏感强的 BGM 备选。
- `audio/sfx/<类别>/`：149 个音效按场景分 16 类——`transition` `impact` `riser`
  `camera` `ui` `text` `paper` `film` `light` `data` `scifi` `mech` `glass`
  `fluid` `crowd` `counter`。找音先进类别目录，清单见 `references/sound-design.md`。
- 词汇表里的 sparkle 目录名是 `light/`（没有 `sparkle/`）。
- S1 禁音色不禁动作：画面真有点击/开关就该配拟音，但 `ui/` 里一半是合成反馈音
  （tone / bleep / notification），需逐个试听、**不可整目录放行**（名单见
  `references/sound-design.md` 3.3）。
- 长样本与轻音素材各有名单需特殊处理（`references/sound-design.md` 4.1）。

## `demos/` 各卡实现源码

- 自包含的成片级 demo，共享件在 `demos/_fixtures/`：`Look.tsx`（视觉系统）、
  `Polish.tsx`（质感件）、`Brand.tsx`（品牌件）等；个别 import
  `demos/_textures/` 的真实页面纹理。
- copy 进 Remotion 项目即可跑。画面里的 logo / 品牌文案是 video-shotcraft 自己，
  给用户产品用时换成用户的标志与文案。
- 个别 demo 用到 `@remotion/motion-blur`（CameraMotionBlur），需
  `npm i @remotion/motion-blur`，名单见 `demos/README.md`。

## `template/` 完整可渲染工程

```bash
cd template && npm install
npx remotion render src/index.ts AiflPromo out/promo.mp4
```

## `gallery/` 静态画廊

- 在线版优先：https://vincentwei1021.github.io/video-shotcraft/library.html
- 本地跑：先 `gallery/fetch-media.sh` 拉样片（mp4 不在 git 里），再
  `cd gallery && python -m http.server 4178`（端口任选，4178 只是惯例）。
- 索引真源是 `gallery/api/library.json`（`cards` 数组 + `stats`），可浏览 / 搜索 /
  多选复制卡名——适合让用户看着样片挑镜头。**卡片与样式数量以该文件为准**，
  本文不硬写数字。
- 没有预览样片时，以配方卡和准确 demo TSX 源码为准。

## `jianying-export/` 剪映工程导出

- `mac_draft.py`：Mac 剪映 11.2 实测通过。
- `windows_draft.py`：按上游支持路径实现，未真机验证。
- `smoke_test.py`：新环境先跑的最小冒烟测试。
- 需 venv + `pip install pyJianYingDraft`。流程、时间线提取与建轨方法见
  `references/jianying-export.md`。

## `publish/upload_post.py` 社交平台发布

Upload-Post API，纯标准库。用户要求时把成片发到 TikTok / Instagram / YouTube /
LinkedIn / X 等，流程见 `references/publish-upload-post.md`；需
`UPLOAD_POST_API_KEY` + `UPLOAD_POST_USER`。离线单测：
`python -m unittest publish/test_upload_post.py`。

## `workbench/` 动效工作台

成片交付后主动打开：`node workbench/scripts/open.mjs <成片工程目录>`——链接工程 →
起 dev server（5198）→ 浏览器自动导入成片。工作台自身文档见 `workbench/README.md`，
制作阶段需要写 `src/workbench.ts` 清单时读 `references/workbench.md` §2–3。

## 测试（仓库内自动验证，新增 demo/组件后跑）

- 纯函数单测：`npm test`（仓库根 vitest，覆盖 `assets/lib/helpers` 的
  mulberry32 / velocityAt / lagged / dampedSettle / handheld，确定性断言）。
- demo 渲染冒烟：`python assets/scripts/smoke-render-demos.py`，渲染每个带时长
  导出 demo 的首帧断言不崩（需 `cd template && npm ci` + motion-blur，详见
  `demos/README.md` 测试与验证一节）。
- CI（`.github/workflows/pr-checks.yml`）已自动跑：tsc 严格编译全部 demo +
  vitest + 冒烟渲染。

## 跨平台注意

本库原为 macOS/Linux 开发，Windows 上：

- `python3` 一律换成 `python`；
- `*.sh` 脚本（如 `gallery/fetch-media.sh`）需要 Git Bash 或 WSL；
- 路径含空格或中文时，命令里要加引号。
