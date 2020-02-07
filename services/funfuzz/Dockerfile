# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

FROM mozillasecurity/fuzzos:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>
WORKDIR /home/worker/funfuzz

USER root
COPY recipes /tmp/recipes

RUN /tmp/recipes/install_prerequisites.sh \
    && rm -f /tmp/recipes/install_prerequisites.sh \
    && chown -R worker:worker /home/worker

ENV USER      worker
ENV HOME      /home/worker
ENV LOGNAME   worker
ENV HOSTNAME  worker
ENV LANG      en_US.UTF-8
ENV LC_ALL    en_US.UTF-8

ENV PATH="${HOME}/.cargo/bin:${HOME}/.local/bin:${PATH}"
ENV LD_LIBRARY_PATH=.
ENV ASAN_SYMBOLIZER_PATH=/usr/bin/llvm-symbolizer

# Expand bash shell history length
ENV HISTTIMEFORMAT="%h %d %H:%M:%S "
ENV HISTSIZE=10000
# Modify bash prompt
ENV PS1="[\u@\h \d \t \W ] $ "

USER $USER
COPY setup.sh $HOME
RUN "$HOME/setup.sh"

USER root
RUN "$HOME/.bin/cleanup.sh"

USER $USER
ENTRYPOINT ["/bin/bash", "--login"]
