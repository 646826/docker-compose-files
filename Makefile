SHELL := /bin/sh
COMPOSE ?= docker compose
DEFAULT_PROFILES := --profile monitoring --profile tools
ALL_PROFILES := --profile monitoring --profile tools --profile iot --profile netdata --profile test

.DEFAULT_GOAL := help

.PHONY: help init check config core up full monitoring netdata tools iot k6 pull ps logs down

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

init: ## Create .env and missing local secrets without overwriting existing values
	@./scripts/init.sh

check: ## Validate static files, bootstrap behavior, shell scripts, and the full Compose model
	@./scripts/check.sh

config: init ## Print the fully rendered Compose model for every profile
	@$(COMPOSE) --env-file .env $(ALL_PROFILES) config

core: init ## Start Traefik, Docker socket proxy, and whoami
	@$(COMPOSE) up -d

up: init ## Start the legacy-equivalent stack: core, monitoring, and Portainer
	@$(COMPOSE) $(DEFAULT_PROFILES) up -d

full: init ## Start every persistent service, including Netdata, Mosquitto, and openHAB
	@$(COMPOSE) --profile monitoring --profile tools --profile iot --profile netdata up -d

monitoring: init ## Start core plus InfluxDB, Telegraf, and Grafana
	@$(COMPOSE) --profile monitoring up -d

netdata: init ## Start full host monitoring without changing the rest of the stack
	@$(COMPOSE) --profile netdata up -d netdata

tools: init ## Start core plus Portainer
	@$(COMPOSE) --profile tools up -d

iot: init ## Start core plus Mosquitto and openHAB
	@$(COMPOSE) --profile iot up -d

k6: init ## Run the bounded k6 smoke test against K6_TARGET_URL
	@$(COMPOSE) up -d whoami
	@$(COMPOSE) --profile test run --rm k6

pull: init ## Pull every explicitly selected image version
	@$(COMPOSE) $(ALL_PROFILES) pull

ps: init ## Show containers from every profile
	@$(COMPOSE) $(ALL_PROFILES) ps

logs: init ## Follow logs from every profile
	@$(COMPOSE) $(ALL_PROFILES) logs --tail=200 -f

down: ## Stop this project and preserve all named volumes
	@$(COMPOSE) $(ALL_PROFILES) down --remove-orphans
