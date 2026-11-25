"""手机端控制台的授权部分：一次性动作码。

免 token 直连那个口（3081）上还能看一页状态，状态是只读的；要动服务就得先在这台电脑上
点一下「手机动作码」，把 6 位数字敲进手机页面。码 60 秒过期、用一次就作废、同时只有一枚 ——
它证明的不是「手机连得上」，而是「拿着手机的人此刻也坐在电脑前」。

只放行启动/重启/关闭/中断会话四件事：切换端口、UAC 开关、退出程序影响面更大，仍然只认电脑上的点击。
"""
from __future__ import annotations

import hmac
import secrets
import time

CODE_TTL = 60.0
CODE_DIGITS = 6
ACTIONS = {"start": "启动 DSH", "restart": "重启 DSH", "stop": "关闭 DSH",
           "interrupt": "中断所有会话"}


class ActionGate:
    """一枚一次性码：签发、倒计时、核销。"""

    def __init__(self, ttl: float = CODE_TTL, clock=time.time,
                 digits: int = CODE_DIGITS, rand=None):
        self._ttl = float(ttl)
        self._clock = clock
        self._digits = int(digits)
        # 注入随机源：测试要的是可预期的数字，不是真随机。
        self._rand = rand or (lambda span: secrets.randbelow(span))
        self._code: str | None = None
        self._expires = 0.0

    def mint(self) -> str:
        """签一枚新码 —— 旧码立刻作废：同一时刻只该有一个人在授权。"""
        span = 10 ** self._digits
        self._code = str(self._rand(span)).zfill(self._digits)
        self._expires = self._clock() + self._ttl
        return self._code

    def clear(self) -> None:
        self._code = None
        self._expires = 0.0

    def remaining(self) -> int:
        """还有几秒可用；没签过或已经过期就是 0（页面据此显示倒计时）。"""
        if self._code is None:
            return 0
        left = self._expires - self._clock()
        return max(0, int(left))

    def redeem(self, code: str, intent: str) -> tuple[bool, str]:
        """核销一次动作。只有「码对、没过期、动作在白名单」三条同时成立才作废它。

        输错码不消耗：否则旁边的人随手敲两下就能把这次授权作废掉。
        """
        if intent not in ACTIONS:
            return False, "不认识的动作"
        if self._code is None:
            return False, "电脑上还没有签动作码"
        if self._clock() >= self._expires:
            self.clear()
            return False, "动作码过期了：回电脑上再点一次「手机动作码」"
        if not hmac.compare_digest(str(code).strip(), self._code):
            return False, "动作码不对"
        self.clear()
        return True, ACTIONS[intent]
