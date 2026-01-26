#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
set -euo pipefail

echo "[!] executing stage2.sh (as user)"

echo "[!] agent is running on the following OS:"
lsb_release -a
uname -a

echo "[!] requesting firefox from hypervisor"
./hget ff_files.sh ff_files.sh
bash ff_files.sh
df -h

echo "[!] requesting config.sh"
./hget config.sh config.sh
set -x
source ./config.sh
set +x

echo "[!] requesting session.sh"
./hget session.sh session.sh
set -x
source ./session.sh
set +x

echo "[!] NYX_FUZZER: $NYX_FUZZER"
if [[ $NYX_FUZZER == Domino* ]]; then
  echo "[!] requesting extra files from hypervisor"
  ./hget nyx-server.py nyx-server.py
  echo "[!] starting domino replay server"
  python3 nyx-server.py &
fi

if [[ -n ${__AFL_PC_FILTER:-} ]]; then
  echo "[!] enabling afl symbol filtering"
  ./hget target.symbols.txt target.symbols.txt
  export AFL_PC_FILTER_FILE=/home/user/target.symbols.txt
fi

if [[ -n ${MOCHITEST_ARGS:-} ]]; then
  echo "[!] requesting testenv.txz from hypervisor"
  ./hget_bulk testenv.txz testenv.txz
  echo "[!] requesting tools.txz from hypervisor"
  ./hget_bulk tools.txz tools.txz
  echo "[!] unpacking testenv.txz"
  tar xf testenv.txz
  echo "[!] unpacking tools.txz"
  tar xf tools.txz -C tests/bin/
elif [[ $NYX_FUZZER == Domino* ]]; then
  cat >fuzz.html <<EOF
<!DOCTYPE html>
<meta http-equiv="refresh" content="0; url=http://localhost:8080/nyx_landing.html">
EOF
else
  zip_name="${NYX_PAGE:-page.zip}"
  html_name="${NYX_PAGE_HTMLNAME:-caniuse.html}"
  echo "[!] requesting $zip_name from hypervisor"
  ./hget_bulk "$zip_name" page.zip
  echo "[!] unpacking $zip_name"
  unzip "$zip_name"
  ln -s "$html_name" fuzz.html
fi

echo "[!] agent is running in the following path:"
pwd

echo "[!] locking all files in /home/user/ into memory"
vmtouch -t /home/user/
vmtouch -dl /home/user/

free -m

export AFL_MAP_SIZE=8388608
export AFL_IGNORE_PROBLEMS=1
export AFL_IGNORE_PROBLEMS_COVERAGE=1
export AFL_DEBUG=1

echo "[!] creating firefox profile"
./hget prefs.js prefs.js
mkdir -p /home/user/.mozilla/firefox
LD_LIBRARY_PATH="/home/user/firefox" \
  xvfb-run /home/user/firefox/firefox-bin -CreateProfile test
mv prefs.js /home/user/.mozilla/firefox/*test/

echo "[!] starting firefox"
./hget launch.sh launch.sh
chmod +x launch.sh
export LIBGL_ALWAYS_SOFTWARE=1
export MOZ_FUZZ_LOG_IPC=1
export NYX_AFL_PLUS_PLUS_MODE=ON
export NYX_ASAN_EXECUTABLE=TRUE
export NYX_NET_FUZZ_MODE=ON
xvfb-run ./launch.sh /home/user/firefox/firefox-bin -P test --new-window "file:///home/user/fuzz.html"

echo "[!] debug output:"
cat /tmp/data.log*
echo "[!] debug output end"

./hrelease
