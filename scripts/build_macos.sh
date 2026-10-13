#!/usr/bin/env bash
# 构建 dsh-pet-standalone macOS .app（本地与 CI 共用的唯一构建入口）。
#
# CI（.github/workflows/build-macos.yml）与本脚本必须保持一致——构建逻辑
# 只有这一份，CI 通过调用本脚本复用，不在 workflow 内联 PyInstaller 命令，
# 避免两处漂移（曾因本地脚本漏 --collect-all PySide6.QtMultimedia 而可能
# 打出缺 QtMultimedia 的坏包）。
#
# 用法：
#   ./scripts/build_macos.sh                          # 本地默认输出 build/macos
#   ./scripts/build_macos.sh --dist dist              # CI：输出到 dist/
#   ./scripts/build_macos.sh --variants webm-chat,webm # 只构建指定变体（CI 只发两个）
#   ./scripts/build_macos.sh --feature-packages <包根> # 随包携带并校验功能包（见下）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# 默认用 PATH 上的 python3（源码环境）；可用 PYTHON_BIN 覆盖。
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || echo python3)}"
# 本机构建隔离依赖目录（scripts/ 下无安装脚本时用系统 python）；CI 走 pip
# install 的系统环境，该目录不存在时直接用系统环境，不设 PYTHONPATH。
BUILD_DEPS="$ROOT/build/.build-deps"
DIST_DIR="$ROOT/build/macos"
WORK_DIR="$ROOT/build/.pyinstaller/macos"
VARIANTS="webm-chat,webm,gif-chat,gif"
# 随包携带的包根（作者用 scripts/build_mod_example.py 打出来的成品包；空 = 不带）。
FEATURE_PACKAGES=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dist) DIST_DIR="$2"; shift 2 ;;
        --variants) VARIANTS="$2"; shift 2 ;;
        --feature-packages) FEATURE_PACKAGES="$2"; shift 2 ;;
        *) echo "未知参数: $1" >&2; exit 1 ;;
    esac
done

cd "$ROOT"
if [[ -d "$BUILD_DEPS/PyInstaller" ]]; then
    export PYTHONPATH="$BUILD_DEPS${PYTHONPATH:+:$PYTHONPATH}"
    export PYINSTALLER_CONFIG_DIR="$ROOT/build/.pyinstaller/config"
fi

"$PYTHON_BIN" scripts/make_icon.py --icns

# 仅当要构建 gif 变体时才生成 GIF 素材（convert_to_gif 默认幂等：只转换
# 缺失/过期的，CI 只构建 webm 变体时不会触发）。
if [[ ",$VARIANTS," == *",gif-chat,"* || ",$VARIANTS," == *",gif,"* ]]; then
    "$PYTHON_BIN" scripts/convert_to_gif.py --clean
fi

mkdir -p "$DIST_DIR" "$WORK_DIR"

IFS=',' read -ra variant_list <<< "$VARIANTS"

# 素材硬门（2026-10-11，与 Windows 的 build_onedir.ps1 同口径）：帧序列产物
# assets/characters/<角色>/frameseq/ 是刻意不入库的派生产物（.gitignore），而
# --add-data 对非 GIF 变体整树拷贝 assets/characters——素材在就进包、缺了也不
# 报错，于是缺帧序列的包会被静默打出来（用户长期看到未转换素材）。这里在
# PyInstaller 起跑前验证每个 clip 都有当前世代的帧序列产物，非零即中止。
# GIF 变体跳过本门：它打包 assets/characters_gif（convert_to_gif.py 直出），
# 素材树里没有也没有 frameseq 这一层，本门不适用。
needs_frameseq=0
for requested in "${variant_list[@]}"; do
    case "$requested" in
        gif|gif-chat) ;;
        *) needs_frameseq=1 ;;
    esac
done
if [[ "$needs_frameseq" == "1" ]]; then
    if ! "$PYTHON_BIN" scripts/check_frameseq_bundle.py; then
        echo "[frameseq] 帧序列素材不完整，拒绝出包（补法见上面的 stderr）" >&2
        exit 1
    fi
fi

