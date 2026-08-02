SHELL := /bin/sh
COMPOSE ?= docker compose
BACKUP_ROOT ?= backups
DEFAULT_PROFILES := --profile monitoring --profile tools
AUTH_PROFILE := $(if $(wildcard .secrets/authelia_configuration.yml),--profile auth,)
ALL_PROFILES := --profile monitoring --profile tools --profile iot --profile netdata --profile test --profile uptime --profile dns --profile dashboard $(AUTH_PROFILE) --profile logs

.DEFAULT_GOAL := help

.PHONY: help init doctor check check-images scan-images sbom check-security check-runtime check-iot-runtime check-optional-runtime check-community-runtime check-auth-runtime backup verify-backup restore check-backup-runtime remote-init remote-backup remote-snapshots verify-remote-backup remote-retention check-remote-backup-runtime config core up full monitoring netdata tools iot uptime dashboard dns-preflight dns auth-init auth-check auth dozzle community k6 pull ps logs down

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

init: ## Create .env and missing established secrets without overwriting existing values
	@./scripts/init.sh

doctor: ## Diagnose Docker, Compose, ports, resources, and local configuration without changing the host
	@python3 scripts/doctor.py

check: ## Validate static files, bootstrap behavior, shell scripts, and the full Compose model
	@./scripts/check.sh

check-images: ## Verify pinned image tags and amd64/arm64 registry manifests
	@python3 scripts/check_images.py
	@python3 scripts/check_images_community.py

scan-images: ## Generate JSON vulnerability reports for every maintained image
	@python3 scripts/security.py scan

sbom: ## Generate one CycloneDX SBOM for every maintained image
	@python3 scripts/security.py sbom

check-security: ## Fail on unexcepted fixable CRITICAL image vulnerabilities
	@python3 scripts/security.py check

check-runtime: ## Pull missing layers, start the isolated default stack, and run runtime assertions
	@./scripts/check_runtime.sh

check-iot-runtime: ## Start the isolated IoT stack and verify MQTT auth/persistence plus openHAB readiness
	@sh ./scripts/check_iot_runtime.sh

check-optional-runtime: ## Verify Netdata host metrics and the committed k6 smoke test in isolation
	@sh ./scripts/check_optional_runtime.sh

check-community-runtime: ## Verify Uptime Kuma, Homepage, and Dozzle behind authenticated Traefik routes
	@sh ./scripts/check_community_runtime.sh

check-auth-runtime: ## Verify the Authelia portal and Traefik ForwardAuth integration in isolation
	@sh ./scripts/check_auth_runtime.sh

backup: ## Create a verified cold snapshot of all established and community volumes
	@# Compatibility engine: python3 scripts/backup.py create
	@BACKUP_ROOT="$(BACKUP_ROOT)" python3 scripts/backup_community.py create

verify-backup: ## Verify BACKUP offline without touching Docker
	@test -n "$(BACKUP)" || { echo "BACKUP is required" >&2; exit 2; }
	@# Compatibility engine: python3 scripts/backup.py verify "$(BACKUP)"
	@python3 scripts/backup_community.py verify "$(BACKUP)"

restore: ## Restore BACKUP into absent or empty volumes for the current project
	@test -n "$(BACKUP)" || { echo "BACKUP is required" >&2; exit 2; }
	@# Compatibility engine: python3 scripts/backup.py restore "$(BACKUP)"
	@python3 scripts/backup_community.py restore "$(BACKUP)"

check-backup-runtime: ## Exercise a disposable backup/verify/restore round trip
	@sh ./scripts/check_backup_runtime.sh

remote-init: ## Initialize the configured encrypted restic repository
	@python3 scripts/remote_backup.py init

remote-backup: ## Upload verified BACKUP to the configured encrypted restic repository
	@test -n "$(BACKUP)" || { echo "BACKUP is required" >&2; exit 2; }
	@python3 scripts/remote_backup.py upload "$(BACKUP)"

remote-snapshots: ## List remote restic snapshots created by this project
	@python3 scripts/remote_backup.py snapshots

verify-remote-backup: ## Verify repository structure and a bounded data sample
	@python3 scripts/remote_backup.py check

remote-retention: ## Apply the documented explicit remote retention and prune policy
	@python3 scripts/remote_backup.py retention

