echo "[!] executing stage2.sh (as user)" | ./hcat

echo "[!] agent is running on the following OS:" | ./hcat
lsb_release -a | ./hcat
uname -a | ./hcat

echo "[!] disabling swap" | ./hcat
sudo swapoff -a

echo "[!] requesting firefox from hypervisor" | ./hcat
./hget ff_files.sh ff_files.sh
sh ff_files.sh

echo "[!] requesting page.zip from hypervisor" | ./hcat
./hget_bulk page.zip page.zip
echo "[!] unpacking page.zip" | ./hcat
unzip page.zip | ./hcat
ln -s caniuse.html fuzz.html

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

echo "[!] Creating firefox profile" | ./hcat

LD_LIBRARY_PATH="/home/user/firefox/" \
/home/user/firefox/firefox-bin -CreateProfile test 2>&1 | ./hcat

echo "[!] starting firefox" | ./hcat

mv prefs.js /home/user/.mozilla/firefox/*test/

export MOZ_FUZZ_LOG_IPC=1
export NYX_FUZZER="${NYX_FUZZER}"
export NYX_AFL_PLUS_PLUS_MODE=ON
export NYX_ASAN_EXECUTABLE=TRUE
export NYX_NET_FUZZ_MODE=ON
LD_LIBRARY_PATH="/home/user/firefox/" \
LD_BIND_NOW=1 \
ASAN_OPTIONS="${ASAN_OPTIONS}" \
UBSAN_OPTIONS="${UBSAN_OPTIONS}" \
LD_PRELOAD=./ld_preload_fuzz.so \
/home/user/firefox/firefox-bin -P test --new-window "file:///home/user/fuzz.html" 2>&1 | ./hcat
echo $?

echo "[!] Debug output:" | ./hcat
cat /tmp/data.log* | ./hcat
echo "[!] Debug output end" | ./hcat

./hrelease
