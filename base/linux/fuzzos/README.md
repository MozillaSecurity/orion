![Logo](https://github.com/posidron/posidron.github.io/raw/master/static/images/fuzzos.png)

[![](https://images.microbadger.com/badges/image/mozillasecurity/fuzzos.svg)](https://microbadger.com/images/mozillasecurity/fuzzos)

## OS

```
Distributor ID:	Ubuntu
Description:	  Ubuntu 18.04.3 LTS
Release:	      18.04
Codename:	      bionic
```

## Pre-Installed Packages

| Program     | AMD64 | ARM64 |
| ----------- | ----- | ----- |
| berglas     | x     | -     |
| breakpad    | x     | x     |
| credstash   | x     | x     |
| fuzzfetch   | x     | x     |
| fuzzmanager | x     | x     |
| git         | x     | x     |
| grcov       | x     | x     |
| halfempty   | x     | x     |
| honggfuzz   | x     | x     |
| llvm        | x     | x     |
| node        | x     | x     |
| python      | x     | x     |
| ripgrep     | x     | x     |
| rr          | x     | -     |

## Run

```bash
docker search fuzzos
docker run -it --rm mozillasecurity/fuzzos:latest bash -li
```