check-remote-backup-runtime: ## Exercise a disposable encrypted restic backup and restore round trip
	@sh ./scripts/check_remote_backup_runtime.sh

config: init ## Print the fully rendered Compose model for every locally configured profile
	@$(COMPOSE) --env-file .env $(ALL_PROFILES) config

core: init ## Start Traefik, Docker socket proxy, and whoami
	@$(COMPOSE) up -d

up: init ## Start the legacy-equivalent stack: core, monitoring, and Portainer
	@$(COMPOSE) $(DEFAULT_PROFILES) up -d

full: init ## Start every established persistent service, including Netdata, Mosquitto, and openHAB
	@$(COMPOSE) --profile monitoring --profile tools --profile iot --profile netdata up -d

monitoring: init ## Start core plus InfluxDB, Telegraf, and Grafana
	@$(COMPOSE) --profile monitoring up -d

netdata: init ## Start full host monitoring without changing the rest of the stack
	@$(COMPOSE) --profile netdata up -d netdata

tools: init ## Start core plus Portainer
	@$(COMPOSE) --profile tools up -d

iot: init ## Start core plus Mosquitto and openHAB
	@$(COMPOSE) --profile iot up -d

uptime: init ## Start Uptime Kuma behind the selected Traefik middleware
	@$(COMPOSE) --profile uptime up -d uptime-kuma

dashboard: init ## Start the static Homepage dashboard without Docker socket access
	@$(COMPOSE) --profile dashboard up -d homepage

dns-preflight: ## Check the configured DNS listener without changing the host
	@python3 scripts/dns_preflight.py

dns: init ## Run DNS preflight and start AdGuard Home explicitly
	@python3 scripts/dns_preflight.py
	@$(COMPOSE) --profile dns up -d adguard-home

auth-init: init ## Create or refresh local Authelia configuration without rotating credentials
	@python3 scripts/init_community.py

auth-check: auth-init ## Validate generated Authelia configuration with the pinned image
	@docker run --rm \
		--volume "$(CURDIR)/.secrets/authelia_configuration.yml:/config/configuration.yml:ro" \
		--volume "$(CURDIR)/.secrets/authelia_users.yml:/config/users_database.yml:ro" \
		--volume "$(CURDIR)/.secrets/authelia_jwt_secret:/run/secrets/authelia_jwt_secret:ro" \
		--volume "$(CURDIR)/.secrets/authelia_session_secret:/run/secrets/authelia_session_secret:ro" \
		--volume "$(CURDIR)/.secrets/authelia_storage_encryption_key:/run/secrets/authelia_storage_encryption_key:ro" \
		--env AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET_FILE=/run/secrets/authelia_jwt_secret \
		--env AUTHELIA_SESSION_SECRET_FILE=/run/secrets/authelia_session_secret \
		--env AUTHELIA_STORAGE_ENCRYPTION_KEY_FILE=/run/secrets/authelia_storage_encryption_key \
		authelia/authelia:4.39.20 \
		authelia config validate --config /config/configuration.yml

auth: auth-check ## Start the Authelia portal and ForwardAuth middleware
	@$(COMPOSE) --profile auth up -d authelia

dozzle: init ## Start protected read-only container log viewing through the socket proxy
	@$(COMPOSE) --profile logs up -d dozzle

community: init ## Start Uptime Kuma, Homepage, Dozzle, and selected authentication
	@profiles="--profile uptime --profile dashboard --profile logs"; \
	if grep -Eq '^AUTH_MIDDLEWARE=authelia@docker$$' .env; then \
		$(MAKE) --no-print-directory auth-check; \
		profiles="$$profiles --profile auth"; \
	fi; \
	$(COMPOSE) $$profiles up -d

k6: init ## Run the bounded k6 smoke test against K6_TARGET_URL
	@$(COMPOSE) up -d whoami
	@$(COMPOSE) --profile test run --rm k6

pull: init ## Pull every locally configured image version
	@$(COMPOSE) $(ALL_PROFILES) pull

ps: init ## Show containers from every locally configured profile
	@$(COMPOSE) $(ALL_PROFILES) ps

logs: init ## Follow logs from every locally configured profile
	@$(COMPOSE) $(ALL_PROFILES) logs --tail=200 -f

down: ## Stop every locally configured profile and preserve named volumes
	@$(COMPOSE) $(ALL_PROFILES) down --remove-orphans
