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
- изолированный runtime smoke test для фактического запуска default stack;
- отдельный IoT runtime smoke test для MQTT authentication/persistence и готовности openHAB;
- проверяемые cold backup/restore named volumes с manifest, checksums и реальным CI round trip;
- k3s отделён от Compose, чтобы базовый стек не превращался в сложную платформу.

## Требования

- Linux с Docker Engine и актуальным Compose plugin (`docker compose`, не legacy `docker-compose`);
- `make`, POSIX shell и Python 3.11+;
- OpenSSL и `curl`;
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
4. создаёт bcrypt cost 12 для Traefik и SHA512-PBKDF2 password record с 220000 итерациями для Mosquitto через фиксированные официальные образы; plaintext не передаётся аргументом процесса;
5. сохраняет генерируемые raw secrets без завершающего перевода строки, чтобы file-backed token можно было безопасно использовать в HTTP headers.

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

Домен, bind-адреса, HTTP-порт, MQTT-порт и timezone меняются в `.env`. `HTTP_HOST_IP` и `MQTT_HOST_IP` по умолчанию равны `0.0.0.0`; задайте `127.0.0.1`, чтобы публиковать соответствующий порт только локально. `HOMELAB_PROJECT_NAME` задаёт общий префикс проекта, сетей и volumes; default `homelab` сохраняет прежние имена. Для доступа с другого компьютера настройте локальный DNS или записи hosts для выбранного `BASE_DOMAIN`.

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
| `make check` | выполнить локальные static, behavior, shell и Compose-проверки |
| `make check-images` | проверить registry tags и manifests для `amd64`/`arm64` |
| `make check-runtime` | поднять изолированный default stack и проверить маршруты, auth, provisioning и метрики |
| `make check-iot-runtime` | поднять изолированный IoT stack и проверить MQTT auth/persistence и готовность openHAB |
| `make backup` | создать атомарный проверенный cold snapshot существующих named volumes |
| `make verify-backup BACKUP=...` | офлайн проверить manifest, checksums и tar safety |
| `make restore BACKUP=...` | восстановить snapshot в отсутствующие или пустые volumes текущего project name |
| `make check-backup-runtime` | выполнить одноразовый backup/verify/restore round trip |
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

Raw password/token files создаются без CR/LF в конце. Это важно для `.secrets/influxdb_token`: Telegraf Docker secret store читает байты файла непосредственно, поэтому перевод строки попал бы в HTTP `Authorization` header. При следующем `make init` старый token, созданный предыдущей версией скрипта, нормализуется удалением только завершающего LF/CRLF; само значение token не ротируется.

Для Mosquitto файл `.secrets/mosquitto_passwords` содержит только SHA512-PBKDF2 hash с 220000 итерациями. При старте контейнер копирует его из read-only Compose secret в приватный `tmpfs`, назначает владельца UID/GID `1883` и режим `0600`; исходный plaintext остаётся только в `.secrets/mosquitto_password`.

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

Сети разделены по назначению. При default `HOMELAB_PROJECT_NAME=homelab` их имена остаются прежними:

- `homelab_proxy` — HTTP-приложения за Traefik;
- `homelab_backend` — закрытый metrics backend;
- `homelab_socket` — закрытый доступ к Docker API proxy;
- `homelab_iot` — Mosquitto и openHAB.

## Зафиксированные версии

| Компонент | Версия образа |
| --- | --- |
| Bootstrap helper Apache httpd | `2.4.68` |
| Backup helper Alpine | `3.24.1` |
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

Состояние хранится в именованных volumes с префиксом из `HOMELAB_PROJECT_NAME`; default остаётся `homelab_`. `make down` их не удаляет.

Перед обновлением stateful-сервисов выполните `make down`, затем `make backup`. Snapshot атомарно публикуется только после проверки manifest, SHA-256 checksums и безопасной структуры каждого tar-архива. Офлайн-проверка выполняется через `make verify-backup BACKUP=backups/<snapshot-id>`, а восстановление рекомендуется делать рядом с оригиналом через отдельный `HOMELAB_PROJECT_NAME`.

