#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
set -euo pipefail

echo "[!] executing stage2.sh (as user)" | ./hcat

echo "[!] agent is running on the following OS:" | ./hcat
lsb_release -a | ./hcat
uname -a | ./hcat

echo "[!] requesting firefox from hypervisor" | ./hcat
./hget ff_files.sh ff_files.sh
bash ff_files.sh

echo "[!] requesting config.sh" | ./hcat
./hget config.sh config.sh
source ./config.sh

echo "[!] NYX_FUZZER: $NYX_FUZZER" | ./hcat
if [[ $NYX_FUZZER == Domino* ]]
then
  echo "[!] requesting extra files from hypervisor" | ./hcat
  ./hget ext_files.sh ext_files.sh
  bash ext_files.sh
fi

if [[ -n ${__AFL_PC_FILTER:-} ]]
then
  echo "[!] enabling afl symbol filtering" | ./hcat
  ./hget target.symbols.txt target.symbols.txt
  export AFL_PC_FILTER_FILE=/home/user/target.symbols.txt
fi

if [[ -n ${MOCHITEST_ARGS:-} ]]
then
  echo "[!] requesting testenv.txz from hypervisor" | ./hcat
  ./hget_bulk testenv.txz testenv.txz
  echo "[!] requesting tools.txz from hypervisor" | ./hcat
  ./hget_bulk tools.txz tools.txz
  echo "[!] unpacking testenv.txz" | ./hcat
  tar xf testenv.txz
  echo "[!] unpacking tools.txz" | ./hcat
  tar xf tools.txz -C tests/bin/
elif [[ $NYX_FUZZER == Domino* ]]
then
  cat > fuzz.html <<EOF
<!DOCTYPE html>
<meta http-equiv="refresh" content="0; url=http://localhost:8080/nyx_landing.html">
EOF
else
  zip_name="${NYX_PAGE:-page.zip}"
  html_name="${NYX_PAGE_HTMLNAME:-caniuse.html}"
  echo "[!] requesting $zip_name from hypervisor" | ./hcat
  ./hget_bulk "$zip_name" page.zip
  echo "[!] unpacking $zip_name" | ./hcat
  unzip "$zip_name" | ./hcat
  ln -s "$html_name" fuzz.html
fi

echo "[!] agent is running in the following path:" | ./hcat
pwd | ./hcat

echo "[!] locking all files in /home/user/ into memory" | ./hcat
vmtouch -t /home/user/
vmtouch -dl /home/user/

free -m

export AFL_MAP_SIZE=8388608
export AFL_IGNORE_PROBLEMS=1
export AFL_IGNORE_PROBLEMS_COVERAGE=1
export AFL_DEBUG=1
export MOZ_FUZZ_COVERAGE="${COVERAGE:-}"

echo "[!] Creating firefox profile" | ./hcat
./hget prefs.js prefs.js
LD_LIBRARY_PATH="/home/user/firefox" \
xvfb-run /home/user/firefox/firefox-bin -CreateProfile test 2>&1 | ./hcat
mv prefs.js /home/user/.mozilla/firefox/*test/

if [[ $NYX_FUZZER == Domino* ]]
then
  echo "[!] starting domino web service ($STRATEGY)" | ./hcat
  node /home/user/domino/lib/bin/server.js --is-nyx --strategy "$STRATEGY" &
fi

echo "[!] starting firefox" | ./hcat
./hget launch.sh launch.sh
chmod +x launch.sh
export LIBGL_ALWAYS_SOFTWARE=1
export MOZ_FUZZ_LOG_IPC=1
export NYX_AFL_PLUS_PLUS_MODE=ON
export NYX_ASAN_EXECUTABLE=TRUE
export NYX_NET_FUZZ_MODE=ON
ASAN_OPTIONS="${ASAN_OPTIONS:-}" \
UBSAN_OPTIONS="${UBSAN_OPTIONS:-}" \
xvfb-run ./launch.sh /home/user/firefox/firefox-bin -P test --new-window "file:///home/user/fuzz.html" 2>&1 | ./hcat

echo "[!] Debug output:" | ./hcat
cat /tmp/data.log* | ./hcat
echo "[!] Debug output end" | ./hcat

./hrelease
