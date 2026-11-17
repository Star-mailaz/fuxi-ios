#!/bin/bash
# fuxi-kernel-build.sh：在 WSL（Ubuntu）本機建置小米 13 的 FUXI 核心
# （xnu-8796.141.3 DEVELOPMENT ARM64 FUXI），不經 GitHub macOS runner。
#
# 步驟對應 harness 的 .github/workflows/kernel-adsp-battery.yml 與 ios-fuxi 的
# tools/ci/build.sh kernel()（blacktop/darwin-xnu-build 的 build.sh），差別只在工具：
# Xcode 換成 UniXNU 的 Linux 工具鏈（/opt/unixnu-linux，setup-unixnu-toolchain.sh 安裝）。
# Linux 專用的部分（fakeroot、來源改寫、make 參數、ISA 檢查）改寫自
# DenialOfGravity/ios-redfin 的 tools-claude/localbuild/xnu.sh（MIT 授權），
# 它建置的是同一版 xnu 與同一個 blacktop builder commit。
#
# 用法（在 WSL 內，root）：
#   fuxi-kernel-build.sh [--ram full|9g] [--name NAME] [--harness DIR] [--ath12k DIR]
#                        [--clean] [--jobs N] [--tests]
# 產物：$OUT_ROOT/NAME/（預設 work/Codex-Xiaomi13-GPU-20261109/kernel-local-<時間>-<ram>-artifact，
# 也就是 loader 產生器 --artifact 讀的位置），
# 檔名與 CI artifact 相同：kernel.development.fuxi、kernel.development.fuxi.unstripped、
# fuxi.adt 等 kernel-inputs.py 的輸出、SHA256SUMS、logs/build.log。
#
# 與 CI 產物的已知差異：編譯器是上游 clang（非 Apple clang），所以機器碼不會逐位元相同；
# 沒有 CTF 與 dSYM。上機前先用 CI 產物確認過同一份補丁可開機，再信任本機產物。
set -uo pipefail

RAM=full NAME= CLEAN=0 TESTS=0 ATH12K= NOTE=
HARNESS=${HARNESS:-/mnt/d/xiaomi13/fuxi_ios/work/adsp-battery/harness}
OUT_ROOT=${OUT_ROOT:-/mnt/d/xiaomi13/fuxi_ios/work/Codex-Xiaomi13-GPU-20261109}   # loader 產生器的 STORAGE
BR=${FUXI_BUILD_ROOT:-/root/fuxi-build}
TC=${UNIXNU_TOOLCHAIN:-/opt/unixnu-linux}
UNIXNU_SRC=${UNIXNU_SRC:-/opt/src/UniXNU}
JOBS=${JOBS:-$(nproc)}
while [ $# -gt 0 ]; do
	case "$1" in
	--ram) RAM=$2; shift 2 ;;
	--name) NAME=$2; shift 2 ;;
	--harness) HARNESS=$2; shift 2 ;;
	--ath12k) ATH12K=$2; shift 2 ;;
	--jobs) JOBS=$2; shift 2 ;;
	--note) NOTE=$2; shift 2 ;;
	--clean) CLEAN=1; shift ;;
	--tests) TESTS=1; shift ;;
	*) echo "unknown argument: $1" >&2; exit 2 ;;
	esac
done
say() { echo "[$(date +%T)] $*"; }
die() { echo "[$(date +%T)] ERROR: $*" >&2; exit 1; }
[ "$RAM" = full ] || [ "$RAM" = 9g ] || die "--ram must be full or 9g"
NAME=${NAME:-kernel-local-$(date +%m%d-%H%M%S)-$RAM-artifact}
[ -f "$HARNESS/.github/workflows/kernel-adsp-battery.yml" ] || die "no workflow in $HARNESS"

