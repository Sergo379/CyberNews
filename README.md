# CyberNews

CyberNews — микросервисный новостной портал по информационной безопасности. Работают RSS-сбор, каталог статей, авторизация, комментарии, реакции, избранное, модерация и внутренние уведомления о новых статьях.

В проекте используются Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2, Alembic, psycopg 3, PostgreSQL 17, RabbitMQ 4.3 с Management UI, Nginx и Docker Compose.

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

`init-env.ps1` создаёт локальный `.env` из `.env.example`. При обновлении стенда скрипт добавляет недостающие секреты межсервисных API и сохраняет существующие ключи и пароли. Порты `GATEWAY_PORT`, `POSTGRES_PORT` и `RABBITMQ_MANAGEMENT_PORT` можно изменить в `.env` перед запуском. Все опубликованные порты привязаны к `127.0.0.1`.

## RSS и каталог новостей

Collector при запуске собирает новости The Hacker News, BleepingComputer и Krebs on Security, а затем повторяет сбор каждые 30 минут. Articles хранит уникальные статьи и предоставляет поиск и фильтры. Для внешних RSS по умолчанию публикуются заголовок, краткая выдержка и ссылка на оригинал. Super Admin может управлять источниками, запускать сбор вручную и публиковать собственные материалы.

- [Список опубликованных статей](http://localhost:8080/api/v1/articles/)
- [Collector Swagger](http://localhost:8080/api/v1/collector/docs)
- [Articles Swagger](http://localhost:8080/api/v1/articles/docs)

Настройки сбора, права на контент и команды ручного обновления приведены в [руководстве RSS и каталога](docs/NEWS_RSS_API.md).

## Пользователи и модерация

После запуска создайте первого Super Admin в интерактивном терминале PowerShell.

```powershell
docker compose exec auth python -m app.bootstrap
```

Введите email, никнейм, основной пароль и отдельный административный пароль. Оба пароля вводятся скрыто и хранятся в виде хешей Argon2id. После первичной настройки новых администраторов назначает действующий Super Admin через API.

Swagger UI доступны для [Auth](http://localhost:8080/api/v1/auth/docs) и [Moderation](http://localhost:8080/api/v1/moderation/docs). Обычный вход даёт `access_token` для заголовка `Authorization: Bearer …`. Для административных запросов дополнительно передайте `X-Admin-Session`, полученный через `POST /admin/unlock`. Сессия действует до 15 минут и завершается командой `POST /admin/lock`.

Матрица ролей, список маршрутов, примеры PowerShell для регистрации, назначения Moderator, работы с жалобами, блокирования и снятия ограничений приведены в [руководстве API](docs/AUTH_MODERATION_API.md).

## Комментарии, избранное и уведомления

Community проверяет опубликованную статью и разрешение комментировать, хранит реакции и личное избранное. Notifications поддерживает подписки на категории и доставляет внутренние уведомления о первой публикации через RabbitMQ. Операции модерации комментариев проходят через Moderation и сохраняются в аудите.

- [Community Swagger](http://localhost:8080/api/v1/community/docs)
- [Notifications Swagger](http://localhost:8080/api/v1/notifications/docs)
- [Контракты API, RabbitMQ и примеры PowerShell](docs/COMMUNITY_NOTIFICATIONS_API.md)

## Миграции

Все шесть приложений применяют свои миграции при запуске. Для ручного повторного запуска на поднятом стеке используйте следующие команды.

```powershell
docker compose exec -T auth alembic upgrade head
docker compose exec -T moderation alembic upgrade head
docker compose exec -T collector alembic upgrade head
docker compose exec -T articles alembic upgrade head
docker compose exec -T community alembic upgrade head
docker compose exec -T notifications alembic upgrade head
docker compose exec -T auth alembic current
docker compose exec -T moderation alembic current
docker compose exec -T collector alembic current
docker compose exec -T articles alembic current
docker compose exec -T community alembic current
docker compose exec -T notifications alembic current
```

## Проверка API

```powershell
Invoke-RestMethod http://localhost:8080/health
Invoke-RestMethod http://localhost:8080/api/v1/auth/health
Invoke-RestMethod http://localhost:8080/api/v1/auth/ready
.\scripts\smoke-test.ps1
```

Под `/api/v1/{service}/` доступны `health`, `ready`, `openapi.json` и `docs`. Подставьте `auth`, `collector`, `articles`, `community`, `moderation` или `notifications`. `/health` проверяет ответ процесса, `/ready` выполняет запрос к его базе PostgreSQL. Moderation дополнительно проверяет готовность Auth, Notifications — подключение к RabbitMQ. Если проверяемая зависимость недоступна, `/ready` возвращает `503`. Запросы можно сопоставить с JSON-логами по заголовку `X-Request-ID`.

Smoke-тест проверяет привязки портов, Git, все сервисы через Gateway, разграничение прав PostgreSQL и RabbitMQ. Он кратковременно останавливает PostgreSQL проекта и перезапускает RabbitMQ проекта, проверяет сохранность временной записи и очереди и затем удаляет их. Выполняйте его в локальном стеке без параллельных инфраструктурных операций.

Тесты второго этапа запускаются на отдельном стенде с временным PostgreSQL, отдельными секретами и динамическим портом Gateway. Понадобится Compose 2.24.4+ для тестовой конфигурации. Скрипт завершает работу тестовых контейнеров в блоке `finally`, сохраняя рабочие контейнеры и тома проекта.

```powershell
.\scripts\smoke-test-stage2.ps1

# Полный набор pytest и smoke-тест. Укажите путь к Python 3.12 при необходимости.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tests/stage2-requirements.txt
.\scripts\smoke-test-stage2.ps1 -RunPytest -PythonExe .\.venv\Scripts\python.exe
```

Тесты третьего этапа поднимают отдельный Compose-стенд и используют локальные RSS/Atom-фикстуры. Рабочий Collector продолжает обращаться к реальным источникам.

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests/stage3-requirements.txt
.\scripts\smoke-test-stage3.ps1 -PythonExe .\.venv\Scripts\python.exe
```

Тесты четвёртого этапа используют изолированные PostgreSQL, RabbitMQ и Gateway. Тестовые аккаунты, статьи и события создаются в этом стенде.

```powershell
.\scripts\smoke-test-stage4.ps1 -PythonExe .\.venv\Scripts\python.exe
```

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

Откройте RabbitMQ Management и войдите с `RABBITMQ_USER` и `RABBITMQ_PASSWORD` из `.env`. В vhost `cybernews` работают обменник `cybernews.events`, очередь уведомлений и очередь ошибок. AMQP доступен во внутренней сети Compose через `rabbitmq:5672`. [RabbitMQ Management](http://localhost:15672/)

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
