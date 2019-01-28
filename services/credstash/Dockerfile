FROM alpine:latest

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

RUN apk add \
        python3 \
    && apk add --virtual \
        build-deps \
        build-base \
        libressl-dev \
        libffi-dev \
        python3-dev \
    && pip3 install --upgrade pip wheel \
    && pip3 wheel --wheel-dir=/root/wheels credstash \
    && apk del build-deps

FROM alpine:latest

COPY --from=0 /root/wheels /root/wheels

RUN apk add --no-cache python3 \
    && pip3 install --no-index --find-links=/root/wheels credstash \ 
    && rm -rf /root/wheels

ENTRYPOINT ["python3", "-m", "credstash"]
