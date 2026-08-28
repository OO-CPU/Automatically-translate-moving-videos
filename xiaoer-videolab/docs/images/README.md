# 截图清单 / Screenshot checklist

把截图按下面的**文件名**存进这个 `docs/images/` 目录，README 里对应位置的占位注释
（`<!-- 截图位: docs/images/xx.png -->`）就会被替换成真图。

> 这些几乎全是「持久界面」，已经装好的人也能随时补拍，不用重装。

| 文件名 | 拍什么 | 怎么拍 |
|---|---|---|
| `01-terminal.png` | 「终端」App 窗口 | ⌘空格 搜 Terminal 打开，截个干净窗口（可选，不重要） |
| `02-install-success.png` | `install.sh` 跑完的成功输出 | 终端里能看到 `✓ Daemon running...` 那几行；没保留的话重跑一次 `./scripts/install.sh` 即可 |
| `03-developer-mode.png` | `chrome://extensions/` 右上角「开发者模式」开关已打开 | 打开扩展页，截右上角开关 |
| `04-load-unpacked.png` | 左上角「加载已解压的扩展程序」按钮（最好连弹出的选文件夹框） | 同上页面，点一下按钮时截 |
| `05-extension-card.png` | 扩展列表里 **Xiaoer VideoLab** 那张卡片 | 直接截你现在的扩展页 |
| `06-pin-toolbar.png` | 工具栏拼图菜单里把 VideoLab 图钉点亮 / 图标已 pin 在工具栏 | 点工具栏拼图图标时截 |
| `07-click-button.png` | 在某个视频页（如 YouTube）点 VideoLab 图标的样子 | 打开视频页，鼠标指着工具栏图标截 |
| `08-notification.png` | 右上角「开始下载 / ✅ 文件名」系统通知 | 下载时通知弹出来的那一下截（或下完那条 ✅） |
| `09-downloads-folder.png` | `~/Downloads` 里下好的视频文件 | 打开下载文件夹，截到那个视频文件 |

## 给 Claude 的话

Jane 把图丢进这个目录后，Claude 把两个 README 里对应的 `<!-- 截图位: ... -->`
注释替换成 `![说明](docs/images/xx.png)`，commit 推送即可。最重要的 3 张：
**05（扩展卡片）、04（加载已解压）、08（通知）** —— 有这三张，小白基本不会卡。
