#!/usr/bin/env -S bash -l
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

pushd /srv/repos/ipc-research/ipc-fuzzing/userspace-tools >/dev/null
sed -i 's,^QEMU_PT_BIN.*,QEMU_PT_BIN=/srv/repos/AFLplusplus/nyx_mode/QEMU-Nyx/x86_64-softmmu/qemu-system-x86_64,' qemu_tool.sh
if ! grep -q '127\.0\.0\.1:55555' qemu_tool.sh; then
  sed -i 's/-vnc/-monitor tcp:127.0.0.1:55555,server,nowait -vnc/' qemu_tool.sh
fi
touch config.sh
qemu-cmd () {
  set +x
  echo "$@" | nc -N 127.0.0.1 55555 >/dev/null
  set -x
}
gen-qemu-sendkeys () {
  set +x
  echo -n "$@" | while read -r -n1 letter; do
    case "$letter" in
      "")
        echo "spc"
        ;;
      "/")
        echo "shift-7"
        ;;
      '"')
        echo "shift-2"
        ;;
      "-")
        echo "slash"
        ;;
      ";")
        echo "shift-comma"
        ;;
      *)
        echo "$letter"
        ;;
    esac
  done | while read -r key; do
    echo "sendkey $key"
  done
  echo "sendkey ret"
  echo ""
  set -x
}

./qemu_tool.sh create_snapshot ~/firefox.img 6144 ~/snapshot &
sleep 120
qemu-cmd "sendkey alt-f2"
sleep 30
qemu-cmd "$(gen-qemu-sendkeys gnome-terminal)"
sleep 60
qemu-cmd "$(gen-qemu-sendkeys "sudo screen -d -m bash -c \"sleep 5; /home/user/loader\"; exit")"
sleep 90
qemu-cmd "$(gen-qemu-sendkeys user)"
wait
popd >/dev/null
