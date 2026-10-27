"""Smart App Control 放行所需的签名接线（安装包 / 主程序 / 卸载器）。

背景（本机 2026-10-27 实测）：`VerifiedAndReputablePolicyState=1`（SAC 强制）下，
CodeIntegrity 3077/3118 只拦了安装时才生成的 `unins000.exe`——它是安装包里唯一
构建时不存在的 PE，因此从未被签过；setup 与 dsh-pet-core.exe 因为用开发证书签过
都能跑。这里把「安装时也签卸载器」的接线钉住，删掉就会重新退回被拦状态。

真实签名结果由构建产出（`.scratch/sac-verify.log` 与交付报告）证明，不由单测冒充。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_petcore.ps1"
ISS = ROOT / "packaging" / "petcore.iss"


def test_iss_signs_the_installer_only_when_a_thumbprint_is_supplied() -> None:
    iss = ISS.read_text(encoding="utf-8")

    assert "#ifdef SignUninstaller" in iss, "签名块必须可开关，否则未签名构建会失败"
    assert "SignTool=devsign" in iss
    assert "SignedUninstaller=yes" in iss, "unins000.exe 不签就会被 SAC 拦"


def test_build_script_registers_the_signtool_and_enables_uninstaller_signing() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "/Sdevsign=" in text, "Inno 需要按名字注册签名工具"
    assert "scripts/sign_artifact.ps1" in text.replace("\\", "/")
    assert "/DSignUninstaller=1" in text
    # 只有带 -SignThumbprint 时才追加这两个参数：默认构建保持原样。
    assert "if ($SignThumbprint) {" in text


def test_signing_tooling_exists_and_never_ships_a_private_key() -> None:
    signer = ROOT / "scripts" / "sign_artifact.ps1"
    installer = ROOT / "scripts" / "install_dev_cert.ps1"

    assert signer.is_file() and "Set-AuthenticodeSignature" in signer.read_text(encoding="utf-8")
    cert_text = installer.read_text(encoding="utf-8")
    assert "Cert:\\CurrentUser\\Root" in cert_text
    assert "Cert:\\CurrentUser\\TrustedPublisher" in cert_text
    assert "HasPrivateKey" in cert_text, "只分发公钥 .cer；带私钥必须拒绝"


def test_build_signs_the_exe_before_the_smoke_check() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    # 先签名再冒烟：未签名的 exe 起不来，冒烟会误报成构建失败。
    sign_at = text.index("Sign-Artifact $exe")
    smoke_at = text.index("== smoke --check --strict ==")
    assert sign_at < smoke_at
