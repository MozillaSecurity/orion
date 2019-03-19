FROM alpine:latest AS builder

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

RUN apk --no-cache add \
        python3 \
    && apk --no-cache add \
        build-base \
        libressl-dev \
        libffi-dev \
        python3-dev \
    && pip3 install --upgrade pip wheel \
    && pip3 wheel --wheel-dir=/root/wheels credstash

FROM alpine:latest

COPY --from=builder /root/wheels /root/wheels

RUN apk add --no-cache python3 libressl \
    && pip3 install --no-index --find-links=/root/wheels credstash \
    && rm -rf /root/wheels \
    && python3 -m compileall -b -q /usr/lib \
    && find /usr/lib -name \*.py -delete \
    && find /usr/lib -name __pycache__ -exec rm -rf \{\} +

ENTRYPOINT ["python3", "-m", "credstash"]