Полная процедура, модель конфиденциальности и rollback описаны в [`docs/BACKUP.md`](docs/BACKUP.md). Переход со старой bind-mount структуры описан в [`docs/MIGRATION.md`](docs/MIGRATION.md).

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

## Пять уровней проверки

### 1. Быстрая конфигурационная проверка

```bash
make check
```

Проверяет static policies, unit/behavior tests, shell syntax и полностью объединённую Compose-модель. Контейнеры приложений не запускаются. Проверка отклоняет:

- невалидные Compose, JSON и TOML;
- нарушения идемпотентности и прав доступа при локальной генерации credentials;
- newline-terminated raw tokens, которые нельзя безопасно передавать в HTTP headers;
- отсутствующие roadmap-сервисы;
- `latest` и неявные image tags;
- известные ранее опубликованные credentials;
- destructive host-wide команды;
- случайно отслеживаемые `.env` или `.secrets/`.

### 2. Проверка registry manifests

```bash
make check-images
```

Получает через Docker Buildx только registry manifests, не скачивает слои образов и не запускает сервисы. Проверка завершается ошибкой, если tag отсутствует либо образ не публикует оба поддерживаемых варианта: `linux/amd64` и `linux/arm64`.

### 3. Изолированная runtime-проверка default stack

```bash
make check-runtime
```

Создаёт одноразовый Compose-проект с уникальными именами сетей и ресурсов, заменяет данные InfluxDB, Grafana и Portainer на `tmpfs`, публикует Traefik только на случайном порту `127.0.0.1` и запускает core + monitoring + Portainer.

Проверяются:

- `401` без Basic Auth и `200` с ним для whoami и Traefik dashboard;
- health endpoints InfluxDB и Grafana;
- Portainer status endpoint;
- provisioned InfluxDB datasource в Grafana;
- появление реальной measurement `system` от Telegraf в InfluxDB;
- гарантированный scoped cleanup с удалением только одноразовых runtime volumes.

Проверка скачивает отсутствующие image layers и занимает заметно больше времени. Она не запускает Netdata, Mosquitto, openHAB или k6 и не читает рабочие `.env`/`.secrets/`.

### 4. Изолированная IoT runtime-проверка

```bash
make check-iot-runtime
```

Создаёт отдельный проект `homelab-iot-runtime-*`, публикует HTTP и MQTT только на случайных loopback-портах, запускает core + profile `iot` и использует официальный Mosquitto image для краткоживущих client-контейнеров через Linux host networking.

Проверяются:

- отказ анонимному MQTT publish;
- authenticated QoS 1 retained publish и точное получение payload через subscribe;
- сохранение retained payload после `restart mosquitto`, что проверяет SQLite persistence на project-scoped volume;
- готовность openHAB через его Traefik hostname;
- отсутствие MQTT password в process arguments и гарантированный scoped cleanup.

Проверка скачивает отсутствующие layers Mosquitto/openHAB и рассчитана только на Linux Docker Engine. Она не устанавливает openHAB MQTT Binding, не завершает setup wizard и не проверяет UPnP, multicast, USB или другое оборудование.

### 5. Изолированная backup/restore runtime-проверка

```bash
make check-backup-runtime
```

Создаёт уникальные одноразовые local volumes с вложенными текстовыми и бинарными файлами, пустым файлом, нестандартными permissions и безопасным относительным symlink. Затем выполняет cold backup, офлайн-проверку, удаление source volumes и side-by-side restore в другой project name.

Проверка сравнивает bytes и существенные filesystem metadata, подтверждает отказ для повреждённого snapshot и непустого target volume, а затем удаляет только собственные fixture-ресурсы. Она не запускает приложения homelab и не читает рабочие `.env` или `.secrets/`; подробная процедура восстановления находится в [`docs/BACKUP.md`](docs/BACKUP.md).
