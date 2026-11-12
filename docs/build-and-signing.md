# 小肥鱼控制台 · 构建、版本信息与签名

> 状态：**已实测**（2026-11-03，批次 E）。本文件里的命令都在本机真跑过，产物数值是实测值，
> 不是"计划中的命令"。签名一节的两条路径都是命令与验证方法，未持有真实 CA 证书，因此真实证书路径没有真签过。
>
> **只想在自己机器上签名**（个人名义、自签名、免费）：看 [self-signed-local.md](self-signed-local.md) +
> `scripts/sign-self-signed.ps1`。那是本机完整性检查，不是发布级凭证。

## 一、实测产物

| 项 | 实测值 |
|---|---|
| 产物路径 | `C:\Users\Ibash\Documents\Codex\apps\dsh-console\dist\DSHConsole.exe` |
| 大小 | 未签名 32,172,230 B；自签名后 32,179,368 B（签名块约 +7 KB，每次签名略有浮动） |
| SHA256 | 自签名后 `930956ABF15D410BBF0FA01C125CD0B6B00247FE8CF4570D91A0C5B7E5DB38CB`（同一份源码未签名时为 `3C3B70B7C270C7FA74CE225E53E8E798B011DD4EB366750029C2B86599783C9C`） |
| 形态 | PyInstaller **onefile**（`dist\` 下只有这一个 exe，无 `_internal\` 目录；引导器 `runw.exe`） |
| 界面子系统 | PE `subsystem=2`（GUI，双击不弹控制台窗） |
| 结构 | `machine=0x8664`（x64）、7 个段、`.rsrc` 72,896 B |
| 压缩 | `upx=False`，二进制内 `UPX!` 命中 0 次 |
| manifest | `requestedExecutionLevel level="asInvoker"`（命中 1 次），`requireAdministrator` 命中 0 次 → **启动不请求管理员权限，无 UAC 提示** |
| 构建机 Python | 3.11.9（`MSC v.1938 64 bit`），命令用 `py -3.11` |
| PyInstaller | 6.22.3 |
| 构建耗时 | 20.7 秒（干净重建，`build/`+`dist/` 全删后） |
| 版本资源 | `FileVersion 2.1.0.0` / `ProductVersion 2.1.0.0` / `CompanyName berserkross` |
| 签名 | v2.2.5 起 Release 附带自签名 exe（证书仅本机信任，见 [self-signed-local.md](self-signed-local.md)）；签名命令为 `scripts/sign-self-signed.ps1`，真实 CA 证书路径见第五节。 |

`.rsrc` 从加版本资源之前的 71,912 B 长到 72,896 B（+984 B），与"版本资源确实写进去了"一致。

构建时的唯一告警是 PyInstaller 的
`DEPRECATION: Running PyInstaller as admin is not necessary nor sensible` —— 这是**构建终端被提升**导致的，
与产物无关：exe 的 manifest 是 `asInvoker`，不带任何管理员要求。想让这行消失就用普通权限的终端构建。

## 二、构建（实测命令）

```powershell
cd C:\Users\Ibash\Documents\Codex\apps\dsh-console
py -3.11 -m PyInstaller --noconfirm DSHConsole.spec
```

首次（干净）构建 20.7 秒；源码一个字都没改时再跑一遍只要 0.64 秒（`build/` 里的 Analysis / PYZ / EXE
缓存全部被复用，输出里是 `checking Analysis` / `checking EXE` 而不是 `Building …`）。
要保证干净重建就先删 `build/`、`dist/`，或加 `--clean`。

### 构建前先清掉 `TCL_LIBRARY` / `TK_LIBRARY`（踩过，务必看）

从跑过 onefile exe 的同一个终端里构建时，这两个变量可能还指着 `%TEMP%\_MEIxxxx\_tcl_data`
—— 那个临时目录早就被删了。PyInstaller 的自检导入会因此判定 tkinter 不可用并**静默排除**它：
产物从 32 MB 掉到 29 MB，双击立刻弹 `Unhandled exception in script`
（`ModuleNotFoundError: No module named 'tkinter'`），构建日志里一行错误都没有。

```powershell
Remove-Item Env:TCL_LIBRARY, Env:TK_LIBRARY -ErrorAction SilentlyContinue
```

判据：构建后 `build\DSHConsole\Analysis-00.toc` 里 `_tkinter` 出现 4 次；少了就是被排除了。

预期输出末尾出现这两行，缺一不可：

```text
... INFO: Copying icon to EXE
... INFO: Copying version information to EXE      <- 缺这行说明 spec 的 version= 没生效
... INFO: Build complete! The results are available in: ...\dsh-console\dist
```

为什么必须重建、不能事后用资源编辑器改 `.rsrc`：那会移动其后所有偏移，而 onefile 尾部的 archive
cookie 记录着归档位置，改完极可能得到"能打开、运行即崩"的 exe。

## 三、版本信息的唯一源头

版本号只写在 `version_info.txt`（PyInstaller 的 `VSVersionInfo` 文本表示，构建时被 `eval()` 加载），
由 spec 的一句 `version='version_info.txt'` 引入：

```python
exe = EXE(
    ...
    name='DSHConsole',
    console=False,
    upx=False,
    icon=['DeepSeekChan [256x256].ico'],
    version='version_info.txt',
)
```

改版本号要同步三处：

1. `version_info.txt` 的 `filevers` / `prodvers` / `FileVersion` / `ProductVersion`；
2. `dshconsole/__init__.py` 的 `__version__`（诊断包 `meta.json` 的 `version` 字段读它）；
3. `CHANGELOG.md` 顶部新段落。

`version_info.txt` 用 UTF-8 编码（PyInstaller 读文件时按 BOM/encoding cookie 解码，文件里有
`# -*- coding: utf-8 -*-`），字符串表用 `080404B0`（zh-CN + 码页 1200），所以中文产品名不会乱码 —— 实测
`FileDescription` 读出来是 `小肥鱼控制台`，`Language` 是 `简体中文(中国大陆)`。

