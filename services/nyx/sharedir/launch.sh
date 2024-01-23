#!/bin/sh
LD_LIBRARY_PATH="/home/user/firefox" \
LD_BIND_NOW=1 \
LD_PRELOAD=./ld_preload_fuzz.so \
"$@"
echo "[!] firefox returned $?"
