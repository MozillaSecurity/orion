# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozillasecurity/grizzly:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

USER root

COPY \
    services/grizzly-android/setup.sh \
    /src/recipes/setup-grizzly-android.sh
RUN /src/recipes/setup-grizzly-android.sh
