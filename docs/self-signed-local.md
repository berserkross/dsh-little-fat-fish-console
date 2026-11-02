# 本机自签名（YANG TIANRUI）

这个项目**不发布签名过的二进制**。产物由你自己构建；如果你想让自己的那份 exe 在属性页里
显示签名者、并让本机把签名判为有效，用本机的自签名证书签一下：

```powershell
py -3.11 -m PyInstaller --noconfirm DSHConsole.spec
powershell -ExecutionPolicy Bypass -File .\scripts\sign-self-signed.ps1 -TrustLocal
```

脚本做四件事：没有证书就生成一张（主体 `CN=YANG TIANRUI`，代码签名 EKU，私钥 NonExportable，
有效期 3 年）→ 导出公开证书到 `certs/dsh-console-selfsigned.cer` → `-TrustLocal` 时把它加进
`CurrentUser\Root`（仅当前用户）→ 用 SHA256 + DigiCert 时间戳签名并验证。

## 它解决什么

- 属性页出现「数字签名」选项卡，签名者为 `YANG TIANRUI`，带时间戳（换机器后仍可验证）
- 本机 `Get-AuthenticodeSignature` 返回 `Valid`
- 任何字节被改动，签名立刻失效 —— 对你自己是一道防篡改检查

## 它不解决什么

- **不消除 SmartScreen**。自签名证书没有信誉，别人的机器看不到「已验证的发布者」，
  只会看到「未知发布者（已签名，但证书链不可信）」。别指望它提升可信度。
- **不能给别人的机器用**，除非那人手动信任 `certs/dsh-console-selfsigned.cer`。
  让别人手动信任一张来自陌生人的根证书，本身就是个坏习惯 —— 不要建议别人这么做。
- 换机器 / 重装系统后这张证书就没了（私钥 NonExportable，导不出 `.pfx`），
  届时重新生成即可；旧文件的签名仍可验证，但签名者变成另一个指纹。

## 为什么这套根证书只进 CurrentUser\Root

自签名证书的「根」就是它本身，链验证必须找到一张受信任的根才能返回 Valid。所以要么
不信任（`UnknownError`），要么把它放进受信任根。这里只放进**当前用户**存储，不进
`LocalMachine`，撤销时也只影响你自己：

```powershell
# 撤销信任（不会删除证书本身）
certutil -user -delstore Root <指纹>
# 删除证书与私钥
Remove-Item Cert:\CurrentUser\My\<指纹>
```

一条纪律：这张证书只有代码签名 EKU、没有 CertSignReq 用途，但它终究是一张你导入的根。
别把私钥导出去，也别用它去签你来源不明的东西。

## 与真实证书的区别（一句话）

真实 CA 证书买到的是「陌生人也能验证的身份 + 可累积的发布者信誉」；
自签名证书买到的是「本机的完整性检查」。前者要花钱和过审，后者免费，就这么多。

真实证书的路径见 [build-and-signing.md](build-and-signing.md)。
