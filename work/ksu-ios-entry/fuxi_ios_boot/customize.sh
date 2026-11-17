SKIPUNZIP=0
# 安裝時給 bin 內的檢查工具執行權限（zip 內的權限不會被保留）
set_perm_recursive "$MODPATH/bin" 0 0 0755 0755
set_perm "$MODPATH/action.sh" 0 0 0755
