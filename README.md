# ClipLab

[English README](./README_EN.md)

ClipLab 是一个本地优先的桌面视频工具，当前以 `macOS` 为首发目标，工程结构同时兼顾 `Windows` 打包。项目由 `Electron + React + TypeScript` 桌面端和 `FastAPI` 本地后端组成，适合处理“复制分享文案 -> 提取真实链接 -> 下载原视频”这类桌面工作流。

## 界面预览

![ClipLab Preview](./docs/images/app-preview.svg)

## 功能概览

- 支持从整段分享文案中提取真实视频链接
- 当前支持平台：`抖音`、`快手`
- 桌面端支持批量输入下载
- 支持“添加”按钮动态增加输入框
- 支持“粘贴”按钮直接读取系统剪贴板
- 下载文件名优先使用作品标题
- 标题超过 `10` 个汉字时自动截断
- 同名文件自动避让，避免覆盖
- 设置页支持可选的 `Douyin Cookie` / `Kuaishou Cookie` 兜底
- 支持本地视频手动框选区域去水印
- 支持局域网 `/remote` 页面提交下载任务
- SQLite 持久化任务和日志，SSE 实时推送任务状态

## 当前实现边界

- 下载链路目前只实现了抖音、快手单作品下载
- 不支持二维码登录
- 默认优先走免登录下载；只有遇到风控或解析失败时，才建议在设置页填写 Cookie
- `Windows` 工程结构已预留，但目前主要按 `macOS` 开发和验证

## 技术栈

- 桌面端：`Electron`、`React 18`、`TypeScript`、`Vite`
- 后端：`Python 3.12`、`FastAPI`
- 依赖工具：`uv`、`ffmpeg`、`curl`
- 数据存储：`SQLite`

## 系统依赖

建议安装以下依赖：

- `Node.js 22+`
- `Python 3.12+`
- `uv`
- `ffmpeg`
- `curl`

在 macOS 上可直接使用 Homebrew：

```bash
brew install node@22 python@3.12 uv ffmpeg curl
```

如果你希望 `npm run dev:clean` 能自动检查并回收占用端口的旧进程，系统里还需要有 `lsof`。macOS 通常自带。

## 快速开始

### 1. 安装前端依赖

```bash
npm install
```

### 2. 安装后端依赖

```bash
uv sync --project backend --extra dev
```

如果你还想启用更完整的 STTN 推理运行时，再额外安装：

```bash
uv sync --project backend --extra dev --extra sttn
```

### 3. 启动桌面开发环境

```bash
npm run dev
```

这会同时启动：

- 前端构建监听
- 本地 FastAPI 后端
- Electron 编译监听
- Electron 桌面应用

### 4. 局域网模式启动

如果你希望手机或其他设备访问本机的提交页：

```bash
npm run dev:lan
```

这个模式会让后端监听 `0.0.0.0:8765`，桌面端设置页会展示可访问的局域网地址。

### 5. 手动清理开发残留进程

```bash
npm run stop
```

## 常用命令

```bash
npm run dev
npm run dev:lan
npm run lint
npm run build
npm run package
npm run stop
uv run --project backend --with pytest pytest -q backend/tests
```

## 使用说明

### 下载视频

1. 打开桌面端的“链接下载”页
2. 选择输出目录
3. 将分享文案或真实链接粘贴到输入框
4. 如需批量下载，点击“添加”继续增加输入框
5. 如需直接读取系统剪贴板，点击“粘贴”
6. 点击“下载”
7. 任务会自动出现在“任务列表”页

支持的输入形式包括：

- 纯链接
- 抖音分享文案
- 快手分享文案
- 一段话里夹带一个有效视频链接的文本

### Cookie 兜底

默认不需要登录。

如果遇到这些情况，可以在“设置”页填写 Cookie：

- 抖音解析失败
- 平台触发风控
- 下载地址返回异常

目前只支持手动填写 Cookie，不支持二维码扫码登录。

