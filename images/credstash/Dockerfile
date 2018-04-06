FROM alpine:latest

LABEL maintainer Jesse Schwartzentruber <truber@mozilla.com>

RUN apk add --no-cache python \
    && apk add --no-cache --virtual build-deps build-base libressl-dev libffi-dev python-dev py-pip \
    && pip --disable-pip-version-check --no-cache-dir install credstash \
    && apk del build-deps

ENTRYPOINT ["python", "-m", "credstash"]
