# DSH 控制台.exe · 版本信息与签名（构建交接单）

> 状态：**尚未执行**。本文件是把「下一步怎么做」写成可执行清单，供新会话/新分支直接照做。

## 已核实的构建事实（2026-11-02 实测）

| 事实 | 证据 |
|---|---|
| 产物是 PyInstaller onefile（非 Nuitka/非打包器套壳） | 二进制内命中 `PyInstaller`@0x346CF、`MEIPASS`@0x34FCF、`python311`@0x1F37672 |
| PE 类型 | `machine=0x8664`（x64）、`subsystem=2`（GUI）、7 个段、`.rsrc` 71,912 B |
| 未启用 UPX | `UPX!` 标记未命中；`upx` 不在 PATH（当时 spec 里 `upx=True` 实际未生效；v2 批次 A 已显式改成 `upx=False`） |
| 版本信息为空的原因 | `DSHConsole.spec` 的 `EXE(...)` 缺 `version=` 参数，`.rsrc` 只有图标 + manifest |
| 源码与素材齐全 | `dsh_gui.py` 23,536 B、`DeepSeekChan [256x256].ico` 70,384 B、`DSHConsole.spec` 781 B（v2 批次 A 起 spec 还带 `dshconsole/data/*.ps1`） |
| PyInstaller 模块缺失 | `Python311\Scripts\pyinstaller.exe` 是残留 shim，报 `ModuleNotFoundError: No module named 'PyInstaller'` |
| Python 环境 | `C:\Users\Ibash\AppData\Local\Programs\Python\Python311\python.exe` → 3.11.9 |
| 无 signtool | `C:\Program Files (x86)\Windows Kits` 只有 8.1 + NETFXSDK，未找到 10 的 signtool.exe |
| 可用签名通道 | `Set-AuthenticodeSignature` 存在，可直接签 PE，**不必装 Windows SDK** |
| 当前证书 | `Cert:\CurrentUser\My` 下无任何代码签名证书 |

## 第一步：加版本信息（必须重建，不能事后改 .rsrc）

事后用资源编辑器改 `.rsrc` 会移动其后所有偏移，而 onefile 的尾部 cookie 记录着归档位置 —— 极可能打出「能打开、运行即崩」的 exe。

```powershell
$py311 = 'C:\Users\Ibash\AppData\Local\Programs\Python\Python311'
& "$py311\python.exe" -m pip install "pyinstaller>=6,<7"
```

新建 `version_info.txt`（与 spec 同目录）：

```python
VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1,0,0,0), prodvers=(1,0,0,0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
  kids=[
    StringFileInfo([StringTable('080404B0', [
      StringStruct('CompanyName',      'Ibash'),
      StringStruct('FileDescription',  'DeepSeek Harness 控制台'),
      StringStruct('FileVersion',      '1.0.0.0'),
      StringStruct('InternalName',     'DSHConsole'),
      StringStruct('OriginalFilename', 'DSH 控制台.exe'),
      StringStruct('ProductName',      'DeepSeek Harness Console'),
      StringStruct('ProductVersion',   '1.0.0.0')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
```

`name='DSH 控制台'` 与 `upx=False` 已由 v2 批次 A 写进 spec，本步只剩一处新增：

```python
    version='version_info.txt',  # 新增
```

### 打包必须带上的资源

spec 的 `datas` 已经列出运行期要用的三个文件，缺一个产物就会「按钮点了没反应」：

```python
    datas=[
        ('DeepSeekChan [256x256].ico', '.'),
        ('dshconsole/data/launch-dsh.ps1', 'dshconsole/data'),
        ('dshconsole/data/switch-dsh-web.ps1', 'dshconsole/data'),
    ],
```

运行时由 `dshconsole/resources.py` 定位：源码运行取包目录，`sys.frozen` 时取 `sys._MEIPASS`，
两条路径都按 `<root>/dshconsole/data` → `<root>/data` 依次尝试。

构建并验收：

```powershell
pyinstaller --clean --noconfirm DSHConsole.spec
(Get-Item 'dist\DSH 控制台.exe').VersionInfo |
  Format-List FileVersion, ProductVersion, CompanyName, FileDescription, OriginalFilename
```

五项都非空即成功；仍为空说明 spec 没被 pyinstaller 读取（确认在 spec 所在目录执行）。

## 第二步：签名（三选一）

| 方案 | 成本 | 本机 | 他人机器 |
|---|---|---|---|
| D 不签，只加版本信息 | 0 | 版本/公司名可见，未知发布者 | 同左 |
| A 自签证书 | 0 | 导入受信任根 + 受信任发布者后显示「已验证的发布者」 | 仍未知发布者；自签证书谁都能重签，防篡改价值为 0 |
| C Azure Trusted Signing | 约 $9.99/月 | 有效 | 有效；需过身份/经营验证（个人要 3 年可查记录） |
| B OV/EV 证书 | OV ¥1300–3000/年 | 有效 | 有效；2023 年后私钥须放硬件 token/云 HSM |

**推荐：D（自用）+ 记录 SHA256 作为构建指纹。** 需要本机观感再加 A。

方案 A 的命令（timestamp 需联网，失败则去掉该参数）：

```powershell
$c = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=Ibash" `
       -KeyUsage DigitalSignature -CertStoreLocation Cert:\CurrentUser\My
Set-AuthenticodeSignature -FilePath 'dist\DSH 控制台.exe' -Certificate $c `
       -TimestampServer http://timestamp.digicert.com -HashAlgorithm SHA256
Get-AuthenticodeSignature 'dist\DSH 控制台.exe' | Format-List Status, SignerCertificate
```

## 第三步：上传 GitHub 前必须先做的事

当前 `C:\Users\Ibash\Documents\Codex\apps\deepseek-harness` **不是 git 仓库**（`fatal: not a git repository`），`gh` 未安装。

必须排除的项（实测存在于该目录）：

- `dsh-web.url.txt` —— **含带 launch token 的登录地址，绝不可提交**
- `dsh-web.stderr.log`（1.3 MB）及十余个 `*.log`、`*.server.out.log`
- `.npmrc`（160 B）
- `node_modules/`、`dist/`、`build/`、`__pycache__/`、`.idea/`
- `.tmp-ccdesk/`、`.tmp-sandbox/`、`.upgrade-backup/`、`.dsh-inspect/`、`.dsh-recovery/`
- `DSH 控制台.exe`（33 MB 二进制，建议作为 Release 附件而非仓库内容）
- 5 张 921 KB 的调试截图（`_d0_before_rename.png` 等）、`_ab_logo.png`、`_desktop_probe.png`
- `*.bak`：`launch-dsh.ps1.bak`、`启动DeepSeekHarness.ps1.bak`
- 与本工具无关的子项目：`_ref_bb/`、`bb-bulk-course-downloader/`、`quadratic-formula-demo/`、`PC-防护/`、`bamboo-cicada/`、`ppt-generator/`（含本地配置与构建产物）

建议做法：新建独立目录 `apps\dsh-console\` 作为仓库根，只放 `dsh_gui.py`、`DSHConsole.spec`、`version_info.txt`、`DeepSeekChan [256x256].ico`、`build.ps1`、`README.md`、`.gitignore`。
