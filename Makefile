# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
ID = fuzzos
NAME = mozillasecurity/$(ID)
TAG = $$(git rev-parse --short HEAD)
IMG = $(NAME):$(TAG)
LATEST = $(NAME):latest

.PHONY: build run push clean debug login ling_scripts lint_dockers lint help

build: ## Build FuzzOS image.
	docker build --no-cache --squash --compress -t $(IMG) -t $(LATEST) .

run: ## Run FuzzOS container.
	docker run -it --rm $(LATEST) bash -li

push: ## Push built image to repository.
	docker push $(IMG)
	docker push $(NAME)

clean: ## Clean local images and containers of FuzzOS.
	docker images -a | grep $(NAME) | awk '{print $3}' | xargs docker rmi -f
	docker ps -a | grep $(ID) | awk '{print $1}' | xargs docker rm -f

debug: ## Run FuzzOS container with root privileges.
	docker run -u 0 --entrypoint=/bin/bash -it --rm $(LATEST)

login: ## Login to Docker Hub
	docker login --username=$(DOCKER_USER)

lint_scripts: ## Lint shellscripts
# Be compatible to MacOS where bash by default is v3.2 and does not support '**/*'
	find . -type f \( -iname "*.bash" -o -iname "*.sh" \) | xargs shellcheck -x -a

lint_dockers: ## Lint Dockerfiles
	find . -type f -name "Dockerfile" | xargs hadolint \
		--ignore DL3002 \
		--ignore DL3003 \
		--ignore DL3007 \
		--ignore DL3008 \
		--ignore DL3013 \
		--ignore DL3018 \
		--ignore DL4001

lint: lint_scripts lint_dockers

help: ## Show this help message.
	@echo 'Usage: make [command] ...'
	@echo
	@echo "Available commands:"
	@grep -E "^(.+)\:\ ##\ (.+)" ${MAKEFILE_LIST} | column -t -c 2 -s ":#"

default: build
