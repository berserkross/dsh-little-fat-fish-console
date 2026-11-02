# 安全策略

## 支持范围

| 版本 | 接收安全报告 |
|---|---|
| v1.x | ✅ |

## 怎么上报

1. 优先走 GitHub 私密上报：仓库页 → **Security** → **Report a vulnerability**。
2. 用不了时，开一个标题以 `[SECURITY]` 开头的 issue，**只描述问题、不带敏感数据**，维护者会另找私密渠道跟进。

请**不要**在公开 issue / PR / 讨论里贴：访问 token、`dsh-web.url.txt` 内容、`dsh-web.stdout.log` 片段、内网 IP、手机访问二维码截图。

## 本程序的预期行为（不算漏洞）

- 修改 `netsh interface portproxy` 规则，把 3080 临时开给局域网 / 手机。
- 通过 PowerShell 启动、停止 DSH 进程。
- 读取 `dsh-web.stdout.log` 提取带 token 的访问地址 —— 仅在内存中用于「复制地址」与二维码，**不落盘**。
- 除上述之外如果发现它在收集或上传数据，那就是漏洞，请上报。

## 响应

个人项目，尽力在 7 天内回复。
