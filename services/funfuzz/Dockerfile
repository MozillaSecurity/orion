FROM mozillasecurity/fuzzos:latest

LABEL maintainer Gary Kwong <gkwong@mozilla.com>
WORKDIR /home/worker/funfuzz

USER root
COPY recipes /tmp/recipes
RUN /tmp/recipes/install_prerequisites.sh \
    && rm -rf /tmp/recipes/install_prerequisites.sh \
    && chown -R worker:worker /home/worker

ENV USER      worker
ENV HOME      /home/worker
ENV LOGNAME   worker
ENV HOSTNAME  worker
ENV LANG      en_US.UTF-8
ENV LC_ALL    en_US.UTF-8

USER $USER
COPY setup.sh $HOME
RUN $HOME/setup.sh
ENTRYPOINT ["/bin/bash", "--login"]
