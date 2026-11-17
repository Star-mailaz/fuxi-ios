#!/usr/bin/env bash
# 000 線狀態欄上機：拉回手機現況（同時是還原點）→ 主機疊加層裡只加一個 UIKit 偏好鍵 → 只把改到的幾個區塊寫回 → 巡覽截圖開機。
#   1. 等 hw000-chain-1.sh 跑完（ALL_DONE）、沒有其他手機工作、Android 穩定 1 分鐘
#   2. 佔用手機：PHONE-LOCK-000（＋HOLD-PHONE，不存在才建，結束只刪自己建的）
#   3. 還原點：hw000-delta-backup.py 只讀拉回現況，存成相對 native-layout0043-root.img 的差異（fuxi_Backup\ios-root-hw000sb-日期）
#   4. 主機：qcow2 疊加層（底檔只讀）＋Alpine 客體跑 sb-guest.sh（套差異→驗證＝手機現況→stage-statusbar.sh→列出改動區塊）
#   5. 手機：sb-blocks-write.sh 寫前比對、寫後讀回；還原資料放在還原點目錄（statusbar-undo-*）
#   6. 巡覽截圖開機（native-tourl-hyb8s-loader，fastboot boot 暫時開機），回 Android 後釋放手機
# 任何一步失敗就停（並釋放手機）。寫入前失敗＝手機沒被改動。
set -uo pipefail
export MSYS_NO_PATHCONV=1
S=${FUXI_ANDROID_SERIAL:?set FUXI_ANDROID_SERIAL to the adb serial of the phone}
W=/d/xiaomi13/fuxi_ios/work
E=$W/Codex-Xiaomi13-GPU-20261109
H=$W/adsp-battery/hw000
SB=$W/statusbar-fix
LOCK=$W/PHONE-LOCK-000
HOLD=$W/hybrid-driver/HOLD-PHONE
PAUSE=$H/HOLD
J='CLASSPATH=/data/local/tmp/codex-managed-native-image.jar app_process /system/bin ManagedNativeImage'
BASE_WIN='D:\xiaomi13\fuxi_ios\work\images-build\native-layout0043-root.img'
BASE=$W/images-build/native-layout0043-root.img
BASE_SHA=86e55716c6655bf374f7b21706f773d78a3ccea7bfe4bc26fe9ca39311fa71d9
QIMG=/d/xiaomi13/fuxi_ios/candidates/vm-tools/qemu/qemu-img.exe
CLASS=${CLASS:-_UIStatusBarVisualProvider_Split1080}
STAGE_SCRIPT=${STAGE_SCRIPT:-$SB/stage-share/stage-statusbar.sh}
BOOT_LOADER=${BOOT_LOADER:-native-tourl-hyb8s-loader}
BOOT_KERNEL=${BOOT_KERNEL:-kernel-tourl-artifact}
BOOT_SECONDS=${BOOT_SECONDS:-660}
BOOT_VERIFIER=${BOOT_VERIFIER:-verify-args-on-loader-payload.py}
OUT_PREFIX=${OUT_PREFIX:-native-hw000sb-tourl-boot}
BACKUP_PREFIX=${BACKUP_PREFIX:-hw000sb}
PARENT_SNAPSHOT=${PARENT_SNAPSHOT:-}
[[ "$BACKUP_PREFIX" =~ ^[a-z0-9-]+$ ]] || exit 2
[[ "$OUT_PREFIX" =~ ^native-[a-z0-9-]+$ ]] || exit 2
[ -f "$STAGE_SCRIPT" ] && [ -f "$E/$BOOT_LOADER/boot.img" ] || exit 2
[ -z "${SHAPE_DYLIB:-}" ] || [ -f "$SHAPE_DYLIB" ] || exit 2
say() { echo "$(date +%H:%M:%S) $*"; }
su_() { adb -s $S shell "su -c '$1'"; }
others() {
  powershell.exe -NoProfile -Command "@(Get-CimInstance Win32_Process | Where-Object { \$_.Name -notmatch '^(tail|grep|cat|less)\.exe$' -and \$_.CommandLine -notmatch 'Get-CimInstance' -and \$_.CommandLine -match 'chain-00[0-9][0-9]\.sh|post-00[0-9][0-9]\.sh|hw000-chain-1\.sh|run-monitor\.ps1|boot-exp|fuxi-xnu-monitor\.py|pull-phone|deploy-layout|delta-pull|delta-stage|wait-then-pull' }).Count" 2>/dev/null | tr -d '\r'
}
android_up() { [ "$(adb -s $S shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; }
wait_android() {
  local i
  for i in $(seq 1 60); do android_up && return 0; [ $i = 20 ] && (cd $E && python reset-soon.py 1); sleep 10; done
  android_up
}
free_now() { [ ! -e "$HOLD" ] && [ ! -e "$PAUSE" ] && [ ! -e "$LOCK" ] && [ "$(others)" = 0 ] && android_up; }
MADE_HOLD=0
LOCKED=0
release() {
  [ $LOCKED = 1 ] && rm -f "$LOCK"
  [ $MADE_HOLD = 1 ] && rm -f "$HOLD"
  say "PHONE_RELEASED"
}

# ---------- 1. 等第一輪跑完 ----------
deadline=$(( $(date +%s) + 3*3600 ))
if [ "${SKIP_CHAIN1:-0}" = 1 ]; then
  # 2026-11-16 第一輪提早結束（使用者要先做狀態欄）：不等 ALL_DONE，只要第一輪程序已不在
  say "SKIP_CHAIN1 (chain-1 ended early)"
else
  say "WAIT_CHAIN1"
  until grep -q '^chain exit=' $H/hw000-chain-1.log 2>/dev/null; do
    [ $(date +%s) -gt $deadline ] && { say "TIMEOUT waiting for chain-1"; exit 2; }
    sleep 30
  done
  grep -q ' ALL_DONE$' $H/hw000-chain-1.log || { say "STOP: chain-1 did not finish (no ALL_DONE)"; exit 2; }
fi
say "CHAIN1_DONE; WAIT_FREE (others=$(others))"
while :; do
  [ $(date +%s) -gt $deadline ] && { say "TIMEOUT waiting for the phone"; exit 2; }
  if free_now; then
    stable=0
    while [ $stable -lt 3 ]; do
      sleep 20
      if free_now; then stable=$((stable+1)); else stable=-1; break; fi
    done
    [ $stable = 3 ] && break
  fi
  sleep 30
done
echo "000 硬體適配線 statusbar-fix\\hw000-sb-chain.sh pid $$ 自 $(date '+%F %T') 起使用手機（預計約 40 分鐘：拉回→改狀態欄→寫回→巡覽截圖開機），結束自動刪除" > "$LOCK"
LOCKED=1
if [ ! -e "$HOLD" ]; then echo "000 線使用手機中（statusbar-fix\\hw000-sb-chain.sh，見 work\\PHONE-LOCK-000），結束自動刪除" > "$HOLD"; MADE_HOLD=1; fi
trap release EXIT
[ "$(others)" = 0 ] || { say "another phone job started at the last moment"; exit 2; }
say "PHONE_START class=$CLASS"

# ---------- 2. 還原點＝拉回現況 ----------
if [ -n "${REUSE_RP:-}" ]; then
  # 2026-11-16：第一次客體失敗（diff-blocks.txt 的 CR），手機之後一直在 Android、iOS root 沒被動過 → 沿用剛拉的還原點；
  # 寫回前 sb-blocks-write.sh 會逐塊比對寫前雜湊，手機若有變就一塊都不寫
  RP=$REUSE_RP
  [ -f "$RP/pull.bin" ] && [ -f "$RP/diff-blocks.txt" ] && [ -f "$RP/phone-blocks.txt" ] || { say "REUSE_RP incomplete: $RP"; exit 4; }
  RP_WIN="D:\\xiaomi13\\fuxi_Backup\\$(basename "$RP")"
  NAME=${RP##*/ios-root-}
  say "REUSE_RP $RP (no pull)"
else
DAY=$(date +%Y%m%d)
RP=/d/xiaomi13/fuxi_Backup/ios-root-$BACKUP_PREFIX-$DAY
n=0; while [ -e "$RP" ]; do n=$((n+1)); RP=/d/xiaomi13/fuxi_Backup/ios-root-$BACKUP_PREFIX-$DAY-$n; done
RP_WIN="D:\\xiaomi13\\fuxi_Backup\\$(basename "$RP")"
if [ $n = 0 ]; then NAME=$BACKUP_PREFIX-$DAY; else NAME=$BACKUP_PREFIX-$DAY-$n; fi
say "MAP"; su_ "$J map" | tail -1
if ! (cd $E && python 'D:\xiaomi13\fuxi_ios\work\xiaomi13-ios-gpu-20261108\verify-native-map.py' > $SB/verifymap-sb.log 2>&1); then
  tail -5 $SB/verifymap-sb.log; su_ "$J unmap"; say "verify-native-map failed"; exit 4
fi
say "PULL $RP"
parent_options=()
[ -z "$PARENT_SNAPSHOT" ] || parent_options=(--parent-snapshot "$PARENT_SNAPSHOT")
[ "${NTFS_COMPRESS_BACKUP:-0}" != 1 ] || parent_options+=(--ntfs-compress)
if ! (cd $H && python -I hw000-delta-backup.py --backup-base "$BASE_WIN" --backup-base-sha $BASE_SHA \
       --name $NAME --keep-delta "$RP_WIN" "${parent_options[@]}" > $SB/delta-backup-sb.log 2>&1); then
  tail -5 $SB/delta-backup-sb.log; su_ "$J unmap" || true; say "delta backup failed"; exit 4
fi
grep -E 'DIFF|DELTA_KEPT' $SB/delta-backup-sb.log
su_ "sync; $J unmap; $J status" | tail -1
fi
say "RESTORE_POINT_DONE"

# ---------- 3. 主機改狀態欄（手機此時在 Android，可放著） ----------
RUN=$SB/run-$NAME
OVL=$(cygpath -m "$RUN/overlay.qcow2")
if [ "${REUSE_STAGED:-0}" = 1 ] && [ -f "$RUN/sb-list.txt" ] && [ -f "$RUN/sb-new.bin" ] && grep -q '^GUEST_OK' "$RUN/guest.log" 2>/dev/null; then
  # 2026-11-16 01:51：客體已成功、6 塊已取出，但寫回前的檢查把第二輪鏈誤認成別的工作而停；沿用同一份取出結果
  say "REUSE_STAGED $(wc -l < "$RUN/sb-list.txt") blocks"
else
[ ! -e "$RUN" ] || { say "STOP: run directory already exists: $RUN"; exit 5; }
mkdir -p "$RUN/share"
cp "$SB/sb-share-template/sb-guest.sh" "$SB/stage-share/hfs-journal-block-probe.py" "$RUN/share/"
cp "$STAGE_SCRIPT" "$RUN/share/stage-statusbar.sh"
if [ -n "${SHAPE_DYLIB:-}" ]; then
  cp "$SHAPE_DYLIB" "$RUN/share/libfuxi-sb.dylib"
  (cd "$RUN/share" && sha256sum libfuxi-sb.dylib > shape-sha256.txt)
fi
printf '%s\n' "$CLASS" > "$RUN/share/class.txt"
cp "$RP/diff-blocks.txt" "$RP/phone-blocks.txt" "$RUN/share/"
BACKING_WIN=$(cygpath -m "$RUN/phone-snapshot.vmdk")
python -I "$(cygpath -m "$SB/make-snapshot-backing.py")" "$RP_WIN" "$BASE_WIN" "$BACKING_WIN" || { say "snapshot backing failed"; exit 5; }
printf '1\n' > "$RUN/share/restore-preloaded.txt"
"$QIMG" create -q -f qcow2 -b "$BACKING_WIN" -F vmdk "$OVL" || { say "overlay create failed"; exit 5; }
say "GUEST"
# pull.bin（還原點本身）以唯讀 raw 磁碟掛給客體（vdc），不複製
(cd $SB && python sb-guest-run.py "$OVL" "$(cygpath -m "$RUN/share")" sb-guest.sh SB_GUEST_SUCCESS "$RP_WIN\\pull.bin" 34611 > "$RUN/guest.log" 2>&1)
grep -aE 'APPLIED|PHONE_STATE_VERIFIED|PREF_AFTER|FSCK_|CHANGED|NEW_WHOLE|SB_GUEST|GUEST_OK|GUEST_FAILED|Error|assert' "$RUN/guest.log" | tr -d '\r' | head -40
grep -q '^GUEST_OK' "$RUN/guest.log" || { say "STOP: guest failed (phone untouched)"; exit 5; }
(cd $SB && python -I sb-extract.py "$(cygpath -m "$RUN/guest.log")" "$OVL" "$RP_WIN" "$BASE_WIN" "$(cygpath -m "$RUN")") || { say "STOP: extract failed (phone untouched)"; exit 5; }
say "STAGED $(wc -l < "$RUN/sb-list.txt") blocks"
fi

# ---------- 4. 寫回手機 ----------
wait_android || { say "android not back"; exit 7; }
[ "$(others)" = 0 ] || { say "STOP: another phone job appeared (phone untouched)"; exit 6; }
T=/data/local/tmp/codex-sb
su_ "rm -rf $T; mkdir -p $T; chmod 777 $T" >/dev/null
for f in sb-new.bin sb-list.txt; do adb -s $S push "$(cygpath -m "$RUN/$f")" $T/$f >/dev/null || { say "push failed $f"; exit 6; }; done
adb -s $S push "$(cygpath -m "$SB/sb-blocks-write.sh")" $T/sb-blocks-write.sh >/dev/null || { say "push failed script"; exit 6; }
[ "$(su_ "sha256sum $T/sb-new.bin" | tr -d '\r' | cut -d' ' -f1)" = "$(sha256sum "$RUN/sb-new.bin" | cut -d' ' -f1)" ] || { say "push sha mismatch"; exit 6; }
say "MAP2"; su_ "$J map" | tail -1
if ! (cd $E && python 'D:\xiaomi13\fuxi_ios\work\xiaomi13-ios-gpu-20261108\verify-native-map.py' > $SB/verifymap-sb2.log 2>&1); then
  tail -5 $SB/verifymap-sb2.log; su_ "$J unmap"; say "verify-native-map failed (phone untouched)"; exit 6
fi
say "WRITE"
su_ "sh $T/sb-blocks-write.sh $T/sb-list.txt $T/sb-new.bin" 2>&1 | tr -d '\r' | tee "$RUN/write.log"
grep -q '^WRITE_OK' "$RUN/write.log"; wrc=$?
su_ "rm -rf $T; sync; $J unmap; $J status" | tail -1
[ $wrc = 0 ] || { say "STOP: write failed (see write.log; PRE_MISMATCH = nothing written)"; exit 6; }
say "WRITTEN"
rm -f "$RUN/overlay.qcow2"
if [ "${STAGE_ONLY:-0}" = 1 ]; then
  say "STAGE_ALL_DONE $NAME"
  exit 0
fi

# ---------- 5. 巡覽截圖開機 ----------
o=1; while [ -e "$E/$OUT_PREFIX-$o" ] || [ -e "$E/$OUT_PREFIX-$o-exp.log" ]; do o=$((o+1)); done
OUT=$OUT_PREFIX-$o
for try in 1 2; do
  say "BOOT $OUT (try $try)"
  (cd $E && powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'D:\xiaomi13\fuxi_ios\work\Codex-Xiaomi13-GPU-20261109\boot-exp-v.ps1' -Loader "$BOOT_LOADER" -Out "$OUT" \
     -Kernel "$BOOT_KERNEL" -Seconds "$BOOT_SECONDS" -Reset 14 -Verifier "$BOOT_VERIFIER" -TourShots > "$OUT-exp.log" 2>&1)
  say "boot exit $?"
  tr -d '\0' < $E/$OUT-exp.log | grep -E 'boot_time=|boot_completed|lines=|throw|Exception' | tail -4
  { [ -d "$E/$OUT" ] || tr -d '\0' < $E/$OUT-exp.log | grep -q 'boot_time='; } && break
  mv "$E/$OUT-exp.log" "$E/$OUT-exp-failed$try.log"
  wait_android || { say "android not back"; exit 7; }
  sleep 20
done
if ! android_up; then
  say "END_TEST_RESET"
  (cd "$E" && python reset-soon.py 1) || true
fi
wait_android || { say "android not back"; exit 7; }
ls $E/$OUT/framebuffer-shot*.png 2>/dev/null | sed 's#.*/##' | tr '\n' ' '; echo
tr -d '\0' < $E/$OUT/boot.log 2>/dev/null | grep -aE 'overridden status bar|panic\(cpu' | head -5
say "SB_ALL_DONE $OUT"
