# test-recipes

Tests Linux installation recipes in an isolated Docker environment.

## Overview

Each recipe in `recipes/linux/` is a shell script that installs a tool or
dependency. The test-recipes service builds a Docker image, runs the recipe
inside it, and (for recipes that support it) runs validation tests to confirm
the installation succeeded.

## Adding test support to a recipe

Add a `# supports-test` comment anywhere in the recipe file, then handle the
`test` argument in the recipe's `case` statement:

```bash
#!/usr/bin/env bash
# supports-test

...

case "${1-install}" in
  install)
    # installation steps
    ;;
  test-setup)
    # optional: steps to run before installation during testing
    ;;
  test)
    # validate the installation, e.g.:
    mytool --version
    ;;
esac
```

The `test-setup` case is optional. It runs before installation and is useful
for setting up state that the test step needs to verify.

## Building locally

From the repository root, build with the `recipe` build arg pointing to the
script filename:

```sh
docker build \
  -f services/test-recipes/Dockerfile \
  --build-arg recipe=llvm.sh \
  .
```
