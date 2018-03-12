# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
ID = fuzzos
NAME = taskclusterprivate/$(ID)
TAG = $$(git rev-parse --short HEAD)
IMG = $(NAME):$(TAG)
LATEST = $(NAME):latest

.PHONY: build push clean login help

build: ## Build FuzzOS image.
	docker build --no-cache --squash --compress -t $(IMG) -t $(LATEST) .

run: ## Run FuzzOS container.
	docker run -it --rm $(LATEST) bash -li

push: ## Push built image to repository.
	docker push $(NAME)

clean: ## Clean local images and containers of FuzzOS.
	docker images -a | grep $(NAME) | awk '{print $3}' | xargs docker rmi -f
	docker ps -a | grep $(ID) | awk '{print $1}' | xargs docker rm -f

debug: ## Run FuzzOS container with root privileges.
	docker run -u 0 --entrypoint=/bin/bash -it --rm $(LATEST)

login:
	docker log -u $(DOCKER_USER) -p $(DOCKER_PASS)

help: ## Show this help message.
	@echo 'Usage: make [command] ...'
	@echo
	@echo "Available commands:"
	@grep -E "^(.+)\:\ ##\ (.+)" ${MAKEFILE_LIST} | column -t -c 2 -s ":#"

default: build