SRC=$BR/src                 # 快取的原始碼（不會被修改）
W=$BR/work-$RAM             # 每種記憶體配置一棵建置樹，各自保持增量
X=$W/xnu FR=$W/xnu/fakeroot
S=$W/source                 # ios-fuxi 釘選 commit ＋ harness 補丁
OUT=$OUT_ROOT/$NAME
CLT=$TC/CommandLineTools/usr XCT=$TC/XcodeDefault.xctoolchain/usr
XNU_CLANG=$TC/llvm/bin/clang
XNU_TAG=xnu-8796.141.3 MACOS_VERSION=13.5 RC_DARWIN_KERNEL_VERSION=22.6.0
KERNEL_CONFIG=DEVELOPMENT ARCH_CONFIG=ARM64 MACHINE_CONFIG=FUXI
RELEASE_URL=https://raw.githubusercontent.com/apple-oss-distributions/distribution-macOS/macos-135/release.json
LLVM_COMMIT=58c46bae21181fb4240cf964461bea738d96d50e   # libcc_kext 用的 compiler-rt profile 來源（UniXNU 的釘選）
LIBC_COMMIT=899a3b2d52d95d75e05fb286a5e64975ec3de757
mkdir -p "$SRC" "$W" "$X" "$FR" "$OUT/logs"
# 同一配置共用增量目錄，拒絕另一個建置同時改寫它。
exec 9>"$W/.build.lock"
flock -n 9 || die "another $RAM build is using $W"
echo "result RUNNING" > "$OUT/BUILD.txt"
rm -f "$OUT/SHA256SUMS" "$OUT/ath12k-link.json"
finish() {
	local rc=$?
	if [ "$rc" != 0 ]; then
		printf 'result FAILED\nexit %s\n' "$rc" > "$OUT/BUILD.txt"
	fi
}
trap finish EXIT
# harness 在 Windows 上是 autocrlf 的工作目錄：git 裡是 LF 的檔案，取出後每行都是 CRLF。
# 這裡還原成 commit 進去時的內容（整份每行都是 CRLF 才轉；本來就是 LF 或混合的不動）。
lf_copy() {  # src dst
	local total crlf
	total=$(wc -l < "$1"); crlf=$(grep -c $'\r$' "$1")
	if [ "$crlf" -gt 0 ] && [ "$crlf" = "$total" ]; then sed 's/\r$//' "$1" > "$2"; else cp "$1" "$2"; fi
}
HP=$W/harness-lf            # LF 版的 workflow 與補丁
rm -rf "$HP"; mkdir -p "$HP/patches"
WORKFLOW=$HP/kernel-adsp-battery.yml
lf_copy "$HARNESS/.github/workflows/kernel-adsp-battery.yml" "$WORKFLOW"
[ -x "$XNU_CLANG" ] && [ -x "$CLT/bin/ld" ] && [ -x "$CLT/libexec/migcom" ] && [ -x "$XCT/bin/iig" ] ||
	die "toolchain incomplete in $TC: run setup-unixnu-toolchain.sh"
T0=$(date +%s)

# UniXNU 的 xcrun／clang shim 讀這些變數：SDK 路徑指向 fakeroot；clang 用 FUXI 的 plain arm64。
# -mcpu=generic：arm64-apple-macos 這個 triple 上游 clang 預設 target-cpu 是 apple-m1，會產生
# MACHINE_FLAGS（-march=armv8.2-a+crypto）以外的指令；Apple clang（CI）不會。
export XNU_TOOLCHAIN_BIN="$CLT/bin $XCT/bin" UNIXNU_SDKROOT=$FR UNIXNU_SDK_VERSION=14.0 PLATFORM=MacOSX
export CROSS_CLANG=$XNU_CLANG DARWIN_TRIPLE=arm64-apple-macos14.0
export CROSS_EXTRA_FLAGS="-mcpu=generic -mllvm -disable-atexit-based-global-dtor-lowering -Wno-error=incompatible-pointer-types"
mkdir -p "$BR/bin"; ln -sf "$(command -v python3)" "$BR/bin/python"   # tools/lldbmacros 用 `env python`
export PATH="$BR/bin:$CLT/bin:$XCT/bin:$PATH" LC_ALL=C

fetch_commit() {  # dir url commit：淺層取得指定 commit（已是該 commit 就略過）
	[ "$(git -C "$1" rev-parse HEAD 2>/dev/null)" = "$3" ] && return 0
	rm -rf "$1"; git init -q "$1"
	git -C "$1" fetch -q --no-tags --depth 1 "$2" "$3" && git -C "$1" checkout -q --detach FETCH_HEAD
}
tag_of() {
	[ -s "$SRC/macos-135.json" ] || curl -fsSL "$RELEASE_URL" -o "$SRC/macos-135.json" || die "release.json"
	python3 -c "import json,sys;print([p['tag'] for p in json.load(open(sys.argv[1]))['projects'] if p['project']==sys.argv[2]][0])" "$SRC/macos-135.json" "$1"
}
apple() {  # project -> $SRC/<tag>（macOS 13.5 的 tag，淺層 clone）
	local tag; tag=$(tag_of "$1") || exit 1
	local d=$SRC/$tag
	[ -d "$d/.git" ] || git clone -q --depth 1 --branch "$tag" "https://github.com/apple-oss-distributions/$1.git" "$d" || die "clone $1 $tag"
	echo "$d"
}

