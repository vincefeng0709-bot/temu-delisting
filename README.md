# temu-delisting

自动化 Temu 卖家中心「合规中心 → 违规处理」页面里符合条件的违规商品下架操作。

流程分两步、中间有人工审核闸门，不会全自动直接提交下架：

1. `scan`：抓取指定日期区间内的违规商品，按已知违规类型清单打标"建议下架/待人工判断"，导出一份清单供你审核确认。
2. `apply`：读取你审核确认过的清单，对每个 SPU 打开一次客服会话，依次对该 SPU 下所有 SKC 走"自助工具 → 商品下架"流程提交下架申请。

## 安装

```bash
pip install -e ".[dev]"
playwright install chrome
cp .env.example .env
```

## 首次登录（重要：不能在自动化浏览器里直接登录）

实测 Temu 卖家中心会拦截 Playwright 驱动的浏览器发起的登录请求（提示"账号异常，无法登录"），哪怕是人工手动输入账号密码、哪怕用的是真实 Chrome 内核也一样；换成无痕窗口都能登录，只有 Playwright 自动化的窗口不行——说明这是针对自动化特征的拦截，不是账号或环境问题。本工具**不会**去做绕过/伪装这类反自动化检测的事情，所以登录必须走下面这条路：

1. 在你**平时正常使用的 Chrome**（不是本工具弹出的那个窗口）里登录卖家中心：`https://seller.kuajingmaihuo.com`，一路点进去直到看到实际控制台首页（域名会变成 `agentseller.temu.com`）
2. 装一个 Cookie 导出扩展（推荐 [Cookie-Editor](https://cookie-editor.com/)，认准这个官方版本），**两个域名的 Cookie 都要导出**：
   - 在 `seller.kuajingmaihuo.com` 页面导出一次
   - 在 `agentseller.temu.com` 页面导出一次
3. 分别导入（是"合并导入"，不会互相覆盖）：
   ```bash
   temu-delisting import-cookies cookies1.json
   temu-delisting import-cookies cookies2.json
   ```
4. 之后 `scan` / `apply` / `explore` 会直接复用这个登录态，不会再尝试登录

登录态过期后（命令会报错提示），重复上面 1-3 步重新导入一次即可。**导出的 Cookie JSON 文件包含登录凭据，用完建议删掉，不要提交进 git**（`.gitignore` 已经排除了 `cookies*.json`，但别偷懒不删）。

## 使用

```bash
# 第一步：扫描指定日期区间的违规商品，生成待审核清单
temu-delisting scan --start "2026-08-06" --end "2026-08-07"

# 清单会输出到 data/exports/，跟着终端逐条确认要不要下架
# （对于"待人工判断"的未知违规类型，请谨慎确认，必要时把这个类型加进
#  config/violation_types.yaml 的 known_delist_types 列表）

# 第二步：执行已确认的下架清单
temu-delisting apply --batch <scan 命令输出的批次ID>

# 先用 --dry-run 走到"申请下架"前一步，不真正提交，用于验证流程走对了
temu-delisting apply --batch <批次ID> --dry-run

# 查看某个批次里失败/超时、需要人工跟进的 SKC
temu-delisting failures --batch <批次ID>
```

### 调试用命令/参数

- `temu-delisting explore`：登录后打开浏览器并暂停，方便手动点击核对页面结构/URL（联调新页面时用）
- `apply --pause-before-chat`：每次要打开客服对话前先暂停，方便盯着看每一步
- `apply --pause-on-error`：卡住等不到"自助工具"时不直接报错退出，而是冻结在卡住的现场，方便当场检查 DOM

## 已知的几个坑（联调时踩过的）

- **客服图标是个开关**：面板已经打开时再点一次会把它关掉。同一个 SPU 下处理多个 SKC 时，客服会话只应该在处理第一个 SKC 前打开一次（见 `chat.open_chat_session`），后续 SKC 直接复用这个已打开的面板（`chat.trigger_delist_flow`），千万不要每个 SKC 都重新点客服图标。
- **有些按钮文字中间会插空格**（比如"确 定"渲染成"确 定"），精确文字匹配会失效，统一用 `text_match.loose_text()` 做"忽略空格"的匹配。
- **重复申请同一个 SKC** 会弹"该商品已在您的上次咨询后处理成功"的提示弹窗，不是正常的聊天气泡回复。这个弹窗是**跟账号绑定在服务端**的，不是跟浏览器窗口绑定——哪怕重开一个全新的 Playwright 浏览器，只要连上客服还是会看到上次没处理完、没关掉的这个弹窗，挡住后续所有点击。所以每次开始处理一个新 SKC 之前都要先检查一下有没有这种残留弹窗（`chat.dismiss_already_processed_alert`）。
- **日期选择器**是自定义的日历组件（不是普通 input，只读，不能直接打字），要通过点日历格子 + 翻页按钮选日期，选择器细节见 `scraper.py` 顶部注释。

## 数据与日志

- `data/app.db`：SQLite，记录每个 SKC ID 的处理状态（幂等去重用，重复跑不会重复提交）
- `data/exports/`：每次 `scan` 生成的建议清单 CSV
- `data/logs/`：每次运行的日志文件（带时间戳），终端打印的内容会同步写一份进去，方便事后审计"跑没跑、跑了哪些、出过什么错"
- 失败/超时的 SKC 记录在 SQLite 里，用 `temu-delisting failures --batch <批次ID>` 查看

## 安全说明

- 账号密码不需要填进 `.env`（登录走 Cookie 导入，不走账号密码）
- 不做验证码/滑块绕过，也不做反自动化检测绕过；登录必须在正常浏览器里人工完成，再导入 Cookie 复用
- 下架属于不可逆操作，`scan` 只生成建议清单，实际提交前必须经过人工确认（`review_status=confirmed` 才会被 `apply` 处理）
- 单个 SPU 处理出错不会拖垮整批，会记录下来跳到下一个继续，最后统一汇报哪些失败了
- 建议保持小批次运行，留意账号是否出现异常提示；本工具不会主动重试被拦截/被节流的请求
