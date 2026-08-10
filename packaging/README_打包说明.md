# 打包说明（给自己看的，不随包分发）

## 怎么打包

```powershell
.\packaging\build.ps1
```

或者手动：

```powershell
.venv\Scripts\Activate.ps1
pyinstaller packaging\temu_delisting_gui.spec --distpath dist --workpath build --noconfirm
```

产物在 `dist\TemuDelisting\` 下，大约 **226MB**（PySide6 + Playwright 自带的
node.exe driver 占了大头）。把整个 `TemuDelisting` 文件夹压缩成 zip 发给
同事，不能只发 `TemuDelisting.exe` 单个文件——onedir 模式下所有依赖文件都
在同一层目录，缺了就跑不起来。

## 目标机器的前提条件

- **必须已安装 Google Chrome**（`browser.py` 用 `channel="chrome"` 直接调
  系统里装好的正式版 Chrome，不会去装/带 Playwright 自己的 Chromium）。
  如果没装，程序启动去真实操作时会报"未检测到 Chrome 浏览器"（见
  `temu_delisting_gui/errors.py`），需要同事自己先装好 Chrome。
- 不需要装 Python、不需要装 Playwright、不需要碰命令行——双击
  `TemuDelisting.exe` 直接跑。
- 首次运行会在 exe 同一层目录下自动创建 `data\` 文件夹（账号、登录态、
  数据库、日志都在里面），删掉这个文件夹等于清空所有账号数据，谨慎删。

## 已知的技术点（改代码之后重新打包要留意）

- **`get_app_root()`（`src/temu_delisting/paths.py`）**：源码运行时是仓库根
  目录，打包后是 exe 所在目录——`config.py`/`accounts.py` 找配置文件、
  数据目录都依赖这个函数。如果以后要改数据/配置的存放逻辑，这个函数是
  必经之路，改的时候两种运行模式都要测一遍。
- **`contents_directory="."`（spec 文件里 `EXE(...)` 的参数）**：PyInstaller
  6.0 起默认会把依赖文件收进一层 `_internal` 子目录，这里特意关掉了，让
  `data`/`config` 这些跟 exe 保持在同一层，跟源码运行时的目录结构一致，
  不然 `get_app_root()` 算出来的路径会对不上。
- **Playwright 的 driver 是自动打包的**，靠它自己注册的官方 PyInstaller
  hook（`playwright._impl.__pyinstaller`），spec 文件里不用手动写
  `collect_data_files`。
- **不需要打包 Chromium 浏览器本体**——因为用的是 `channel="chrome"`，
  所以`playwright install`下载的那份完整 Chromium 用不上，只需要
  driver（含它自带的 node.exe，跟系统有没有装 Node.js 无关）。

## 打包后验证过什么

- 双击 exe 能正常弹出窗口（全新环境，`data\` 文件夹自动创建，账号下拉框
  显示"尚未添加账号"，符合首次运行的预期状态）
- 日志文件正确写入 `data\accounts\default\logs\`，且开头的启动横幅正确
  显示"运行方式: 打包后的 exe"（区别于源码运行时的"源码 (python -m)"）
- config/violation_types.yaml、Playwright driver（node.exe）、GUI 的
  style.qss 资源文件都确认打包进去了

## 还没测过、后续要注意的

- 打包版本里还没实测过真实的"添加账号 → 扫描 → 下架"完整流程（源码版本
  已经充分验证过，理论上行为一致，但 Playwright 从打包后的 exe 里拉起
  浏览器这个环节没有百分百实测确认，如果同事那边反馈"扫描没反应/浏览器
  不弹出"，优先怀疑这里，可以按 README 里"运行方式"日志先确认是不是真的
  在打包版里跑）
- 还没在第二台"干净"电脑（没装过 Python/这个项目源码）上验证过，只在本机
  用一个空的 data 目录模拟了"全新环境"
