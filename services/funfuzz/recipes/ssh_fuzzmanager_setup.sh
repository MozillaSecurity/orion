#!/bin/bash -ex

# shellcheck disable=SC1090
source ~/.common.sh

eval "$(ssh-agent -s)"
mkdir -p .ssh
retry ssh-keyscan github.com >> .ssh/known_hosts

# Figure this out before deployment
# # Get deployment keys from credstash
# if [[ -f "$HOME/.aws/credentials" ]]
# then
#   retry credstash get funfuzz-gkw-key > .ssh/gkwAWSFuzz.pem
#   chmod 0600 .ssh/gkwAWSFuzz.pem
#   retry credstash get awsm-gkw-key > .ssh/id_rsa.fuzz
#   chmod 0600 .ssh/id_rsa.fuzz
# fi

# # Get FuzzManager configuration from credstash.
# # We require FuzzManager credentials in order to submit our results.
# if [[ ! -f "$HOME/.fuzzmanagerconf" ]]
# then
#   retry credstash get fuzzmanagerconf > .fuzzmanagerconf
# fi

# Update FuzzManager config for this instance.
mkdir -p sigcache
cat >> .fuzzmanagerconf << EOF
sigdir = $HOME/sigcache
tool = funfuzz
EOF

# Setup Additional Key Identities
cat << EOF >> .ssh/config
Host *
StrictHostKeyChecking no

Host funfuzz
HostName github.com
IdentitiesOnly yes
IdentityFile ~/.ssh/gkwAWSFuzz.pem

Host framagit.org
IdentityFile ~/.ssh/id_rsa.fuzz
User nth10sd
EOF
