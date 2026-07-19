# Docker Compose Homelab

Простой, воспроизводимый и безопасный homelab-стек для Linux `amd64` и `arm64`.

В репозитории сохранены все прежние возможности — Traefik, InfluxDB, Telegraf, Grafana и Portainer — и завершены явно запланированные интеграции: Netdata, Eclipse Mosquitto, openHAB, k6 и отдельная инструкция для k3s.

## Что изменилось

- один корневой `compose.yaml` вместо набора независимых файлов;
- Docker Compose profiles для необязательных групп сервисов;
- фиксированные версии образов вместо `latest`;
- локально генерируемые Compose secrets вместо паролей в Git;
- Traefik dashboard и whoami без insecure-порта и с общим Basic Auth;
- доступ Traefik и Telegraf к Docker API через ограниченный socket proxy;
- именованные volumes, которые не удаляются командой `make down`;
- healthchecks, CI-проверка, Renovate и компактные поддерживаемые конфиги;
- отдельная проверка существования image tags и manifests для `amd64`/`arm64`;
- k3s отделён от Compose, чтобы базовый стек не превращался в сложную платформу.

## Требования

- Linux с Docker Engine и актуальным Compose plugin (`docker compose`, не legacy `docker-compose`);
- `make`, POSIX shell и Python 3.11+;
- OpenSSL;
- пользователь с доступом к Docker daemon.

## Быстрый запуск

```bash
git clone https://github.com/646826/docker-compose-files.git
cd docker-compose-files
make init
make up
```

`make init`:

1. создаёт `.env` из `.env.example`, если файла ещё нет;
2. создаёт только отсутствующие файлы в `.secrets/`;
3. не заменяет существующие настройки и пароли;
4. создаёт bcrypt cost 12 для Traefik и Argon2id password record для Mosquitto через фиксированные официальные образы; plaintext не передаётся аргументом процесса.

`make up` запускает эквивалент прежнего набора: core + monitoring + Portainer.

## Адреса по умолчанию

| Сервис | Адрес | Запуск |
| --- | --- | --- |
| Traefik dashboard | `http://traefik.localhost/dashboard/` | всегда |
| whoami | `http://whoami.localhost` | всегда |
| InfluxDB | `http://influxdb.localhost` | `make up` / `make monitoring` |
| Grafana | `http://grafana.localhost` | `make up` / `make monitoring` |
| Portainer | `http://portainer.localhost` | `make up` / `make tools` |
| Netdata | `http://localhost:19999` | `make full` / `make netdata` |
| openHAB | `http://openhab.localhost` | `make full` / `make iot` |
| Mosquitto | `mqtt://localhost:1883` | `make full` / `make iot` |

Домен, HTTP-порт, MQTT-порт и timezone меняются в `.env`. Для доступа с другого компьютера настройте локальный DNS или записи hosts для выбранного `BASE_DOMAIN`.

## Команды

| Команда | Назначение |
| --- | --- |
| `make help` | показать доступные команды |
| `make init` | создать локальную конфигурацию и отсутствующие secrets |
| `make core` | запустить Traefik, socket proxy и whoami |
| `make up` | запустить core + monitoring + Portainer |
| `make full` | запустить все постоянные сервисы, включая Netdata, Mosquitto и openHAB |
| `make monitoring` | core + InfluxDB + Telegraf + Grafana |
| `make netdata` | запустить только Netdata для мониторинга хоста |
| `make tools` | core + Portainer |
| `make iot` | core + Mosquitto + openHAB |
| `make k6` | выполнить ограниченный 10-секундный smoke test |
| `make pull` | загрузить выбранные версии всех образов |
| `make ps` | показать контейнеры всех profiles |
| `make logs` | следить за логами |
| `make check` | выполнить локальные статические, shell и Compose-проверки |
| `make check-images` | проверить registry tags и manifests для `amd64`/`arm64` |
| `make down` | остановить проект, сохранив volumes |

## Учётные данные

В Git нет рабочих паролей и токенов. Локальные значения находятся в `.secrets/`:

| Сервис | Пользователь | Пароль или токен |
| --- | --- | --- |
| Traefik и whoami | `TRAEFIK_USERNAME` из `.env` | `.secrets/traefik_password` |
| Grafana | `GRAFANA_ADMIN_USER` из `.env` | `.secrets/grafana_admin_password` |
| InfluxDB | `.secrets/influxdb_username` | `.secrets/influxdb_password`, `.secrets/influxdb_token` |
| Mosquitto | `MOSQUITTO_USERNAME` из `.env` | `.secrets/mosquitto_password` |
| Portainer | задаётся в мастере первого запуска | хранится в Portainer volume |

Каталог `.secrets/` имеет режим `0700`. Plaintext-файлы, которые нужны только оператору, имеют режим `0600`. Источники file-backed Compose secrets имеют режим `0644`, потому что Compose bind-монтирует их без remap UID/GID; приватный родительский каталог по-прежнему запрещает другим host-пользователям доступ к файлам. Каждый контейнер получает только явно назначенные ему secrets.

Для Mosquitto файл `.secrets/mosquitto_passwords` содержит только Argon2id hash. При старте контейнер копирует его из read-only Compose secret в приватный `tmpfs`, назначает владельца UID/GID `1883` и режим `0600`; исходный plaintext остаётся только в `.secrets/mosquitto_password`.

