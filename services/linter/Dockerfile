FROM alpine:latest

LABEL maintainer Christoph Diehl <cdiehl@mozilla.com>

RUN apk --no-cache add \
    curl \
    && HADOLINT_VERSION=$( \
        curl -sL 'https://api.github.com/repos/hadolint/hadolint/releases/latest' \
        | grep '"tag_name":' \
        | sed -E 's/.*"([^"]+)".*/\1/' \
        ) \
    && curl -sL -o /bin/hadolint "https://github.com/hadolint/hadolint/releases/download/$HADOLINT_VERSION/hadolint-Linux-x86_64" \
    && chmod +x /bin/hadolint \
    && curl -sL https://storage.googleapis.com/shellcheck/shellcheck-latest.linux.x86_64.tar.xz \
       | tar -xJ \
    && mv shellcheck-latest/shellcheck /bin/shellcheck \
    && rm -rf shellcheck-latest

WORKDIR /mnt

CMD ["/bin/bash"]
