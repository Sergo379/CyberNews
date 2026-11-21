# CyberNews

CyberNews — микросервисный новостной портал по информационной безопасности. Этап 1 закладывает инфраструктуру и API для диагностики. Функции портала запланированы на следующие этапы.

Стек: Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2, psycopg 3, PostgreSQL 17, RabbitMQ 4.3 с Management UI, Nginx и Docker Compose.

## Запуск в Windows 11

Понадобятся Git, Windows PowerShell 5.1 или PowerShell 7 и запущенный Docker Desktop с WSL 2, Linux-контейнерами, Compose v2.17 или новее и BuildKit. Python, PostgreSQL и RabbitMQ устанавливаются в контейнерах.

```powershell
Set-Location C:\MyWorkP\CyberNews
docker version
docker compose version
.\scripts\init-env.ps1
docker compose up -d --build
docker compose ps
```

`init-env.ps1` создаёт локальный `.env` из `.env.example` с восемью независимыми случайными паролями и сохраняет существующий файл. Порты `GATEWAY_PORT`, `POSTGRES_PORT` и `RABBITMQ_MANAGEMENT_PORT` можно изменить в `.env` перед запуском. Все публичные порты привязаны к `127.0.0.1`.

## Проверка API

```powershell
Invoke-RestMethod http://localhost:8080/health
Invoke-RestMethod http://localhost:8080/api/v1/auth/health
Invoke-RestMethod http://localhost:8080/api/v1/auth/ready
.\scripts\smoke-test.ps1
```

Под `/api/v1/{service}/` доступны корневой диагностический ответ, `health`, `ready`, `openapi.json` и `docs`. Подставьте `auth`, `collector`, `articles`, `community`, `moderation` или `notifications`. `/health` проверяет ответ процесса, `/ready` выполняет запрос к его базе PostgreSQL и возвращает `503`, когда база недоступна. Запросы можно сопоставить с JSON-логами по заголовку `X-Request-ID`.

Smoke-тест проверяет привязки портов, Git, все сервисы через Gateway, разграничение прав PostgreSQL и RabbitMQ. Он кратковременно останавливает PostgreSQL проекта и перезапускает RabbitMQ проекта, проверяет сохранность временной записи и очереди и затем удаляет их. Выполняйте его в локальном стеке без параллельных инфраструктурных операций.

## PostgreSQL и pgAdmin 4

В pgAdmin выберите **Servers → Register → Server**. На вкладке **General** укажите имя подключения. На вкладке **Connection** используйте `127.0.0.1`, порт из `POSTGRES_PORT` (по умолчанию `5433`), базу обслуживания и пользователя из таблицы. Пароль возьмите из локального `.env`. Для административного входа используйте базу `postgres` и значения `POSTGRES_USER` и `POSTGRES_PASSWORD`.

| База обслуживания | Пользователь | Переменная пароля |
| --- | --- | --- |
| `auth_db` | `auth_svc` | `AUTH_DB_PASSWORD` |
| `collector_db` | `collector_svc` | `COLLECTOR_DB_PASSWORD` |
| `article_db` | `article_svc` | `ARTICLE_DB_PASSWORD` |
| `community_db` | `community_svc` | `COMMUNITY_DB_PASSWORD` |
| `moderation_db` | `moderation_svc` | `MODERATION_DB_PASSWORD` |
| `notification_db` | `notification_svc` | `NOTIFICATION_DB_PASSWORD` |

## RabbitMQ

Откройте [RabbitMQ Management](http://localhost:15672/) и войдите с `RABBITMQ_USER` и `RABBITMQ_PASSWORD` из `.env`. Для будущих событий выделен виртуальный хост `cybernews`. AMQP доступен во внутренней сети Compose через `rabbitmq:5672`.

## Независимый запуск сервиса

При первом запуске создайте `.env`. Для сборки и запуска выбранного сервиса с PostgreSQL используйте `docker compose up -d --build auth`. Для проверки из контейнера выполните следующую команду.

```powershell
docker compose exec -T auth python -c "from urllib.request import urlopen; print(urlopen('http://127.0.0.1:8000/ready').read().decode())"
```

Отдельный образ можно собрать из корня проекта командой `docker build --build-context runtime=./services/runtime -t cybernews-auth ./services/auth`. При запуске образа на своей Docker-сети передайте `DATABASE_URL` в формате `postgresql+psycopg://...` или `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` и `DB_PASSWORD`. HTTP-порт внутри контейнера — `8000`. Секреты передавайте через локальное окружение или файл параметров запуска вне Git.

## Остановка и диагностика

```powershell
docker compose stop
docker compose up -d
docker compose down
docker compose config --quiet
docker compose ps
docker compose logs --tail 100 gateway postgres rabbitmq auth
```

`stop` останавливает контейнеры. `down` удаляет контейнеры и сеть проекта, сохраняя именованные тома PostgreSQL и RabbitMQ. Первичная инициализация учётных данных PostgreSQL и RabbitMQ происходит при создании пустых томов. Для смены действующих паролей обновите учётные записи в самих системах и синхронизируйте `.env`.

Если Docker CLI отсутствует в `PATH`, откройте новую консоль или добавьте каталог `resources\bin` установленного Docker Desktop в `PATH` текущего процесса. Если опубликованный порт занят, измените соответствующую переменную в `.env`. При ответе `503` проверьте логи сервиса и PostgreSQL, соответствие пароля роли и имя базы. Команда `docker compose config --quiet` проверяет YAML без вывода разрешённых значений переменных.

## Структура

| Каталог | Назначение |
| --- | --- |
| `services/` | Шесть приложений с отдельными Dockerfile, конфигурациями, API и метаданными SQLAlchemy. В `services/runtime/` находится общий код журналирования, подключения к БД и диагностики |
| `gateway/` | Шаблон конфигурации Nginx |
| `infrastructure/postgres/`, `infrastructure/rabbitmq/` | Первичная инициализация баз и настройки брокера |
| `scripts/`, `tests/` | Генерация локальной конфигурации и автоматические инфраструктурные проверки |
| `frontend/` | Резерв для публичного интерфейса, админ-панели, стилей, JavaScript и локализаций |
| `k8s/` | Резерв для манифестов лабораторной №3 |
| `docs/`, `lab2/`, `lab3/` | Архитектура и материалы лабораторных работ |

Подробнее об API-контракте и границах сервисов — в [архитектурном описании](docs/ARCHITECTURE.md).
