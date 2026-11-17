#!/system/bin/sh
# 小米 13（fuxi）雙系統：檢查無誤後切到 b 槽重開進 iOS。
# b 槽的 boot 是「分流器」：一般開機 -> iOS；recovery 開機（電源＋音量上）-> Android 核心 -> TWRP。
# 回 Android：在 iOS 按住 電源＋音量上 重開進 TWRP，選 Reboot -> Slot A，再 Reboot System。
# iOS 卡死時：同時長按 電源＋音量下 約 7 秒（暖重置），放開後立刻按住 電源＋音量上 進 TWRP。
case "$0" in */*) MODDIR=${0%/*} ;; *) MODDIR=. ;; esac
chmod 755 "$MODDIR"/bin/* 2>/dev/null
IMG=/data/gsi/codexnative1108b/codexnative_root_1108b.img.0000
DM=/dev/block/mapper/codexnative_root_1108b

fail() {
    echo "✗ $*"
    echo "沒有切換，手機仍在 Android。"
    exit 1
}

echo "[1/5] 檢查目前槽位"
[ "$(getprop ro.boot.slot_suffix)" = "_a" ] || fail "目前不在 a 槽（$(getprop ro.boot.slot_suffix)）"

echo "[2/5] 檢查 iOS 映像的區塊位置"
[ -e "$DM" ] && fail "iOS 映像目前被 Android 對應著（$DM 存在），先解除再試"
cur=$("$MODDIR/bin/inspect-fiemap" "$IMG") || fail "讀不到 iOS 映像的區塊表"
[ "$cur" = "$(cat "$MODDIR/expected-fiemap.txt")" ] || fail "iOS 映像的區塊位置與 loader 內建的不同（映像被移動或換過），不能開機"
pin=$("$MODDIR/bin/check-pin" "$IMG")
case "$pin" in
    *"flags_rc=0 flags=0x800000 "*"pin_rc=0 moved=0 "*) ;;
    *) fail "iOS 映像沒有固定（pin）：$pin" ;;
esac

echo "[3/5] 檢查 b 槽的分流器與 TWRP"
size=$(cat "$MODDIR/loader.size")
want=$(cat "$MODDIR/loader.sha256")
got=$(head -c "$size" /dev/block/by-name/boot_b | sha256sum | cut -d' ' -f1)
[ "$got" = "$want" ] || fail "boot_b 不是預期的分流器（sha256 $got）"
rec=$(sha256sum /dev/block/by-name/recovery_b | cut -d' ' -f1)
[ "$rec" = "$(cat "$MODDIR/twrp.sha256")" ] || fail "recovery_b 不是預期的 TWRP，切過去會回不來"

echo "[4/5] 切換到 b 槽"
bootctl set-active-boot-slot 1 || fail "切換槽位失敗"
[ "$(bootctl get-active-boot-slot 2>/dev/null)" = "1" ] || echo "（提醒：無法讀回 active slot，繼續）"

echo "[5/5] 3 秒後重開進雙系統選單（音量鍵選擇，短按電源確認）"
echo "回 Android：電源＋音量上 進 TWRP -> Reboot -> Slot A -> Reboot System"
sleep 3
sync
reboot
