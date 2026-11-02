# 小肥鱼控制台 · DSH Console

DeepSeek Harness 的桌面图形界面（customtkinter · 蓝鲸主题）。双击 exe 或运行脚本即可打开窗口，
用来在本机启动 / 停止 DSH Web 服务、把服务临时开给手机访问、以及随时看状态。

> v1 存档版：这是**第一版源码的忠实快照**，上传目的是建立可迭代的基线。
> 已知的硬编码与待办都列在「v1 已知问题」里，进入 v2 时逐项处理。

## 功能

- ▶ 启动 DeepSeek Harness
- ⏹ 停止 DeepSeek Harness
- 开启手机访问（回环 + 端口转发 + 信任来源）
- 恢复本机（仅回环）
- 复制手机地址
- 生成二维码（窗口内显示，刷新 / 关闭即清除，**不落盘**）
- 实时查看服务状态与日志

## 环境要求

| 项 | 版本 |
|---|---|
| Windows | 10 / 11 |
| Python | 3.11（开发与打包环境实测 3.11.9） |
| 运行依赖 | `customtkinter`、`pillow` |
| 打包 | `pyinstaller >= 6, < 7` |

## 运行

```powershell
python -m pip install customtkinter pillow
python .\dsh_gui.py
```

## 打包

```powershell
python -m pip install "pyinstaller>=6,<7"
pyinstaller --clean --noconfirm DSHConsole.spec
```

产物在 `dist\` 下。架构细节见 `docs\build-and-signing.md`。

## 目录结构

```
dsh_gui.py                       主程序（GUI + 状态机 + 二维码）
DSHConsole.spec                  PyInstaller 打包描述
DeepSeekChan [256x256].ico       窗口与 exe 图标
reference/launch-dsh.ps1         本程序调用的 harness 启动器（对照用）
reference/switch-dsh-web.ps1     本程序调用的手机访问切换器（对照用）
docs/build-and-signing.md        构建、加版本信息、签名交接单
```

## v1 已知问题（进 v2 要解决）

1. `dsh_gui.py:22` 把 `HARNESS` 硬编码为 `C:\Users\Ibash\Documents\Codex\apps\deepseek-harness`，换机器即失效。
2. `DSHConsole.spec` 的 `EXE()` 缺 `version=` 参数 → 产物没有 FileVersion / ProductName / CompanyName。
3. 产物未签名，SmartScreen 显示「未知发布者」。
4. spec 里 `name='DSHConsole'` 与实物文件名 `DSH 控制台.exe` 不一致。
5. 端口 3080、会话令牌日志路径 `dsh-web.stdout.log` 同样被硬编码。

## 安全提示

本程序会读取 DSH 启动日志以提取带 token 的访问地址。**该日志与地址绝不可提交进仓库**（见 `.gitignore`）。

## 商标

图标与配色取自 DeepSeek 品牌视觉，仅作本机自用；对外分发请自行替换并遵守相应商标政策。