MQTT listener требует пароль, но default-порт `1883` не использует TLS. Оставляйте его в доверенной локальной сети; для передачи через недоверенную сеть добавьте deployment-specific TLS listener на `8883` и не публикуйте plaintext listener наружу.

Пример чтения локального пароля:

```bash
cat .secrets/grafana_admin_password
```

После первого `make init` не меняйте `INFLUXDB_USERNAME`, `TRAEFIK_USERNAME` или `MOSQUITTO_USERNAME` отдельно от уже созданных credentials. Скрипт отклонит такое расхождение, а не создаст незаметно нерабочую пару. Для совершенно нового развёртывания удалите только соответствующие локальные secret-файлы и повторите `make init`; для работающего или мигрированного сервиса сначала выполните ротацию учётной записи средствами самого приложения.

Не добавляйте `.env` и `.secrets/` в Git, резервные копии или логи без шифрования.

## Profiles и архитектура

- **Core без profile:** `docker-socket-proxy`, Traefik, whoami.
- **`monitoring`:** InfluxDB, Telegraf, Grafana.
- **`netdata`:** Netdata с доступом к данным Linux-хоста.
- **`tools`:** Portainer.
- **`iot`:** Mosquitto 2.1 с password-file/SQLite plugins и openHAB.
- **`test`:** одноразовый k6.

Сети разделены по назначению:

- `homelab_proxy` — HTTP-приложения за Traefik;
- `homelab_backend` — закрытый metrics backend;
- `homelab_socket` — закрытый доступ к Docker API proxy;
- `homelab_iot` — Mosquitto и openHAB.

## Зафиксированные версии

| Компонент | Версия образа |
| --- | --- |
| Bootstrap helper Apache httpd | `2.4.68` |
| Docker socket proxy | `0.4.2` |
| Traefik | `3.7.8` |
| whoami | `1.11.0` |
| InfluxDB | `2.9.1` |
| Telegraf | `1.39.1` |
| Grafana | `13.1.0` |
| Portainer CE LTS | `2.39.5` |
| Netdata | `2.10.3` |
| Eclipse Mosquitto | `2.1.2` |
| openHAB | `5.2.0` |
| k6 | `2.1.0` |

Renovate предлагает обновления отдельными pull request; обновления не применяются автоматически.

## Данные и резервные копии

Состояние хранится в именованных volumes с префиксом `homelab_`. `make down` их не удаляет.

Пример архивирования Grafana:

```bash
mkdir -p backups
docker run --rm \
  -v homelab_grafana_data:/data:ro \
  -v "$PWD/backups:/backup" \
  alpine:3.22 \
  tar -czf /backup/grafana-data.tgz -C /data .
```

Перед обновлением баз данных и Portainer делайте резервную копию соответствующих volumes. Переход со старой структуры описан в [`docs/MIGRATION.md`](docs/MIGRATION.md).

## Важные ограничения

### Netdata

Для полноценного мониторинга Linux-хоста Netdata использует host network/PID, `SYS_PTRACE`, `SYS_ADMIN`, read-only host mounts и Docker socket. Поэтому он вынесен в отдельный opt-in profile `netdata`, не запускается обычной командой `make up` и открывается напрямую на порту `19999`.

### Portainer

Portainer предназначен для управления Docker-хостом и поэтому напрямую монтирует Docker socket. Не публикуйте его в интернет и ограничьте доступ доверенной сетью.

### openHAB

Для MQTT Binding укажите внутренний broker `mosquitto:1883`, пользователя `MOSQUITTO_USERNAME` из `.env` и пароль из `.secrets/mosquitto_password`. Адрес работает внутри Compose-сети и не зависит от опубликованного host-порта.

Bridge-сеть и Traefik дают переносимый безопасный default. Некоторые bindings, использующие UPnP/multicast или USB-устройства, требуют host networking, дополнительных capabilities или `devices`. Добавляйте их локальным override-файлом только для конкретного оборудования.

### TLS

Локальный default использует HTTP и `*.localhost`. Автоматический публичный TLS не включён, потому что он требует реального домена, DNS и выбранного ACME challenge. Это лучше добавлять отдельным deployment-specific override, а не хранить фиктивную универсальную конфигурацию.

## k3s

k3s не запускается внутри этого Compose-проекта. Причины и безопасный вариант совместной установки описаны в [`docs/K3S.md`](docs/K3S.md).

## Проверка

Быстрая локальная проверка конфигурации:

```bash
make check
```

Она отклоняет:

- невалидные Compose, JSON и TOML;
- нарушения идемпотентности и прав доступа при локальной генерации credentials;
- отсутствующие roadmap-сервисы;
- `latest` и неявные image tags;
- известные ранее опубликованные credentials;
- destructive host-wide команды;
- случайно отслеживаемые `.env` или `.secrets/`.

Отдельная сетевая проверка опубликованных образов:

```bash
make check-images
```

Она получает через Docker Buildx только registry manifests, не скачивает слои образов и не запускает сервисы. Проверка завершается ошибкой, если tag отсутствует либо образ не публикует оба поддерживаемых варианта: `linux/amd64` и `linux/arm64`.
