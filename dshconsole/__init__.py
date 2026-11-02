"""DSH 控制台的可移植性支持包：资源定位（resources）与配置探测（config）。

导入本包不会拉起 tkinter，可在无 GUI 的环境（CI、单元测试）里直接使用。
"""
from . import resources
from .config import DshConfig, config_path, load, save

__all__ = ["DshConfig", "config_path", "load", "save", "resources"]