产物名用 ASCII 的 `DSHConsole.exe` 而不是中文名：命令行、CI 与签名脚本引用时不用带引号、不用处理
代码页；中文产品名由 `ProductName` / `FileDescription` 与窗口标题体现（资源管理器"详细信息"里看得到）。

## 四、冒烟验收（实测输出）

版本资源五项：

```powershell
(Get-Item dist\DSHConsole.exe).VersionInfo |
  Format-List FileVersion, ProductVersion, CompanyName, FileDescription, LegalCopyright
```

```text
FileVersion     : 2.0.0.0
ProductVersion  : 2.0.0.0
CompanyName     : berserkross
FileDescription : 小肥鱼控制台
LegalCopyright  : MIT License · Copyright (c) 2026 YANG TIANRUI
```

冻结态自检（exe 是 GUI 子系统，控制台里看不到它 print 的东西，所以要用 `Start-Process -Wait`
拿退出码，自检结论另外写进 `%TEMP%` 的标记文件）：

```powershell
$p = Start-Process -FilePath dist\DSHConsole.exe -ArgumentList '--selftest' -Wait -PassThru
$p.ExitCode; Get-Content "$env:TEMP\dsh-gui-selftest.txt"
$p = Start-Process -FilePath dist\DSHConsole.exe -ArgumentList '--stop-selftest' -Wait -PassThru
$p.ExitCode; Get-Content "$env:TEMP\dsh-stop-selftest.txt"
```

实测：

```text
SELFTEST_EXIT=0
OK 2026-11-03 03:00:57 qr=True clear=True adopt_shown=True adopt_hidden=True log_lines=2000 trim=True addresses=True

STOPSELFTEST_EXIT=0
OK
fake_pid=36448
detected=([], None)
fake_alive_after_click=False
log_has_stopped=True
queue_idle=True pending=[]
```

`--stop-selftest` 的日志片段里出现 `托盘已就绪` 与 `正在跟随日志：dsh-web.stdout.log`，
说明冻结态下 pystray（`pystray._win32`）、customtkinter、PIL、qrcode 与日志跟随全部能起来；
两条自检都不碰本机真实的 DSH 进程与 3080 端口（探测口全部注入）。

资源在冻结态的位置（`dshconsole/resources.py`）：`sys.frozen` 为真时根目录是 `sys._MEIPASS`，
脚本在 `<_MEIPASS>\dshconsole\data\*.ps1`，图标在 `<_MEIPASS>\DeepSeekChan [256x256].ico` ——
与 spec 的 `datas` 目标目录一一对应，归档里已实测列出这两条：

```text
9813886, 1816, 4078, 1, 'b', 'dshconsole\\data\\launch-dsh.ps1'
9815702, 3839, 9737, 1, 'b', 'dshconsole\\data\\switch-dsh-web.ps1'
66352, 70402, 70384, 1, 'b', 'DeepSeekChan [256x256].ico'
```

清单用 `py -3.11 -m PyInstaller.utils.cliutils.archive_viewer dist\DSHConsole.exe -l` 取。

## 五、签名

### 本机现状：没有证书，也没有 signtool

```powershell
Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert
```