### 去水印

1. 打开“去水印”页
2. 选择本地视频
3. 在预览区拖动框选水印区域
4. 点击“创建去水印任务”

### 手机 / 局域网提交

1. 使用 `npm run dev:lan` 启动
2. 在桌面端“设置”页查看 `手机提交页` 地址
3. 在同一局域网设备浏览器中打开 `/remote`
4. 粘贴分享文案或链接后提交

手机端提交的任务会进入同一个本地任务队列，并在桌面端实时同步。

## 文件命名规则

- 文件名优先使用作品标题
- 会自动清理文件系统非法字符
- 如果标题不超过 `10` 个汉字，直接使用标题
- 如果标题超过 `10` 个汉字，截到第 `10` 个汉字为止
- 如果标题为空，则回退为 `<platform>_<resolvedId>.mp4`
- 如果同名文件已存在，则自动追加 ` (2)`、` (3)` 这类后缀

## 项目结构

```text
ClipLab/
├─ electron/                    # Electron 主进程与 preload
├─ src/                         # React 渲染层与共享类型
├─ backend/
│  ├─ cliplab_backend/
│  │  ├─ services/              # 平台解析、下载、任务、模型、去水印逻辑
│  │  ├─ storage/               # SQLite 持久化
│  │  └─ main.py                # FastAPI 入口
│  └─ tests/                    # 后端测试
├─ scripts/                     # 开发辅助脚本
├─ docs/                        # README 预览图等文档资源
├─ app-data/                    # 运行期生成的数据目录（已忽略）
└─ tmp/                         # 本地参考项目目录（已忽略）
```

## 图标放置位置

请将你的软件图标放到：

- `public/assets/icons/app-icon.png`

当前程序会优先用这张图作为：

- 左上角品牌图标
- Electron 窗口图标
- macOS Dock 图标

正式打包时，脚本会基于这张 PNG 自动生成：

- macOS 所需的 `.icns`
- Windows 所需的 `.ico`

因此你只需要维护这一张源图即可。

## 环境变量

后端支持以下环境变量：

- `CLIPLAB_APP_DATA`
  - 指定应用数据目录
- `CLIPLAB_BACKEND_URL`
  - 覆盖桌面端连接的后端地址
- `CLIPLAB_FFMPEG_PATH`
  - 指定 `ffmpeg` 可执行文件路径
- `CLIPLAB_STTN_AUTO_MODEL_URL`
  - 配置 `sttn_auto` 模型下载地址
- `CLIPLAB_LAMA_MODEL_URL`
  - 配置 `lama` 模型下载地址
- `CLIPLAB_PID_FILE`
  - 指定后端 PID 文件位置

默认情况下，应用数据会写到仓库下的 `app-data/`，其中包括：

- `cliplab.sqlite3`
- `logs/`
- `models/`
- 默认输出目录 `ClipLab/`

## 测试与校验

### TypeScript / Electron 类型检查

```bash
npm run lint
```

### 后端测试

```bash
uv run --project backend --with pytest pytest -q backend/tests
```

## 打包

```bash
npm run build
npm run package
```

日常开发不需要每次都打包。

只有在你要验证发布结果或准备分发安装包时，才需要执行打包命令。

### 打包前准备

发布版现在采用“Electron 前端 + 本地 Python 后端二进制”的结构。

也就是说，正式打包前需要先准备好当前平台的后端可执行文件，脚本会自动完成这一步：

- `node scripts/prepare-app-icons.mjs`
- `node scripts/build-backend-binary.mjs`
- 或直接执行完整打包命令，由它先构建后端再调用 `electron-builder`

首次执行时会额外下载：

- `electron-builder` 需要的 Electron 运行时
- `png-to-ico` 依赖的 Node 打包能力（安装依赖时）
- `uv run --with pyinstaller` 需要的 `PyInstaller`
- 后端内置使用的 `imageio-ffmpeg`

