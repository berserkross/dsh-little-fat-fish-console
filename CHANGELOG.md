# 变更记录

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-11-03

首个公开快照：把本机自用的控制台原样开源，作为后续迭代的基线。

### 新增

- 启动 / 停止 DeepSeek Harness
- 开启手机访问（回环 + portforward + 信任来源）与「恢复本机」
- 复制手机地址、窗口内生成二维码（不落盘）
- 实时查看服务状态与日志

### 已知问题

- `dsh_gui.py:22` 的 `HARNESS` 路径硬编码，换机器即失效
- 产物缺 FileVersion / ProductName（spec 缺 `version=`），且未签名
- 端口 3080 与 token 日志路径同样硬编码
