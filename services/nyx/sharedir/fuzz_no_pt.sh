# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

echo "[!] executing fuzz.sh" | ./hcat
chmod +x hget
echo 0 > /proc/sys/kernel/randomize_va_space
echo 0 > /proc/sys/kernel/printk

#echo 2 > /proc/sys/vm/overcommit_memory
#echo 1 > /proc/sys/vm/panic_on_oom

echo "[!] requesting htools from hypervisor" | ./hcat
./hget htools/hcat_no_pt hcat
./hget htools/habort_no_pt habort
./hget htools/hpush_no_pt hpush
./hget htools/hget_bulk_no_pt hget_bulk
./hget htools/hrelease_no_pt hrelease

echo "[!] requesting agent & setup scripts from hypervisor" | ./hcat
./hget stage2.sh stage2.sh
./hget ld_preload_fuzz_no_pt.so ld_preload_fuzz.so

echo "[!] setting permissions" | ./hcat
chmod +x hget_bulk
chmod +x hcat
chmod +x habort
chmod +x hpush
chmod +x hrelease
chmod +x ld_preload_fuzz.so
chmod +x stage2.sh
chown user hget
chown user hcat
chown user habort
chown user hpush
chown user hrelease
chown user ld_preload_fuzz.so
chown user fuzz.sh
chown user stage2.sh

echo "[!] switching user (root -> user)" | ./hcat
su user -c "sh stage2.sh"

sleep 200000000
