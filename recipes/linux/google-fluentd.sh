#!/usr/bin/env bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

set -e
set -x
set -o pipefail

# shellcheck source=recipes/linux/common.sh
source "${0%/*}/common.sh"

#### Install Google fluentd logging agent

# adapted from https://dl.google.com/cloudagents/add-logging-agent-repo.sh
# but that script pulls in some extra stuff via recommends

apt-install-auto \
    curl \
    ca-certificates \
    gpg \
    gpg-agent \
    lsb-release \
    patch

REPO_HOST='packages.cloud.google.com'
CODENAME="${REPO_CODENAME:-"$(lsb_release -sc)"}"
REPO_SUFFIX=all
REPO_NAME="google-cloud-logging-${CODENAME}${REPO_SUFFIX+-${REPO_SUFFIX}}"

cat > /etc/apt/sources.list.d/google-cloud-logging.list << EOF
deb https://${REPO_HOST}/apt ${REPO_NAME} main
EOF
curl --retry 5 -sS "https://${REPO_HOST}/apt/doc/apt-key.gpg" | apt-key add -

sys-update
sys-embed \
    google-fluentd \
    google-fluentd-catch-all-config-structured

patch /etc/init.d/google-fluentd << "EOF"
--- a/google-fluentd 2020-04-16 20:54:12.679872143 +0000
+++ b/google-fluentd 2020-04-16 20:55:14.823208241 +0000
@@ -113,1 +111,4 @@
 do_start() {
+  # Assert the log path exists
+  mkdir -p "$(dirname "$TD_AGENT_LOG_FILE")"
+
EOF