# 功能包硬门（2026-10-14，两道，同 frameseq 先例）：--feature-packages 声明这次发布要
# **随包携带**的包根（作者用 scripts/build_mod_example.py 打出来的成品包：目录或 ZIP）。
# 源目录先验一遍——坏包不该等 PyInstaller 跑完（甚至装到用户机器上）才说话；产物里那
# 一份在下面的变体循环里再验一次（拷贝截断/漏件运行期看不出来）。判据只有一份，在
# scripts/verify_feature_package.py（清单 + 验签 + 装前子进程预检）；--target-platform
# 传**产物平台**，所以为别的平台声明的包在这里就会被点名拒绝。
if [[ -n "$FEATURE_PACKAGES" ]]; then
    if ! "$PYTHON_BIN" scripts/verify_feature_package.py --bundle-root "$FEATURE_PACKAGES" --target-platform darwin; then
        echo "[features] 功能包没过门（原因见上面的 stderr），拒绝出包" >&2
        exit 1
    fi
fi

for variant in "${variant_list[@]}"; do
    case "$variant" in
        webm-chat)  entry="packaging/pet_entry.py";            assets="assets/characters";       excludes="" ;;
        webm)       entry="packaging/pet_entry_no_chat.py";    assets="assets/characters";       excludes="pet.chat,keyring" ;;
        gif-chat)   entry="packaging/pet_entry.py";            assets="assets/characters_gif";   excludes="" ;;
        gif)        entry="packaging/pet_entry_no_chat.py";    assets="assets/characters_gif";   excludes="pet.chat,keyring" ;;
        *) echo "未知变体: $variant" >&2; exit 1 ;;
    esac
    name="dsh-pet-standalone-$variant"
    printf "VARIANT = '%s'\n" "$variant" > packaging/build_variant.py

    args=(
        --noconfirm
        --clean
        --onedir
        --windowed
        --paths .
        --distpath "$DIST_DIR"
        --workpath "$WORK_DIR"
        --name "$name"
        --icon assets/icon.icns
        --collect-all imageio_ffmpeg
        --collect-all certifi
        --collect-all PySide6.QtMultimedia
        --collect-all edge_tts
        --collect-all psutil
        --add-data "$assets:$assets"
        --add-data "assets/big_blue_fat_fish:assets/big_blue_fat_fish"
        --add-data "assets/chat:assets/chat"
        --add-data "assets/sounds:assets/sounds"
        --add-data "pet/menu_templates:pet/menu_templates"
        --add-data "pet/persona_presets:pet/persona_presets"
        --add-data "integrations:integrations"
    )
    # 设置页样式表：已在 modern_settings_dialog.py 内联（_settings_stylesheet）
    if [[ "$name" == *-chat ]]; then
        args+=(--collect-all keyring)
        args+=(--add-data "pet/chat/legacy_styles.qss:pet/chat")
        args+=(--add-data "pet/chat/modern_styles.qss:pet/chat")
    fi
    if [[ -n "$excludes" ]]; then
        IFS=',' read -ra exclude_modules <<< "$excludes"
        for module in "${exclude_modules[@]}"; do
            args+=(--exclude-module "$module")
        done
    fi

    echo "==> 构建 $name.app"
    "$PYTHON_BIN" -m PyInstaller "${args[@]}" "$entry"
    # 中文编码自检（issue #26）：字节码/资源/文件名被编码污染即中止。
    "$PYTHON_BIN" scripts/check_bundle_encoding.py --dir "$DIST_DIR/$name.app"
    # Bridge 零依赖防线（2026-09 事故：缺 @deepseek-ai/dsh-llm 导致用户整个
    # dsh 插件树加载失败）：剥掉 --add-data 可能带入的 node_modules 残留，
    # 校验 dist 副本清单零依赖并跑 hermetic 冒烟（见 fix_bridge_bundle.py）。
    "$PYTHON_BIN" scripts/fix_bridge_bundle.py --app-dir "$DIST_DIR/$name.app"
    # 功能包随包携带 + 产物门（2026-10-14）：包根复制进 app 的 Resources/features/
    # （设计文档里"旁置 packages 根"在 .app 上的落法），再对**产物里那一份**验一遍
    # ——源目录验过不等于产物里完好。位置在 codesign 之前：签名要对最终那份内容做。
    if [[ -n "$FEATURE_PACKAGES" ]]; then
        rm -rf "$DIST_DIR/$name.app/Contents/Resources/features"
        cp -R "$FEATURE_PACKAGES" "$DIST_DIR/$name.app/Contents/Resources/features"
        if ! "$PYTHON_BIN" scripts/verify_feature_package.py --bundle-root "$DIST_DIR/$name.app/Contents/Resources/features" --target-platform darwin; then
            echo "[features] 产物里的功能包不完整，拒绝出包" >&2
            exit 1
        fi
    fi
    codesign --force --deep --sign - "$DIST_DIR/$name.app"
done

echo "macOS 构建完成：$DIST_DIR"
