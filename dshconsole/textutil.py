"""文本脱敏：写进日志框 / 诊断包的内容先打码，剪贴板不受影响。

两档语义：
  redact()       只处理 token=<值>，日志框与二维码动作沿用（原语义不改，幂等）；
  redact_text()  诊断包用：token、cookie、api key、bearer、sk- / gho_ 等凭据前缀一起打码，
                 并且**连前缀一起换成 ****** —— 校验方式是 grep 字面量零命中。
"""
from __future__ import annotations

import re

# 前面不是字母数字下划线才算 token 参数（`mytoken=...` 不算），值到空白 / & / 引号为止。
_TOKEN_PARAM = re.compile(r"(?<![A-Za-z0-9_])(token=)([^\s&#\"'<>]+)", re.IGNORECASE)
MASK = "****"

# ---- redact_text() 额外规则（顺序即优先级：先具体键名，后裸前缀） ----
# name=value / name: value 形态的凭据键；值可以带引号。
_SECRET_KEYS = re.compile(
    r"(?<![A-Za-z0-9_])((?:api[_-]?key|apikey|access[_-]?key|client[_-]?secret|secret|"
    r"password|passwd|pwd|cookie|set-cookie|session[_-]?id|auth[_-]?token))(\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s&;,\"'<>]+)",
    re.IGNORECASE,
)
# Authorization: Bearer <token>
_BEARER = re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._\-]{4,})")
# 裸的 url 内嵌凭据：https://user:pass@host
_URL_CRED = re.compile(r"(?<=://)([^\s/:@]+):([^\s/@]+)@")
# 凭据前缀：sk- 与 GitHub 令牌（gho_ / ghp_ / ghu_ / ghs_ / ghr_）连前缀一起打码。
# 前面不能紧贴字母数字与 - 号，否则 "task-123" 会被当成 sk- 令牌。
_SK = re.compile(r"(?<![A-Za-z0-9_\-])sk-[A-Za-z0-9_\-]{2,}")
_GH = re.compile(r"(?<![A-Za-z0-9_\-])gh[posur]_[A-Za-z0-9]{2,}")


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


def _mask_value(match: re.Match) -> str:
    head = match.group(1) + match.group(2)
    return head + MASK


def redact_text(text: str) -> str:
    """整段文本脱敏：token / cookie / api key / bearer / sk- / gh*_ 一律打码。

    比 redact() 宽：诊断包会被发到别处（issue、聊天），所以除了 token 参数，
    还能认出 `Cookie: ...`、`api_key=...`、`Bearer ...` 与裸的凭据前缀。
    幂等：打码后的 **** 不会再被任何规则命中。
    """
    if not text:
        return text
    out = _TOKEN_PARAM.sub(lambda m: m.group(1) + MASK, text)
    out = _SECRET_KEYS.sub(_mask_value, out)
    out = _BEARER.sub(lambda m: m.group(1) + MASK, out)
    out = _URL_CRED.sub(MASK + "@", out)
    out = _SK.sub(MASK, out)
    out = _GH.sub(MASK, out)
    return out