# ---- 1. ios-fuxi 釘選 commit ＋ harness 補丁（順序直接讀 workflow，與 CI 同步）----
KSRC_URL=$(grep -oE 'remote add origin [^ ]+' "$WORKFLOW" | head -1 | awk '{print $NF}')
KSRC_SHA=$(grep -oE 'fetch --no-tags --depth=1 origin [0-9a-f]{40}' "$WORKFLOW" | head -1 | awk '{print $NF}')
mapfile -t HPATCHES < <(grep -oE 'git -C source apply \.\./harness/patches/[A-Za-z0-9._-]+' "$WORKFLOW" | awk -F/ '{print $NF}')
[ -n "$KSRC_URL" ] && [ -n "$KSRC_SHA" ] && [ "${#HPATCHES[@]}" -gt 0 ] || die "cannot read source pin / patch list from $WORKFLOW"
say "source $KSRC_URL @ $KSRC_SHA, ${#HPATCHES[@]} harness patches, ram=$RAM"
# fuxi-ios 公開倉庫在自己的歷史裡收了未修改的上游基底：upstream/EXPORT-SOURCES.txt 的
# kernel-base 列出釘選 commit 對應的 tree。harness 是這種倉庫時直接從它取，不連上游。
KSRC_TREE= KSRC_FROM=$KSRC_URL
if [ -f "$HARNESS/upstream/EXPORT-SOURCES.txt" ]; then
	KSRC_TREE=$(awk -v c="$KSRC_SHA" '$1 == "kernel-base" && $2 == c { print $3 }' "$HARNESS/upstream/EXPORT-SOURCES.txt")
fi
rm -rf "$S"; mkdir -p "$S"
if [ -n "$KSRC_TREE" ]; then
	hgit() { git -c safe.directory='*' -C "$HARNESS" "$@"; }
	[ "$(hgit cat-file -t "$KSRC_TREE" 2>/dev/null)" = tree ] ||
		die "kernel base tree $KSRC_TREE not in $HARNESS (shallow clone? run git fetch --unshallow)"
	KSRC_FROM="in-repo tree $KSRC_TREE"
	say "source from $KSRC_FROM"
	hgit archive "$KSRC_TREE" | tar -x -C "$S" || die "export in-repo kernel base"
else
	fetch_commit "$SRC/ios-fuxi" "$KSRC_URL" "$KSRC_SHA" || die "fetch ios-fuxi"
	git -C "$SRC/ios-fuxi" archive HEAD | tar -x -C "$S" || die "export ios-fuxi"
fi
test_n=0
if [ "$TESTS" = 1 ]; then
	say "host tests interleaved with patches, in workflow order"
	[ ! -d "$W/harness" ] || [ -L "$W/harness" ] || die "unexpected directory: $W/harness"
	rm -f "$W/harness"; ln -s "$HARNESS" "$W/harness" || die "host test harness link"
	: > "$OUT/logs/tests.txt"
	python3 - "$WORKFLOW" "$HP/test-commands.tsv" <<'PY' || die "workflow test commands"
import re, sys
from pathlib import Path
active = False
patch = None
rows = []
for raw in Path(sys.argv[1]).read_text().splitlines():
    line = raw.strip()
    if line.startswith('- name:'):
        if active:
            break
        active = line == '- name: Fetch pinned public kernel source and apply patches'
    if not active:
        continue
    match = re.fullmatch(r'git -C source apply ../harness/patches/([A-Za-z0-9._-]+)', line)
    if match:
        patch = match[1]
    elif re.match(r'python3 (?:harness/tests/|source/tools/)|\(cd source && ', line):
        if patch is None:
            raise SystemExit('test before first patch')
        rows.append(patch + '\t' + line + '\n')
if not rows:
    raise SystemExit('no workflow tests found')
Path(sys.argv[2]).write_text(''.join(rows))
PY
fi
for p in "${HPATCHES[@]}"; do
	[ -f "$HARNESS/patches/$p" ] || die "harness patch missing: $p"
	lf_copy "$HARNESS/patches/$p" "$HP/patches/$p"
	( cd "$S" && git apply --check "$HP/patches/$p" && git apply "$HP/patches/$p" ) ||
		die "harness patch does not apply: $p"
	if [ "$TESTS" = 1 ]; then
		while IFS=$'\t' read -r test_patch line; do
			[ "$test_patch" = "$p" ] || continue
			test_n=$((test_n + 1)); log=$(printf '%s/logs/test-%02d.log' "$OUT" "$test_n")
			# 這裡要產出 Linux 主機程式，不能走 Darwin clang shim。
			( cd "$W" && PATH="/usr/bin:/bin:$PATH" CC=/usr/bin/clang CXX=/usr/bin/clang++ bash -c "$line" ) > "$log" 2>&1 ||
				{ tail -20 "$log"; die "host test failed: $line"; }
			printf 'PASS %s\n' "$line" >> "$OUT/logs/tests.txt"
		done < "$HP/test-commands.tsv"
	fi
done
if [ "$TESTS" = 1 ]; then
	[ "$test_n" = "$(wc -l < "$HP/test-commands.tsv")" ] || die "workflow tests were not all executed"
	say "host tests passed: $test_n commands"
fi
{ echo "source $KSRC_URL $KSRC_SHA"; echo "source-from $KSRC_FROM"; echo "ram $RAM"
  echo "workflow $(sha256sum < "$WORKFLOW" | cut -c1-64)"
  echo "local-script $(sha256sum < "$0" | cut -c1-64)"
  for p in "${HPATCHES[@]}"; do echo "$(sha256sum < "$HP/patches/$p" | cut -c1-64)  $p"; done   # LF 內容的雜湊
  echo "${NOTE:-harness (version not recorded)}"
} > "$OUT/INPUTS.txt"

