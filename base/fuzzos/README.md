![Logo](https://github.com/posidron/posidron.github.io/raw/master/static/images/fuzzos.png)

[![](https://images.microbadger.com/badges/image/mozillasecurity/fuzzos.svg)](https://microbadger.com/images/mozillasecurity/fuzzos "Get your own image badge on microbadger.com")

## OS

OS: Ubuntu 18.04

## Pre-Installed Packages

- credstash
- fuzzfetch
- fuzzmanager
- afl
- honggfuzz
- llvm
- breakpad
- rr
- grcov
- ripgrep
- nodejs


## Run

```bash
docker search fuzzos
docker run -it --rm mozillasecurity/fuzzos:latest bash -li
```