```text
（无任何输出；同一存储里另有 8 张非代码签名证书，例如自签的开发证书）
```

`C:\Program Files (x86)\Windows Kits` 下只有 8.1 SDK 与 NETFXSDK，**没有 10 的 `signtool.exe`**。
可用的签名通道是 PowerShell 自带的 `Set-AuthenticodeSignature`，它直接给 PE 写 Authenticode 签名，
不必装 Windows SDK。

### 路径 (a)：有 Authenticode 证书（OV / EV / Azure Trusted Signing）

```powershell
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object { $_.Subject -like '*你的公司名*' } | Select-Object -First 1
Set-AuthenticodeSignature -FilePath dist\DSHConsole.exe -Certificate $cert `
    -TimestampServer http://timestamp.digicert.com -HashAlgorithm SHA256
```

时间戳服务器要联网；离线环境去掉 `-TimestampServer`，但那样签名会随证书过期一起失效（有了时间戳，
已签的二进制在证书过期后仍然有效）。`-HashAlgorithm SHA256` 是现在的默认值，写出来是为了防止在旧机器
上落到 SHA1。

验证：

```powershell
Get-AuthenticodeSignature dist\DSHConsole.exe | Format-List Status, StatusMessage, SignerCertificate
```

预期形态：

- 签名成功且证书链可信：`Status : Valid`，`StatusMessage : Signature verified.`，`SignerCertificate`
  显示证书主题与颁发者；
- 证书不在受信任根里（自签）：`Status : UnknownError` 或 `NotTrusted`，`StatusMessage` 类似
  `A certificate chain processed, but terminated in a root certificate which is not trusted by the trust provider`；
- 没签：`Status : NotSigned`。

签名之后 `SHA256` 必然改变 —— 签名要往产物里追加 Authenticode 段，所以**先签再算哈希**，别反过来。

### 路径 (b)：自签名证书，只供本机测试

```powershell
$c = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=Ibash (test only)" `
       -KeyUsage DigitalSignature -CertStoreLocation Cert:\CurrentUser\My `
       -NotAfter (Get-Date).AddYears(1)
Set-AuthenticodeSignature -FilePath dist\DSHConsole.exe -Certificate $c `
       -TimestampServer http://timestamp.digicert.com -HashAlgorithm SHA256
# 让本机把它当可信根（只对这台机器、这个用户生效）
$c | Export-Certificate -FilePath "$env:TEMP\dsh-test.cer" | Out-Null
Import-Certificate -FilePath "$env:TEMP\dsh-test.cer" -CertStoreLocation Cert:\CurrentUser\Root
```

自签名的边界，必须写清楚：

- **不能消除 SmartScreen 警告。**SmartScreen 看的是证书的"信誉"，自签证书没有第三方背书，别人机器上照样
  弹"未知发布者"，本机也只是因为手工把它导进了受信任根才显示"已验证的发布者"。
- 防篡改价值为 0：私钥就在你自己的证书存储里，谁都能重签一个内容不同的 exe。
- 别人机器上 `Get-AuthenticodeSignature` 会返回 `UnknownError`（根不受信任），而不是 `Valid`。

所以自签名只用来验证"签名管线是否通"，发布仍应选 (a)，或者接受"未签名 + 公布 SHA256"。

### 自签名与 SmartScreen 的现实

v2.2.5 起 Release 直接附带用自签名证书签名的 exe，但证书根只在本机受信任，别人机器上
`Get-AuthenticodeSignature` 会返回 `UnknownError`，SmartScreen 仍会弹「Windows 已保护你的电脑」/「未知发布者」，
需要点「更多信息 → 仍要运行」。这是自签名 exe 的预期行为，不是构建失败。可用的补充手段是把
SHA256 写进 Release 说明，让对方自己校验：

```powershell
Get-FileHash dist\DSHConsole.exe -Algorithm SHA256
```

## 六、还没有验证的

- **干净机器上是否需要 VC++ 运行库**：本机装了 VS 运行库，测不出来。Python 3.11 官方安装包自带的
  `vcruntime140.dll` 会被 PyInstaller 打进 onefile，理论上不需要另装；但没有在全新系统上验过。
- **未签名包在他人机器上的 SmartScreen 表现**：只有本机口径（点开即要求"仍要运行"），没有真实样本。
- **签名流程本身**：没有证书，第五节的命令全部未执行过；命令写法依据 `Set-AuthenticodeSignature` /
  `New-SelfSignedCertificate` 的文档，不是实测输出。
- **杀毒软件误报**：PyInstaller onefile 产物常被启发式引擎误判，本机未做多引擎扫描。