因此首次打包需要联网。

### macOS 打包

在 macOS 机器上执行：

```bash
npm run package:mac
```

脚本会依次执行：

1. `node scripts/prepare-app-icons.mjs --platform=mac`
2. `npm run build`
3. `node scripts/build-backend-binary.mjs`
4. `electron-builder --mac dmg --<当前机器架构>`

默认会生成当前机器架构对应的安装包：

- Apple Silicon 机器通常输出 `arm64` 的 `dmg`
- Intel Mac 通常输出 `x64` 的 `dmg`

产物会写到 `dist/` 目录，例如：

- `dist/ClipLab-0.1.0-arm64.dmg`

### Windows 打包

在 Windows 机器上执行：

```bash
npm run package:win
```

脚本会依次执行：

1. `node scripts/prepare-app-icons.mjs --platform=win`
2. `npm run build`
3. `node scripts/build-backend-binary.mjs`
4. `electron-builder --win nsis --<当前机器架构>`

产物同样会输出到 `dist/` 目录，通常会得到：

- `nsis` 安装包
- `win-<arch>-unpacked/` 目录

### 当前打包策略与限制

- 当前脚本只支持“在目标平台的原生机器上打包该平台的包”。
- 原因是桌面端会随应用一起分发一个本地 Python 后端二进制，不适合在另一种平台或另一种 CPU 架构上盲目交叉构建。
- 例如：应当在 macOS 机器上打 `macOS` 包，在 Windows 机器上打 `Windows` 包。
- 如果你后面要额外做 `macOS x64`、`macOS universal`、`Windows arm64` 这类包，建议分别在匹配的平台与架构环境中单独构建并验证。

### 打包注意事项

- 打包图标统一从 `public/assets/icons/app-icon.png` 自动生成；这张图必须是正方形 PNG，尺寸小于 `1024x1024` 时脚本会警告，但仍允许继续打包。
- 当前正式包会优先使用内置的 `imageio-ffmpeg`，不再默认依赖目标机器是否安装系统 `ffmpeg`。
- 下载链路当前也直接调用系统 `curl`；在大多数现代 macOS / Windows 环境通常可用，但如果你要做更稳的离线分发，后续最好一起评估是否内置。
- macOS 正式分发前，建议补上 `Developer ID Application` 签名与 notarization；否则其他机器上可能会遇到 Gatekeeper 提示。
- 第一次运行打包脚本时耗时会明显更长，因为要下载 Electron 运行时和 PyInstaller 相关依赖。
- 如果去水印视频处理成功但音轨合并失败，任务会保留静音结果并在任务列表和日志里给出明确 warning，不再静默吞掉问题。

### 手动拆分执行

如果你想单独验证每一步，也可以分开执行：

```bash
node scripts/prepare-app-icons.mjs --platform=mac
npm run build
node scripts/build-backend-binary.mjs
npx electron-builder --mac dmg --arm64
```

或在 Windows 上：

```bash
node scripts/prepare-app-icons.mjs --platform=win
npm run build
node scripts/build-backend-binary.mjs
npx electron-builder --win nsis --x64
```

## 已验证的下载样例

当前代码已在本地验证以下两条分享文案可以成功下载到原视频：

- 你提供的抖音分享文案
- 你提供的快手分享文案

## 故障排查

### 1. `ffmpeg` 找不到

- 确认系统已安装 `ffmpeg`
- 或通过 `CLIPLAB_FFMPEG_PATH` 指定路径

### 2. 抖音解析失败

- 先重试一次
- 如果仍失败，在设置页填写抖音 Cookie 再试

### 3. 端口 `8765` 被占用

```bash
npm run stop
```

如果还不行，检查是否有其他服务占用了 `8765`。

### 4. 局域网访问不到 `/remote`

- 确认使用的是 `npm run dev:lan`
- 确认设备处于同一局域网
- 确认本机防火墙没有拦截 `8765`