# ---- 2. blacktop builder 的補丁目錄（用專案自己的 prepare-kernel.py 產生）----
. <(grep -E '^DXB_SHA=' "$S/tools/ci/pins.env")
fetch_commit "$SRC/dxb" https://github.com/blacktop/darwin-xnu-build.git "$DXB_SHA" || die "fetch dxb"
rm -rf "$W/dxb"; mkdir -p "$W/dxb"
git -C "$SRC/dxb" archive HEAD | tar -x -C "$W/dxb"
export FUXI_RAM_LAYOUT=$RAM
if [ -n "$ATH12K" ]; then   # CI 的 fuxi-ath12k-objects artifact（選用；路徑不能有特殊字元）
	rm -rf "$W/ath12k-out"; cp -r "$ATH12K" "$W/ath12k-out"
	( cd "$S" && python3 tools/ci/ath12k-link.py "$W/ath12k-out" ) || die "ath12k bundle check"
	export FUXI_ATH12K_OBJECT=$W/ath12k-out/fuxi_ath12k.o
	DARWIN_TRIPLE=$(python3 -c 'import runpy,sys; print(runpy.run_path(sys.argv[1])["KERNEL_TARGET"])' "$S/tools/ci/ath12k-link.py") || die "ath12k kernel target"
	export DARWIN_TRIPLE UNIXNU_SDK_VERSION=${DARWIN_TRIPLE##*-macos}
fi
python3 "$S/tools/ci/prepare-kernel.py" "$W/dxb" || die "prepare-kernel.py"

# ---- 3. 打好補丁的 xnu 原始碼 ----
PRISTINE=$(apple xnu)
[ "$(basename "$PRISTINE")" = "$XNU_TAG" ] || die "13.5's xnu is $(basename "$PRISTINE"), expected $XNU_TAG"
PREP=$X/prep
rm -rf "$PREP"; mkdir -p "$PREP" "$FR/usr/include"
rsync -a --exclude .git "$PRISTINE/" "$PREP/xnu/"
# 0026-stage-hfs.sh 會從 `xcrun --sdk macosx --show-sdk-path` 取 TargetConditionals.h
cp "$UNIXNU_SRC/scripts/linux/TargetConditionals.h" "$FR/usr/include/" || die "TargetConditionals.h"
say "patching: $(ls "$W/dxb/patches" | grep -cE '\.(sh|patch)$') files"
(
	cd "$PREP/xnu" || exit 1
	# blacktop patches() 的 sed（GNU sed）。MIG／MIGCOM 改由 make 參數傳入，不做它的 find 改寫。
	sed -i 's|^AVAILABILITY_PL="${SDKROOT}/${DRIVERKITROOT}|AVAILABILITY_PL="${FAKEROOT_DIR}|g' bsd/sys/make_symbol_aliasing.sh
	sed -i 's|^#include.*BSD.xcconfig.*||g' libsyscall/Libsyscall.xcconfig
	sed -i 's|^LDFLAGS_KERNEL_SDK	= -L$(SDKROOT).*|LDFLAGS_KERNEL_SDK	= -L$(FAKEROOT_DIR)/usr/local/lib/kernel -lfirehose_kernel|g' makedefs/MakeInc.def
	sed -i 's|^\(INCFLAGS_SDK[[:space:]]*=\) -I$(SDKROOT)/usr/local/include/\(kernel\)\{0,1\}|\1 -I$(FAKEROOT_DIR)/usr/local/include/kernel|' makedefs/MakeInc.def
	export MACOS_VERSION MACHINE_CONFIG KDKROOT=$X/fake-kdk
	for s in "$W"/dxb/patches/*.sh; do
		[ -e "$s" ] || continue
		say "script $(basename "$s")"
		bash "$s" || { echo "PATCH SCRIPT FAILED: $(basename "$s")"; exit 1; }
	done
	napplied=0 nskipped=0
	for p in "$W"/dxb/patches/*.patch; do
		b=$(basename "$p")
		if c=$(git apply --check "$p" 2>&1); then
			git apply "$p" || { echo "PATCH FAILED: $b"; exit 1; }
			napplied=$((napplied + 1))
		elif [ -e "$p.fuxi-required" ]; then   # 與 CI 相同：必要的 Fuxi 補丁套不上就失敗
			echo "PATCH FAILED: required Fuxi patch $b: $(echo "$c" | head -1)"; exit 1
		else
			echo "skip $b: $(echo "$c" | head -1)"; nskipped=$((nskipped + 1))
		fi
	done
	echo "patches applied: $napplied (skipped builder patches: $nskipped)"
	# Linux 專用改寫（非核心補丁；來源同 UniXNU scripts/linux/prepare-xnu.py "source" 與 ios-redfin xnu.sh）
	python3 - <<'PY'
from pathlib import Path
s = Path('bsd/kern/makesyscalls.sh'); t = s.read_text()
if '\\(sy_call_t *\\)' in t: s.write_text(t.replace('\\(sy_call_t *\\)', '(sy_call_t *)')); print('linux: makesyscalls.sh mawk escape')
s = Path('osfmk/arm64/corecrypto/arm64_isa_compatibility.h')
old = '#if defined(__clang__) && ((defined(__apple_build_version__) && __apple_build_version__ > 5010000))\n'
if s.exists() and old in s.read_text():
    s.write_text(s.read_text().replace(old, '#if defined(__clang__) && (!defined(__apple_build_version__) || __apple_build_version__ > 5010000)\n')); print('linux: arm64_isa_compatibility.h')
s = Path('SETUP/kextsymboltool/kextsymboltool.c'); t = s.read_text()
old = '''	if (offset != lseek(fd, offset, SEEK_SET)) {
		err = kErrorDiskFull;
	} else {
		err = kErrorNone;
	}
'''
new = '''	if (offset != lseek(fd, offset, SEEK_SET)) {
		struct stat st;
		/* Linux lseek() returns 0 on /dev/null (check_all_exports): not an error */
		if (0 == fstat(fd, &st) && S_ISCHR(st.st_mode)) {
			return kErrorNone;
		}
		err = kErrorDiskFull;
	} else {
		err = kErrorNone;
	}
'''
if 'S_ISCHR' not in t and t.count(old) == 1:
    t = t.replace(old, new)
    if '#include <sys/stat.h>' not in t: t = t.replace('#include <sys/types.h>', '#include <sys/types.h>\n#include <sys/stat.h>', 1)
    s.write_text(t); print('linux: kextsymboltool lseek')
# Apple clang 對 C++ 裡 __typeof__ 內的 *(void *) 只警告；上游 clang 直接報錯。同一個檢查改用 __remove_pointer。
s = Path('osfmk/kern/kalloc.h'); t = s.read_text()
old = """	(__builtin_xnu_types_compatible(__typeof__(*(ptr)), type) ||   \\
	    __builtin_xnu_types_compatible(__typeof__(*(ptr)), void))  \\
"""
new = """	(__builtin_xnu_types_compatible(__KT_PTR_ELEM_T(ptr), type) ||   \\
	    __builtin_xnu_types_compatible(__KT_PTR_ELEM_T(ptr), void))  \\
"""
defs = """#ifdef __cplusplus
#define __KT_PTR_ELEM_T(ptr) __remove_pointer(__typeof__(ptr))
#else
#define __KT_PTR_ELEM_T(ptr) __typeof__(*(ptr))
#endif
#define KALLOC_TYPE_IS_COMPATIBLE_PTR(ptr, type)"""
if old in t:
    t = t.replace(old, new).replace('#define KALLOC_TYPE_IS_COMPATIBLE_PTR(ptr, type)', defs, 1)
    s.write_text(t); print('linux: kalloc.h KALLOC_TYPE_IS_COMPATIBLE_PTR for C++')
else:
    print('linux: kalloc.h pattern not found (changed upstream?)')
PY
) > "$OUT/logs/patch.log" 2>&1 || { tail -30 "$OUT/logs/patch.log"; die "patching failed (logs/patch.log)"; }
tail -8 "$OUT/logs/patch.log"
mkdir -p "$X/xnu"
# 只改寫內容有變的檔案，make 才能增量
CHANGED=$(rsync -rlc --no-times --delete --exclude .git --itemize-changes "$PREP/xnu/" "$X/xnu/" | grep -vc '^\.')
say "synced into build tree: $CHANGED changed entries"
[ "$CLEAN" = 1 ] && rm -rf "$X/build"
rm -rf "$X"/build/xnu.obj/kernel.* "$FR"/System/Library/Kernels/kernel.*

# 編譯器或旗標變了 make 不會察覺：全部重建
FLAGS_ID="$(sha1sum < "$XNU_CLANG" | cut -c1-12) $DARWIN_TRIPLE $CROSS_EXTRA_FLAGS $(sha1sum < "$CLT/bin/clang" | cut -c1-12)"
if [ "$(cat "$X/build/.lb-flags" 2>/dev/null)" != "$FLAGS_ID" ]; then
	say "compiler/flags changed: full rebuild"
	rm -rf "$X/build/xnu.obj" "$X/build/xnu.sym" "$X/build/firehose" "$SRC/linux-cc_kext/obj" \
		"$FR/usr/local/lib/kernel/libfirehose_kernel.a" "$FR/usr/local/lib/kernel/libcc_kext.a"
	mkdir -p "$X/build"; echo "$FLAGS_ID" > "$X/build/.lb-flags"
fi

# ---- 4. fakeroot（每棵建置樹做一次）----
# installhdrs 也會執行 IIG；從這一步起就必須重播同一份 cache。
export IIG=$S/tools/xnu-iig-cache.py XNU_IIG_CACHE=$S/xnu/iig-pregen
[ -x "$IIG" ] && [ -f "$XNU_IIG_CACHE/manifest.json" ] || die "IIG replay cache missing in the patched source"
MEM=$(( $(getconf _PHYS_PAGES) * $(getconf PAGE_SIZE) ))
LINUX_ARGS=(HOST_CC="$CLT/bin/xnu-host-cc" MIG="$CLT/bin/mig" MIGCOM="$CLT/libexec/migcom" TIGHTBEAMC=tightbeamc-not-supported
	BUILD_DSYM=0 MEMORY_SIZE=$MEM SYSCTL_HW_PHYSICALCPU=$JOBS SYSCTL_HW_LOGICALCPU=$JOBS KERNEL_BUILDS_IN_PARALLEL=1
	RC_DARWIN_KERNEL_VERSION=$RC_DARWIN_KERNEL_VERSION FAKEROOT_DIR="$FR" KDKROOT="$X/fake-kdk")
mkdir -p "$X/fake-kdk" "$FR/usr/local/lib/kernel" "$FR/usr/local/include/kernel/os"
if [ ! -x "$FR/usr/local/libexec/availability.pl" ] || [ ! -f "$FR/usr/local/include/dyld/VersionMap.h" ]; then
	say "fakeroot: AvailabilityVersions"
	AV=$(apple AvailabilityVersions)
	rm -f "$FR/System/Library/Frameworks/Kernel.framework/Versions/A/Headers/AvailabilityVersions.h"
	make -C "$AV" install -j"$JOBS" OBJROOT="$X/build/availability" SYMROOT="$X/build/availability" DSTROOT="$FR" \
		CMAKE="$(command -v cmake)" NINJA="$(command -v ninja)" > "$OUT/logs/availability.log" 2>&1 ||
		{ tail -20 "$OUT/logs/availability.log"; die "AvailabilityVersions (needs ruby)"; }
fi
if [ ! -f "$FR/.xnu-headers-iig-replay-v1" ]; then
	say "fakeroot: xnu headers"
	rm -rf "$X/build/xnu-hdrs.obj" "$X/build/xnu-hdrs.sym"
	( cd "$X/xnu" && make installhdrs SDKROOT=macosx ARCH_CONFIGS=ARM64 OBJROOT="$X/build/xnu-hdrs.obj" \
		SYMROOT="$X/build/xnu-hdrs.sym" DSTROOT="$FR" "${LINUX_ARGS[@]}" ) > "$OUT/logs/installhdrs.log" 2>&1 ||
		{ tail -30 "$OUT/logs/installhdrs.log"; die "installhdrs"; }
	touch "$FR/.xnu-headers-iig-replay-v1"
fi
if [ ! -f "$FR/usr/local/include/_simple.h" ]; then
	say "fakeroot: libplatform headers"
	LP=$(apple libplatform)
	cp -R "$LP/include/." "$LP/private/." "$FR/usr/local/include/"
	mkdir -p "$FR/System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/platform"
	cp -R "$LP/private/platform/." "$FR/System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/platform/"
fi
if [ ! -f "$FR/usr/local/lib/kernel/libfirehose_kernel.a" ]; then
	say "fakeroot: libfirehose_kernel"
	LD_=$(apple libdispatch)
	mkdir -p "$FR/usr/local/include/os" "$X/build/firehose"
	for h in "$LD_"/os/*.h; do unifdef -DKERNEL=1 -DOS_FIREHOSE_SPI=1 -DOS_VOUCHER_ACTIVITY_SPI_TYPES=1 -UOS_VOUCHER_ACTIVITY_SPI \
		-o "$FR/usr/local/include/os/$(basename "$h")" "$h"; done
	unifdef -DKERNEL=1 -DOS_FIREHOSE_SPI=1 -DOS_VOUCHER_ACTIVITY_SPI_TYPES=1 -UOS_VOUCHER_ACTIVITY_SPI \
		-o "$FR/usr/local/include/kernel/os/firehose_buffer_private.h" "$LD_/os/firehose_buffer_private.h"
	xcrun clang -std=gnu11 -Os -g -mkernel -nostdinc -Wno-packed -DKERNEL=1 -DDISPATCH_USE_DTRACE=0 \
		-DOS_ATOMIC_CONFIG_MEMORY_ORDER_DEPENDENCY=1 -DOS_ATOMIC_CONFIG_STARVATION_FREE_ONLY=0 \
		-I"$LD_" -I"$FR/System/Library/Frameworks/Kernel.framework/PrivateHeaders" \
		-I"$FR/System/Library/Frameworks/Kernel.framework/Headers" -I"$FR/usr/local/include/os" \
		-I"$FR/usr/local/include/firehose" -I"$FR/usr/include" -I"$FR/usr/local/include" -I"$X/xnu/EXTERNAL_HEADERS" \
		-c "$LD_/src/firehose/firehose_buffer.c" -o "$X/build/firehose/firehose_buffer.o" || die "firehose_buffer.c"
	xcrun libtool -static -o "$FR/usr/local/lib/kernel/libfirehose_kernel.a" "$X/build/firehose/firehose_buffer.o" || die libtool
fi
if [ ! -f "$FR/usr/local/lib/kernel/libcc_kext.a" ] || [ ! -f "$FR/.cc-kext-profile-udiv-v1" ]; then
	say "fakeroot: libcc_kext.a"
	L=$SRC/linux-cc_kext; mkdir -p "$L/obj"
	for spec in "llvm-project https://github.com/llvm/llvm-project $LLVM_COMMIT compiler-rt/lib/profile compiler-rt/include/profile compiler-rt/lib/builtins" \
	            "Libc https://github.com/apple-oss-distributions/Libc.git $LIBC_COMMIT include"; do
		set -- $spec; d=$L/$1
		[ "$(git -C "$d" rev-parse HEAD 2>/dev/null)" = "$3" ] && continue
		rm -rf "$d"; git init -q "$d"; git -C "$d" sparse-checkout set --no-cone "${@:4}"
		git -C "$d" fetch -q --depth 1 --filter=blob:none "$2" "$3" && git -C "$d" checkout -q FETCH_HEAD || die "fetch $1"
	done
	# 舊快取可能只抓過 profile；同一 commit 也要補齊 builtins。
	git -C "$L/llvm-project" sparse-checkout add compiler-rt/lib/builtins || die "cc_kext builtin sources"
	objs=()
	# XNU 8796 的 Availability.h 尚無 Libsyscall 使用的 SPI／bridgeos 註記。
	# 僅在這份核心 profiling library 略去私有 API 的平台註記，不改宣告或程式碼。
	for n in InstrProfiling InstrProfilingBuffer InstrProfilingPlatformDarwin InstrProfilingWriter InstrProfilingInternal InstrProfilingVersionVar; do
		xcrun clang -isysroot "$FR" -mkernel -DKERNEL_USE -O3 -fPIC -w -I "$L/llvm-project/compiler-rt/include" \
			'-D__SPI_AVAILABLE(...)=' \
			-I "$FR/System/Library/Frameworks/Kernel.framework/Headers" -I "$X/xnu/EXTERNAL_HEADERS" -idirafter "$L/Libc/include" \
			-idirafter "$X/xnu/libsyscall/wrappers" -c "$L/llvm-project/compiler-rt/lib/profile/$n.c" -o "$L/obj/$n.o" || die "cc_kext $n"
		objs+=("$L/obj/$n.o")
	done
	# 上游 clang 的 128-bit 除法會呼叫 compiler-rt；Apple clang 的既有 CI 路徑未需要此符號。
	for n in udivti3 udivmodti4; do
		xcrun clang -isysroot "$FR" -mkernel -O2 -fno-builtin -ffreestanding -nostdlibinc \
			-c "$L/llvm-project/compiler-rt/lib/builtins/$n.c" -o "$L/obj/$n.o" || die "cc_kext $n"
		objs+=("$L/obj/$n.o")
	done
	xcrun libtool -static -o "$FR/usr/local/lib/kernel/libcc_kext.a" "${objs[@]}" || die libtool
	touch "$FR/.cc-kext-profile-udiv-v1"
fi

# ---- 5. 核心 ----
# CI 用 FUXI_IIG_MODE=replay：不跑 iig，重播雜湊比對過的 Xcode 15 iig 產物。本機照做。
export KERNEL_BUILD_DATE=${KERNEL_BUILD_DATE:-$(TZ=UTC git -C "$PRISTINE" log -1 --format=%cd --date=format-local:'%a %b %e %T %Z %Y')}
export KERNEL_BUILD_OBJROOT=$XNU_TAG
T1=$(date +%s)
say "make install ($JOBS jobs) -> logs/build.log"
( cd "$X/xnu" && make install -j"$JOBS" -Otarget -k VERBOSE=YES SDKROOT=macosx \
	TARGET_CONFIGS="$KERNEL_CONFIG $ARCH_CONFIG $MACHINE_CONFIG" CONCISE=0 LOGCOLORS=n BUILD_WERROR=0 BUILD_LTO=0 \
	SRCROOT="$X/xnu" OBJROOT="$X/build/xnu.obj" SYMROOT="$X/build/xnu.sym" DSTROOT="$FR" \
	LD_KERNEL_LIBS="$FR/usr/local/lib/kernel/libcc_kext.a" "${LINUX_ARGS[@]}" ) > "$X/build/build.log" 2>&1
rc=$?
T2=$(date +%s)
K=$FR/System/Library/Kernels/kernel.development.fuxi
KU=$X/build/xnu.sym/kernel.development.fuxi
if [ $rc != 0 ] || [ ! -f "$K" ]; then
	grep -a -n -E ':[0-9]+:[0-9]+: (fatal )?error:|^clang.*error:|^ld:|^Undefined symbols|^  "|^make.*\*\*\*' "$X/build/build.log" | head -300 > "$OUT/errors.txt"
	grep -a -n -B3 -A12 -E ':[0-9]+:[0-9]+: (fatal )?error:|^clang.*error:|^ld:|^Undefined symbols' "$X/build/build.log" | head -1500 > "$OUT/errors-context.txt"
	tail -300 "$X/build/build.log" > "$OUT/tail.txt"
	gzip -9 -c "$X/build/build.log" > "$OUT/logs/build.log.gz"
	say "make failed (rc $rc) after $((T2 - T1)) s; first errors:"; head -40 "$OUT/errors.txt"
	echo "result FAILED" > "$OUT/BUILD.txt"; exit 1
fi
gzip -9 -c "$X/build/build.log" > "$OUT/logs/build.log.gz"
cp "$K" "$OUT/kernel.development.fuxi" || die "copy kernel"
cp "$KU" "$OUT/kernel.development.fuxi.unstripped" || die "copy unstripped kernel"
echo "$FLAGS_ID" > "$OUT/COMPILER.txt"

# ISA 檢查：MACHINE_FLAGS 是 armv8.2-a+crypto，出現更新架構的指令代表編譯器旗標跑掉了
OBJDUMP=$(command -v llvm-objdump || ls /usr/bin/llvm-objdump-* 2>/dev/null | sort -V | tail -1)
if [ -n "$OBJDUMP" ]; then
	"$OBJDUMP" -d --no-show-raw-insn --no-leading-addr "$K" > "$W/disassembly.txt" || die "kernel disassembly"
	awk -F'\t' '/^ +\t/{split($2,m,".");print m[1]}' "$W/disassembly.txt" > "$W/mnemonics.txt"
	decoded=$(wc -l < "$W/mnemonics.txt")
	[ "$decoded" -gt 0 ] || die "ISA check decoded no instructions"
	bad=$(grep -c -x -E 'stlur[bh]?|ldapur(s?[bhw])?|cfinv|setf8|setf16|rmif|axflag|xaflag|frint(32|64)[xz]|sb|bcax|eor3|rax1|xar|sha512(h|h2|su0|su1)|sm3.*|sm4.*|bfcvtn?2?|bfdot|bfmmla|bfmlal[bt]|[su]s?mmla|usdot|sudot|ld64b|st64bv?0?' "$W/mnemonics.txt" || true)
	if [ "$bad" != 0 ]; then echo "result FAILED (ISA check: $bad instructions)" > "$OUT/BUILD.txt"; die "ISA CHECK FAILED: $bad instructions newer than armv8.2"; fi
	printf 'decoded %s\nforbidden %s\nobjdump %s\n' "$decoded" "$bad" "$OBJDUMP" > "$OUT/ISA.txt"
	rm -f "$W/disassembly.txt" "$W/mnemonics.txt"
	say "ISA check ok ($decoded instructions)"
else
	die "no llvm-objdump for required ISA check"
fi

# ---- 6. 與 CI 相同的後處理 ----
( cd "$S" || exit 1
  rm -rf "$OUT/iig-pregen"
  python3 tools/xnu-iig-cache.py --prepare "$X/xnu" "$X/build" "$OUT/iig-pregen" || exit 1
  python3 tools/xnu-iig-cache.py --verify "$X/xnu" "$OUT/iig-pregen" || exit 1
  cmp "$XNU_IIG_CACHE/manifest.json" "$OUT/iig-pregen/manifest.json" || exit 1
  if [ -n "${FUXI_ATH12K_OBJECT:-}" ]; then
	FUXI_LOCAL_NM=$(command -v llvm-nm) || exit 1
	python3 tools/ci/ath12k-link.py "$(dirname "$FUXI_ATH12K_OBJECT")" \
		--kernel "$OUT/kernel.development.fuxi.unstripped" --nm "$FUXI_LOCAL_NM" --output "$OUT/ath12k-link.json" || exit 1
  fi
  python3 tools/ci/kernel-inputs.py --variant metal4 --out "$OUT" ) > "$OUT/logs/kernel-inputs.log" 2>&1 ||
	{ tail -20 "$OUT/logs/kernel-inputs.log"; echo "result FAILED (kernel-inputs)" > "$OUT/BUILD.txt"; die "kernel-inputs.py"; }
T3=$(date +%s)
{ echo "result ok"; echo "name $NAME"; echo "ram $RAM"; echo "source $KSRC_SHA"
  echo "seconds total=$((T3 - T0)) make=$((T2 - T1))"; echo "built $(date -u +%Y-%m-%dT%H:%M:%SZ) local-wsl (not a CI artifact)"; } > "$OUT/BUILD.txt"
rm -f "$OUT/errors.txt" "$OUT/errors-context.txt" "$OUT/tail.txt"
python3 - "$OUT" <<'PY' || die "SHA256SUMS"
import hashlib
from pathlib import Path
import sys
out = Path(sys.argv[1])
files = sorted(p for p in out.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
(out / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.relative_to(out).as_posix() + '\n' for p in files))
PY
say "kernel ok in $((T3 - T0)) s (make $((T2 - T1)) s): $OUT"
ls -la "$OUT" | sed -n '1,30p'
