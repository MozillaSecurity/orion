# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

echo "[!] executing stage2.sh (as user)" | ./hcat

echo "[!] agent is running on the following OS:" | ./hcat
lsb_release -a | ./hcat
uname -a | ./hcat

echo "[!] requesting firefox from hypervisor" | ./hcat
./hget ff_files.sh ff_files.sh
sh ff_files.sh

echo "[!] requesting config.sh" | ./hcat
./hget config.sh config.sh
. ./config.sh

echo "[!] NYX_FUZZER: $NYX_FUZZER" | ./hcat
if [ "$(expr "$NYX_FUZZER" : '^Domino')" -gt 0 ]
then
  echo "[!] requesting extra files from hypervisor" | ./hcat
  ./hget ext_files.sh ext_files.sh
  sh ext_files.sh
fi

if [ -n "$MOCHITEST_ARGS" ]
then
  echo "[!] requesting testenv.txz from hypervisor" | ./hcat
  ./hget_bulk testenv.txz testenv.txz
  echo "[!] requesting tools.txz from hypervisor" | ./hcat
  ./hget_bulk tools.txz tools.txz
  echo "[!] unpacking testenv.txz" | ./hcat
  tar xf testenv.txz
  echo "[!] unpacking tools.txz" | ./hcat
  tar xf tools.txz -C tests/bin/
elif [ "$(expr "$NYX_FUZZER" : '^Domino')" -gt 0 ]
then
  cat >> fuzz.html << EOF
<!DOCTYPE html>
<meta http-equiv="refresh" content="0; url=http://localhost:8080/nyx_landing.html">
EOF
else
  echo "[!] requesting ${NYX_PAGE-page.zip} from hypervisor" | ./hcat
  ./hget_bulk "${NYX_PAGE-page.zip}" page.zip
  echo "[!] unpacking ${NYX_PAGE-page.zip}" | ./hcat
  unzip "${NYX_PAGE-page.zip}" | ./hcat
  ln -s "${NYX_PAGE_HTMLNAME-caniuse.html}" fuzz.html
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
export MOZ_FUZZ_COVERAGE="${COVERAGE}"

echo "[!] Creating firefox profile" | ./hcat
./hget prefs.js prefs.js
LD_LIBRARY_PATH="/home/user/firefox" \
/home/user/firefox/firefox-bin -CreateProfile test 2>&1 | ./hcat
mv prefs.js /home/user/.mozilla/firefox/*test/

if [ "$(expr "$NYX_FUZZER" : '^Domino')" -gt 0 ]
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
ASAN_OPTIONS="${ASAN_OPTIONS}" \
UBSAN_OPTIONS="${UBSAN_OPTIONS}" \
xvfb-run ./launch.sh /home/user/firefox/firefox-bin -P test --new-window "file:///home/user/fuzz.html" 2>&1 | ./hcat

echo "[!] Debug output:" | ./hcat
cat /tmp/data.log* | ./hcat
echo "[!] Debug output end" | ./hcat

./hrelease
