FROM python:3.8-slim

ENV DEBIAN_FRONTEND=noninteractive

# Setup git for ssh clones
# Setup gcc to build patiencediff
RUN apt-get update -qq && apt-get install --no-install-recommends -qq gcc libc6-dev git openssh-client && rm -rf /var/lib/apt/lists/*
RUN mkdir ~/.ssh && chmod 0700 ~/.ssh && ssh-keyscan github.com > ~/.ssh/known_hosts

COPY services/fuzzing-decision /src

RUN pip install --disable-pip-version-check --no-cache-dir --progress-bar off --quiet -e "/src[decision]"

# Setup env variable for tc-admin.py discovery
ENV TC_ADMIN_PY=/src/tc-admin.py

CMD ["fuzzing-decision"]
