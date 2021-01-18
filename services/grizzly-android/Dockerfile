# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozillasecurity/grizzly:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

USER root

COPY services/grizzly-android/recipes/ /tmp/recipes/
RUN /tmp/recipes/setup.sh \
    && rm -rf /tmp/recipes
COPY services/grizzly-android/recipes/kvm.sh /home/worker/

COPY services/grizzly-android/android-x86_64-llvm-symbolizer \
    /home/worker/android-ndk/prebuilt/android-x86_64/llvm-symbolizer/llvm-symbolizer
RUN chown -R worker:worker /home/worker/android-ndk

CMD ["/bin/sh", "-c", "/home/worker/kvm.sh && /home/worker/launch-grizzly.sh"]
