#!/bin/bash -ex
if [ ! -e /dev/kvm ]
then
    mknod /dev/kvm c 10 "$(grep '\<kvm\>' /proc/misc | cut -f 1 -d' ')"
fi

chgrp kvm /dev/kvm
chmod 0660 /dev/kvm
