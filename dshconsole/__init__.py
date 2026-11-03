"""小肥鱼控制台的可移植性支持包：资源定位（resources）与配置探测（config）。

导入本包不会拉起 tkinter，可在无 GUI 的环境（CI、单元测试）里直接使用。
"""
from . import resources
from .config import DshConfig, config_path, load, save

# 版本号源头是 version_info.txt（PyInstaller 的 PE 版本资源）；改版本时两处一起改，
# diagnostics 的 meta.json 从这里取值。
__version__ = "2.2.3"

__all__ = ["DshConfig", "config_path", "load", "save", "resources", "__version__"]
