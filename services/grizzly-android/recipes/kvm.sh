#!/bin/bash -ex
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

if [ ! -e /dev/kvm ]
then
    mknod /dev/kvm c 10 "$(grep '\<kvm\>' /proc/misc | cut -f 1 -d' ')"
fi

chgrp kvm /dev/kvm
chmod 0660 /dev/kvm
