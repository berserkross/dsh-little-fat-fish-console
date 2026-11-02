"""文本脱敏：写进日志框的内容先把 token 打码，剪贴板不受影响。"""
from __future__ import annotations

import re

# 前面不是字母数字下划线才算 token 参数（`mytoken=...` 不算），值到空白 / & / 引号为止。
_TOKEN_PARAM = re.compile(r"(?<![A-Za-z0-9_])(token=)([^\s&#\"'<>]+)", re.IGNORECASE)
MASK = "****"


def redact(text: str) -> str:
    """把 token=<值> 的令牌部分换成 ****；无 token 时原样返回（幂等）。

    只用于「给人看的地方」（日志框、诊断复制）。剪贴板要放完整地址，那是功能。
    """
    if not text:
        return text
    return _TOKEN_PARAM.sub(lambda m: m.group(1) + MASK, text)


def redact_urls(text: str) -> str:
    """同 redact()，语义化别名：处理的是整段文本里出现的所有地址。"""
    return redact(text)
