<p align="center">
  <img src="desktop/src-tauri/icons/icon.svg" width="104" alt="QM Unlock logo">
</p>

<h1 align="center">QM Unlock</h1>

<p align="center"><strong>将本地 QQ 音乐下载还原为标准音频，配齐专辑封面与同步歌词。</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Desktop-Rust%20%2B%20Tauri-151515" alt="Rust and Tauri desktop">
  <img src="https://img.shields.io/badge/UI-React%20%2B%20TypeScript-3178C6" alt="React and TypeScript UI">
  <img src="https://img.shields.io/badge/Batch-Python-3776AB" alt="Python batch CLI">
  <img src="https://img.shields.io/badge/License-MIT-60B932" alt="MIT license">
</p>

QM Unlock 面向已下载到本机的 QQ 音乐 `musicex V1` 文件，提供两个入口：

- **桌面应用**：Rust 后端、Tauri 2 应用框架及 React / TypeScript 界面，支持拖放队列、自动获取密钥、封面歌词、目录监听与命名模板。
- **批量命令行**：沿用项目原有的 Python 入口，提供「解码＋封面」和「解码＋封面＋歌词」两种模式，默认保留原音频编码并做完整校验，也可为已经解密的音频补充封面、歌词。

本仓库是 [mary20050520/qmunlock](https://github.com/mary20050520/qmunlock) 的 Fork。在保留原有桌面功能的基础上，完善了 macOS 登录文件查找、批量命令行、音频校验、封面与 LRC 配对，并增加回归测试。

> **当前开发重点是 Python 命令行。新增的两种批量模式、封面与歌词处理及强化校验以 CLI 为准；Rust 桌面端有待同步。原有桌面功能继续保留，支持范围见下表。**

仅处理你有权访问的本地音频。项目不提供歌曲下载、帐号登录或无权限资源访问功能；参见[免责声明](DISCLAIMER.md)。

## 功能总览

| 功能 | 桌面应用：Rust / Tauri | 批量命令行：Python |
| --- | --- | --- |
| 新版 QQ 音乐解密 | `musicex V1`，支持多文件及文件夹 | `musicex V1`，支持单文件及递归目录 |
| 原格式输出 | 支持，界面默认原格式 | 支持，命令行默认原格式 |
| MP3 输出 | FFmpeg / LAME 转码，生成新文件 | 保留历史转码入口，见[格式与音质](#格式与音质) |
| 自动获取 ekey | macOS 本地登录信息；Windows 已登录客户端进程 | 自动读取 macOS 登录信息，每首分别获取 ekey |
| 手动 ekey | 界面支持 | CLI 未提供手动 ekey 参数 |
| macOS 双位置登录查找 | 容器及用户资源库 | 容器及用户资源库 |
| 专辑封面 | FLAC、MP3 内嵌；macOS 可设置访达图标 | FLAC、OGG Vorbis、MP3、M4A 内嵌，已有封面保留 |
| 同名 LRC | 可选，与音频同目录或指定目录 | `audio-lyrics` 模式，固定与最终音频同目录同名 |
| MP3 内嵌歌词 | 普通歌词；实验性 ID3 `SYLT` 同步歌词 | 当前采用外挂 LRC，不写入 `SYLT` |
| 普通音频增强 | 支持曲库匹配、封面及歌词；可选原位或副本 | 保留音频编码，按同名原始下载文件精确补元数据 |
| 整首解码及 FLAC 校验 | 强化校验有待同步 | 默认启用，失败单独报告 |
| 封面写入后音频流及时间参数校验 | 保留原有检查；强化校验有待同步 | 临时副本校验通过后更新目标文件 |
| 下载目录监听 | 支持稳定检测、逐批处理 | 无常驻监听 |
| 处理历史、重复跳过 | 本地处理历史，默认跳过已完成任务 | 已有封面及可识别 LRC 不重复下载；无桌面历史库 |
| 自定义命名模板 | 支持歌手、专辑、曲序等标签及子目录 | 保留源文件名，同名原格式输出编号另存 |
| JSON 结果报告 | 内部任务结果及本机处理历史 | `--report` 导出逐文件音频、封面、歌词状态 |
| 深浅主题、打开输出目录 | 支持 | 使用终端和文件管理器 |

<p align="center">
  <img src="docs/assets/qmunlock-banner-macos.png" width="920" alt="QM Unlock 桌面应用的队列、输出格式、封面和歌词设置">
</p>

<p align="center"><sub>原有桌面应用界面；新增的两种批量模式使用下文 Python 命令行入口。</sub></p>

## 支持的文件与平台

### 文件格式

| 输入 | 常见原格式输出 | 说明 |
| --- | --- | --- |
| `.mflac` | `.flac` | 需要有效的 `musicex V1` 文件尾及对应 ekey |
| `.mgg` | `.ogg` | 同上，通常为 OGG Vorbis 音频 |
| `.mmp4` | `.m4a` | 同上，保留对应音频容器与编码 |
| `.flac`、`.ogg`、`.mp3`、`.m4a` | 保留现有格式 | 可用于已有音频的封面、歌词处理 |
| `.opus`、`.wav` | 桌面原格式处理入口 | 不属于当前 CLI 内嵌封面支持范围；桌面随包精简 FFmpeg 不支持它们转 MP3 |

扩展名不能单独确定加密版本或实际编码。加密输入必须有有效的 `musicex V1` 文件尾；实际输出按解密后的内容识别。

**不支持旧 QMC 解密体系**，包括 `.qmc*`、`.bkcmp3`、QTag、STag 等。桌面端可识别某些扩展名为 `.mgg` / `.mflac`、但内容已经是普通音频的文件，并按真实格式另存；不要把这一行为理解为支持全部历史加密版本。

### 平台范围

| 平台 | 当前范围 |
| --- | --- |
| macOS Apple Silicon | 桌面开发测试及 CLI 批量实测平台 |
| macOS Intel | 桌面构建目标；本 Fork 的新增功能尚未做 Intel 实机验证 |
| Windows x64 | 桌面构建目标；沿用 Windows 客户端凭据读取，本 Fork 尚未做 Windows 实机验证 |
| Python CLI | 当前自动登录实现针对 macOS；`--platform 27` 只改变接口平台参数，不会增加 Windows 进程凭据读取能力 |

QQ 音乐更新可能改变本地存储或接口行为，项目不承诺兼容所有客户端版本。

## 快速开始：桌面应用

1. 从[本仓库 Releases](https://github.com/30466/qmunlock/releases) 查看实际发布的安装包，选择对应系统和架构。若所需源码功能尚未包含在发布版本中，请使用命令行或[自行构建](#开发与构建)。
2. macOS 将 App 从 DMG 拖入「应用程序」后运行；在 QQ 音乐客户端完成登录。
3. 拖入文件或整个文件夹，也可使用「选择文件」「文件夹」加入队列。
4. 选择「原格式」或「MP3」，按需勾选封面、歌词；选择输出目录。
5. 点击底部处理按钮，查看逐文件结果；完成后可打开输出目录。

桌面界面默认使用原格式和自动 ekey，封面默认开启，歌词默认关闭。建议先处理一首，确认格式、目录与播放器表现，再处理整批。

### 原有桌面功能

- **统一队列**：混合加入加密文件和普通音频，逐文件显示状态与进度。
- **普通音频处理**：可做封面、歌词增强；原格式处理可选原位更新或生成副本。OGG、FLAC、M4A 可转为新 MP3；已有 MP3 不重复转码。
- **封面与标签**：FLAC / MP3 支持内嵌封面；MP3 可补歌名、歌手、专辑、专辑艺人、年份、曲序、碟号。macOS 的访达自定义图标是额外显示效果，不等同于播放器可读的内嵌封面。
- **歌词**：输出同名 LRC；MP3 还可写入普通内嵌歌词。`SYLT` 同步歌词为实验性功能，播放器兼容性不同。
- **输出保护**：副本与新 MP3 使用编号避开同名文件。选择原位增强时会修改普通音频的元数据。
- **使用体验**：深浅主题、输出目录选择、打开输出目录、逐文件失败反馈。

### 下载目录监听与处理历史

「监听文件夹」每 2 秒检查一次；文件连续两次大小及修改时间稳定、格式就绪后加入队列。已有文件需要手动导入，重启应用后需要重新开启监听。

监听仅扫描浅层目录：最多 2 层子目录、2,000 个条目；跳过隐藏目录和 `Library`、`node_modules`、`*.app` 等目录。磁盘根目录、用户主目录或超限目录会被拒绝，请选择具体的 QQ 音乐下载目录。

监听输出放在独立目录或子目录，默认使用下载目录下的「QM Unlock 输出」，防止产物再次入队。批次串行执行，处理期间暂停轮询；未确认的文件版本会在后续轮询重试。

「跳过已转换文件」默认开启。应用根据源文件状态、处理选项及输出存在性复用成功结果；可关闭跳过以重新处理。历史保存在应用数据目录的 `processing-history.json`，最多 10,000 条，载入及批次结束时清理已删除输出的记录。侧栏可清除处理历史，路径偏好单独保留。

### 输出命名模板

可保留源文件名，或使用内置 / 自定义模板：

| 模板 | 示例 |
| --- | --- |
| `{filename}` | 原文件名.flac |
| `{artist} - {title}` | 歌手 - 歌名.flac |
| `{album}/{track} {title}` | 专辑/01 歌名.flac |
| `{albumartist}/{year} - {album}/{track} {title}` | 专辑艺人/年份 - 专辑/01 歌名.flac |

支持 `{artist}`、`{title}`、`{album}`、`{albumartist}`、`{year}`、`{disc}`、`{track}`、`{filename}`；`/` 用于子目录。缺失字段按界面提示回退，绝对路径、`..` 和未知占位符会被拒绝；文件名按 UTF-8 字节限制安全截断。

启用命名模板或自动监听时，普通音频生成副本；LRC 随最终音频文件名命名。命令行目前没有这套模板功能。

## 快速开始：批量命令行

### 安装依赖

CLI 不需要 Node.js、Rust 或桌面 App。需要 Python、FFmpeg、FLAC 命令行工具及 `requirements.txt` 中的 Python 依赖；本 Fork 使用 Python 3.12 验证。

在 macOS 上，已安装 Homebrew 时可执行：

```bash
brew install ffmpeg flac

git clone https://github.com/30466/qmunlock.git
cd qmunlock
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

其中 Mutagen 负责封面标签，FFmpeg 负责音频检查 / 兼容转码，`flac` 负责 FLAC 完整性检查。CLI 使用系统工具；桌面发布包则使用随包的 FFmpeg，两者的依赖来源不同。

### 两个模式

| 选项 | 处理内容 |
| --- | --- |
| `--mode audio` | **解码＋封面**，默认模式 |
| `--mode audio-lyrics` | **解码＋封面＋歌词** |

两种模式默认保留原编码并启用完整校验，不必另外开启封面开关。已有正面封面会保留；对应专辑没有可用封面时跳过。

```bash
# 默认模式：解码＋封面
python3 cli.py "/path/to/downloads" "/path/to/output"

# 解码＋封面＋同名 LRC
python3 cli.py "/path/to/downloads" "/path/to/output" \
  --mode audio-lyrics --report "/path/to/batch-report.json"
```

默认输出到输入文件同目录，建议指定独立输出目录。文件夹输入会递归扫描；macOS 的 `._` 元数据文件不会作为音频处理。

### 为已有音频补封面、歌词

无需再次解密或转码，直接处理音频所在目录：

```bash
python3 cli.py "/path/to/existing-audio" \
  --mode audio-lyrics \
  --metadata-dir "/path/to/original-downloads" \
  --report "/path/to/enrichment-report.json"
```

`--metadata-dir` 指向保留原始 `.mflac` / `.mgg` / `.mmp4` 的目录。脚本按同名文件读取歌曲 MID，获取该版本的专辑及歌词，不做模糊歌名搜索；同名原文件对应多个 MID 时报告冲突。

已有正面封面和可识别的同名 LRC 都齐全时，直接跳过，不再需要原始下载文件。只补封面可使用默认的 `audio` 模式。处理已有音频时省略输出目录，封面写入音频标签，LRC 留在音频旁。

### 参数与结果

| 参数 | 含义 |
| --- | --- |
| `target` | 加密文件、普通音频或目录 |
| `outdir` | 新解密文件的输出目录；已有音频增强时省略 |
| `--mode` | `audio` 或 `audio-lyrics` |
| `--format` | 默认 `original`；`mp3` 为历史兼容转码入口 |
| `--verify` | 兼容参数，CLI 默认已启用整首校验 |
| `--metadata-dir` | 已有音频所对应的原始下载目录 |
| `--report` | JSON 报告路径 |
| `--list` | 只列出加密扩展名文件，不解密 |
| `--creds` | 检查本机登录信息，不显示帐号或令牌 |
| `--platform` | QQ 音乐接口平台参数，默认 `20`；不改变凭据读取实现 |

```bash
python3 cli.py --help
python3 cli.py --creds
python3 cli.py --list "/path/to/downloads"
```

终端与 JSON 分别报告音频、封面和歌词状态。没有对应封面允许跳过；歌词缺失、版本冲突、网络失败、标签写入或校验失败会明确记录。歌词失败不会删除已成功的音频，已有 LRC 不覆盖。

只要有请求的项目未完成，CLI 返回非零状态；报告不包含歌词正文、登录凭据或 ekey，但包含输入 / 输出路径。

## 音质、完整性与时长

### 格式与音质

- **原格式解密**还原原有音频字节，不重新压缩。原本是 FLAC 才能保留其无损音质；原本是 OGG / AAC 等有损编码，不会因改后缀或转 FLAC 变成无损音源。
- **补封面**修改标签元数据，音频流不重新编码。文件整体哈希会因封面变化，但不代表音频内容变化。
- **输出 MP3**属于有损转码。桌面端用 FFmpeg / LAME 生成新文件；CLI 的 MP3 入口沿用旧转换实现，可能按环境回退到其他格式，且同名转码目标的保护未与原格式流程统一，建议使用空输出目录。
- 新批量流程的保真验证主要围绕默认的 `original` 模式；不要用 MP3 转码结果代替无损还原结果。

### CLI 的检查与写入保护

1. 解密后识别文件头，未知音频不作为成功输出；MP3 识别不再只检查首字节 `FF`。
2. 完整解码音轨，FLAC 另做完整性检查。
3. 新解密 FLAC 若含有界的多余尾部，只有声明的全部采样存在、清理后校验也通过，才保留结果。无法确认完整音频时报告失败，不强行截断。
4. 原格式解密输出使用独占创建；同名文件编号另存，校验失败清理本次新建的输出，保留加密源文件。
5. 已有音频只做只读检查，不自动修剪其尾部。
6. 封面先写入临时副本；核对编码音频流摘要以及时长、采样率、声道、位深参数，并通过完整性检查后，再更新目标文件。校验失败保留原文件。

`.flac` 后缀不代表文件一定采用原生 FLAC 封装。例如 MP4 容器里的 FLAC 音轨若误标为 `.flac`，电脑可能能播放，其他播放器却可能误判。CLI 校验会拒绝这类误标文件，项目没有把通用封装修复当作正常解密功能。文件校验通过也不等于所有播放器固件均已实测。

## 封面、LRC 与播放器

CLI 支持 FLAC、OGG Vorbis、MP3、M4A 的标准内嵌封面；桌面端目前内嵌 FLAC / MP3，其余格式可能仅有 macOS 访达图标。两者不要混淆。

LRC 是带时间戳的文本。播放器通常按**同目录、同文件名**匹配，不需要一首歌建一个文件夹：

```text
Music/
├── 歌手-歌曲一.flac
├── 歌手-歌曲一.lrc
├── 歌手-歌曲二.ogg
└── 歌手-歌曲二.lrc
```

重命名或移动歌曲时，同步处理对应 LRC。现场版、录音室版及不同剪辑版的歌词时间轴不可混用。CLI 导出 UTF-8、保留时间戳的 LRC，纯音乐占位文本及无时间轴文本不冒充同步歌词。

将音频与 LRC 一起复制到播放器，必要时重新扫描曲库，并在歌词页确认显示与同步效果。使用外挂 LRC 无需把 FLAC 转成 MP3。

## 自动登录与权限

### macOS

Rust 桌面端与 Python CLI 都会检查：

```text
~/Library/Containers/com.tencent.QQMusicMac/Data/Library/Preferences/com.tencent.QQMusicMac.plist
~/Library/Preferences/com.tencent.QQMusicMac.plist
```

一个位置缺失、归档不可用或不可读时继续尝试另一个位置；无需为了兼容路径而复制登录文件或建立符号链接。Python API 显式指定某个 plist 时只读取该文件，避免切换到另一份帐号信息。

先在 QQ 音乐完成登录。若桌面应用提示访问权限不足，在「系统设置 → 隐私与安全性 → 完全磁盘访问权限」中手动添加「应用程序」里的 QM Unlock，并重新打开应用。

系统设置页面可以由应用打开，但添加应用和授权开关仍由用户操作。ad-hoc 签名的包更新后可能需要删除旧授权条目、重新添加；不要直接在 DMG 内运行 App。CLI 的访问权限取决于承载它的终端或运行宿主。

### Windows 桌面端

保持 QQ 音乐客户端运行并登录。QM Unlock 与 QQ 音乐使用相同权限级别；QQ 音乐为普通权限时，QM Unlock 也用普通权限，只有客户端以管理员身份运行时才需要匹配提升权限。

### 手动 ekey 的范围

桌面应用可手动粘贴对应 ekey。密钥通常对应具体歌曲资源，不能把一首歌的密钥套用到整个文件夹。批量处理优先使用自动获取。

## 项目结构与技术栈

| 部分 | 语言 / 工具 | 职责 |
| --- | --- | --- |
| `desktop/src/` | React、TypeScript、Vite | 桌面队列、设置、进度、监听界面 |
| `desktop/src-tauri/` | Rust、Tauri 2、Tokio、Reqwest | 桌面命令、登录信息、密钥请求、QMC2 解密、标签、监听、历史及命名 |
| `cli.py`、`qmunlock/` | Python | 批量入口、另一套解密实现、封面与 LRC、完整校验、结果报告 |
| Mutagen | Python 依赖 | CLI 音频标签与内嵌图片 |
| FFmpeg / FLAC | 外部工具 | 转码、解码检查及 FLAC 完整性检查 |
| `tests/` | Python 测试 | 虚构登录、生成音频、批量、封面、歌词、时长和文件保护回归 |
| Rust 模块内 `#[test]` | Rust 测试 | 桌面后端、算法、标签、命名及监听回归 |
| `scripts/check-local.sh` | Shell | 本地检查入口 |
| `.github/workflows/` | GitHub Actions | 桌面 CI、开发构建及安装包发布 |

## 开发与构建

### 桌面开发

准备 Rust stable、Node.js（CI 使用 22）及对应平台的 Tauri 系统依赖：

```bash
cd desktop
npm ci
npm run tauri dev
```

桌面运行不需要安装 Python CLI 的 Mutagen 依赖。开发环境可从 `PATH` 使用 FFmpeg；发布安装包需准备随包的 LGPL FFmpeg，构建方法见 [desktop/README.md](desktop/README.md) 与 [FFmpeg 资源说明](desktop/src-tauri/resources/ffmpeg/README.md)。

### 桌面构建

```bash
cd desktop
npm ci
npm run tauri -- build
```

仓库的发布工作流配置了 macOS Apple Silicon、macOS Intel 与 Windows x64 目标。正式签名、DMG 布局、FFmpeg 资源及发布步骤见 [docs/RELEASING.md](docs/RELEASING.md)。

仅运行 `npm run build` 会构建前端资源，不会更新已安装的桌面应用；桌面源码修改需要 Tauri 构建、打包并安装对应产物。

### 本地验证

在仓库根目录激活 Python 环境、安装依赖，并准备桌面前端依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
(cd desktop && npm ci)
./scripts/check-local.sh
```

等价的主要检查为：

```bash
python3 -m pytest tests/ -q
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check
cargo test --manifest-path desktop/src-tauri/Cargo.toml
cargo clippy --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
(cd desktop && npm run build)
```

依赖 FFmpeg 的 Rust 音频集成测试默认忽略，可单独运行：

```bash
cargo test --manifest-path desktop/src-tauri/Cargo.toml -- --ignored
```

Python 音频 / 封面测试在缺少对应工具时会跳过，检查测试结果中的 skipped 数量。自动化测试使用生成音频及虚构数据，不需要 QQ 音乐帐号，不请求真实歌词或封面。

## 验证记录

以下是本 Fork 在 macOS Apple Silicon 上的验证范围，不代表所有平台或播放器已验证：

| 项目 | 结果 |
| --- | --- |
| Python 回归 | 40 项测试及 4 个子测试通过 |
| Rust 回归 | 39 项默认测试通过，另 1 项音频集成测试单独通过 |
| 工程检查 | Rust fmt、Clippy、TypeScript 检查及前端构建通过 |
| 加密输入样例 | 新 CLI 的 FLAC / OGG 加密样例解密校验通过，两个处理模式另有端到端样例验证 |
| 批量音频检查 | 203 首，含 195 首 FLAC 与 8 首 OGG，完整解码及对应完整性检查通过 |
| 歌词 | 203 个同名 LRC，UTF-8 与时间戳检查通过 |
| 封面 | 203 首补齐内嵌封面，编码音频流摘要与时间参数未变，原有 LRC 未变化 |

这些文件级验证不包含 M5 Ultra 等播放器的全部固件兼容性测试。回归测试覆盖 MP4 误标 FLAC、错误音频头、尾部异常、歌词缺失、已有文件保护，以及封面写入后音频或时长变化时拒绝替换等情况。

## 隐私与本地数据

解密、转码、标签写入和校验在本机执行，音频内容不会上传。获取 ekey、曲目信息、专辑封面和歌词会访问 QQ 音乐及图片服务；自动获取 ekey 会使用本机登录状态，元数据请求包含歌曲 MID 等资源标识。桌面端对普通音频做曲库匹配时，还可能发送由文件名或标签生成的检索词。

- 登录凭据、手动 ekey 不写入项目报告或桌面处理历史；CLI 也不显示帐号或令牌。
- 桌面历史保存输入 / 输出完整路径、处理选项及结果；目录偏好保存在 WebView localStorage。
- CLI 的 `--report` 包含文件路径和处理状态，不包含歌词正文、登录令牌或 ekey。
- CLI 在进程内缓存部分曲目信息与封面；下载的 LRC 是用户输出文件，仓库默认忽略 `*.lrc`。
- 不要把真实音乐、歌词、plist、数据库、处理历史、帐号信息、密钥或进程转储提交到仓库。

更多说明见 [SECURITY.md](SECURITY.md)、[CONTRIBUTING.md](CONTRIBUTING.md) 和[免责声明](DISCLAIMER.md)。

## 常见问题

**为什么 Mac 能播放，硬件播放器却显示异常时长？**

先确认内容与后缀、声明时长与实际解码时长是否一致。MP4 内封装的 FLAC 不能只改后缀当作原生 FLAC；这属于封装整理问题。默认 CLI 会检查文件，但不能替代实机验证。

**为什么没有封面或歌词？**

可能是曲库没有资源、网络请求失败、已有文件无法识别，或找不到同名原始下载文件。查看逐文件状态；CLI 不用模糊搜索强行替换版本。封面缺失允许跳过；请求歌词但无法完成时会报告未全部完成。

**歌词为什么在播放器上不同步？**

检查是否同目录同名、编码是否可读，以及歌曲是否为同一个现场 / 录音室 / 剪辑版本。播放器上应重新扫描并打开对应文件；实验性内嵌同步歌词不代表所有播放器都支持。

**macOS 提示无法验证开发者、Windows 提示未知发布者？**

现有发布流程默认使用 macOS ad-hoc 签名，Windows 安装包可能未签名。核对安装包来源；正式分发可配置 Developer ID 公证及 Authenticode 签名，详见发布文档。

## 许可与致谢

项目代码采用 [MIT License](LICENSE)。Mutagen、FFmpeg、LAME 等依赖遵循各自许可证；随包 FFmpeg / LAME 的许可与源码说明见 [FFmpeg 许可说明](desktop/src-tauri/resources/ffmpeg/LICENSES.md) 和 [源码说明](desktop/src-tauri/resources/ffmpeg/SOURCE.md)。

感谢上游 [mary20050520/qmunlock](https://github.com/mary20050520/qmunlock) 及相关开源项目。解密流程与技术资料见 [docs/DECRYPTION.md](docs/DECRYPTION.md)，历史变更见 [CHANGELOG.md](CHANGELOG.md)。
