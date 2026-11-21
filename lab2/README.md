# Лабораторная работа №2. Микросервисное приложение CyberNews

CyberNews собирает публикации об информационной безопасности, показывает их в публичном каталоге и поддерживает обсуждения, модерацию и уведомления по подпискам. Цель лабораторной — разделить backend на самостоятельные сервисы, реализовать работу с данными и межсервисные контракты и подтвердить их автоматическими проверками. [Методичка PAD](https://github.com/Randwow/PAD/blob/b7beb3d0ec64cf48275c26b5ffe36a699a214db2/README.md#лабораторная-работа-2-микросервисное-приложение)

## Материалы для защиты

- [Технический отчёт](REPORT.md) и [матрица соответствия](REQUIREMENTS_MATRIX.md).
- [Демонстрация на 7–10 минут](DEMO.md) и [ответы на вопросы](DEFENSE.md).
- [Доказательства и команды воспроизведения](EVIDENCE.md) и [чеклист сдачи](SUBMISSION_CHECKLIST.md).
- Диаграммы [архитектуры](diagrams/architecture.md), [данных](diagrams/databases.md), [взаимодействий](diagrams/communication.md), [авторизации](diagrams/authentication.md) и [доставки событий](diagrams/article-events.md).

Код и Docker Compose расположены в корне репозитория. Каталог лабораторной содержит материалы, которые ссылаются на единственную реализацию проекта.

## Архитектура и хранение

| Сервис | Ответственность | База и роль |
| --- | --- | --- |
| [Auth](../services/auth/app/main.py) | Учётные записи, JWT, роли, статус аккаунта и административные сессии | `auth_db`, `auth_svc` |
| [Collector](../services/collector/app/main.py) | RSS/Atom, расписание, ручной запуск, нормализация и история синхронизаций | `collector_db`, `collector_svc` |
| [Articles](../services/articles/app/main.py) | Каталог, поиск, редактор, доступность статей и outbox | `article_db`, `article_svc` |
| [Community](../services/community/app/main.py) | Комментарии, реакции, избранное и статусы комментариев | `community_db`, `community_svc` |
| [Moderation](../services/moderation/app/main.py) | Жалобы, ограничения комментирования, команды и аудит | `moderation_db`, `moderation_svc` |
| [Notifications](../services/notifications/app/main.py) | Подписки, дедупликация событий, уведомления и отметки прочтения | `notification_db`, `notification_svc` |

Каждое приложение имеет Dockerfile, конфигурацию, HTTP API и историю миграций. Nginx, PostgreSQL и RabbitMQ образуют инфраструктуру. Всего в Compose девять контейнеров. PostgreSQL использует отдельные базы и роли на одном сервере. SQLAlchemy связывает модели с данными, Alembic управляет схемами, межсервисные ссылки хранятся как UUID. FastAPI формирует OpenAPI. Публичный интерфейс использует HTML, CSS и JavaScript. [Архитектура и обоснование технологий](../docs/ARCHITECTURE.md).

REST позволяет сразу проверить полномочия, доступность статьи и разрешение на комментирование, а также получить результат импорта или модерации. Первая публикация создаёт событие в PostgreSQL outbox. Dispatcher передаёт его RabbitMQ, а Notifications пишет уведомления подписчиков и подтверждает доставку после commit. [Диаграмма события](diagrams/article-events.md).

## Запуск и конфигурация

В Windows 11 нужны Git, PowerShell 5.1 или 7, Docker Desktop с Linux-контейнерами, Docker Compose v2 и BuildKit. Локальный Python 3.12 нужен для pytest и Playwright. Запускайте команды из корня CyberNews.

```powershell
.\scripts\init-env.ps1
docker compose up -d --build
.\scripts\verify-lab2.ps1
```

Шаблон [.env.example](../.env.example) описывает параметры. Инициализация сохраняет уже заданные значения. `GATEWAY_PORT` по умолчанию 8080, `POSTGRES_PORT` — 5433, `RABBITMQ_MANAGEMENT_PORT` — 15672. Адреса сервисов, строка подключения и секреты поступают из конфигурации контейнеров. При чистом запуске PostgreSQL создаёт шесть баз, а entrypoint каждого сервиса выполняет его `alembic upgrade head` перед запуском HTTP. Команда `docker compose exec -T auth alembic current --check-heads` проверяет актуальность ревизии Auth. [Описание переменных и миграций](../README.md).

Текущая конфигурация предназначена для локального запуска по HTTP на loopback. Публичной эксплуатации потребуются TLS, управление секретами, резервное копирование и операционное сопровождение.

## API и права

Главная страница доступна на [localhost:8080](http://localhost:8080/), панель — на [localhost:8080/admin/](http://localhost:8080/admin/). Маршруты в таблице отсчитываются от префикса соответствующего сервиса. У каждого префикса есть `/health`, `/ready`, `/docs` и `/openapi.json`.

| Swagger | Основные маршруты |
| --- | --- |
| [Auth](http://localhost:8080/api/v1/auth/docs) | `POST /register`, `POST /login`, `GET /me`, `POST /admin/unlock` |
| [Collector](http://localhost:8080/api/v1/collector/docs) | `GET /sources`, `POST /sync`, `GET /runs/{run_id}` |
| [Articles](http://localhost:8080/api/v1/articles/docs) | `GET /`, `GET /{article_id}`, `GET /categories`, `POST /admin/articles` |
| [Community](http://localhost:8080/api/v1/community/docs) | `GET /articles/{article_id}/comments`, `POST /articles/{article_id}/comments`, `GET /bookmarks` |
| [Moderation](http://localhost:8080/api/v1/moderation/docs) | `POST /reports`, `PATCH /reports/{report_id}`, `POST /restrictions` |
| [Notifications](http://localhost:8080/api/v1/notifications/docs) | `GET /`, `GET /unread-count`, `PUT /subscriptions/{category_id}` |

Guest читает публикации и публичные комментарии. User дополнительно управляет своими данными и участвует в обсуждении. Moderator рассматривает жалобы, ограничивает комментирование и скрывает комментарии обычных пользователей. Super Admin управляет ролями, аккаунтами, редакторским каталогом и источниками, снимает ограничения и восстанавливает комментарии. Административные операции проверяют JWT и отдельную сессию с максимальным сроком 15 минут. [Auth и Moderation](../docs/AUTH_MODERATION_API.md) · [RSS и каталог](../docs/NEWS_RSS_API.md) · [Community и Notifications](../docs/COMMUNITY_NOTIFICATIONS_API.md).

Пример безопасного чтения из PowerShell.

```powershell
Invoke-RestMethod 'http://localhost:8080/api/v1/articles/?q=security&limit=5'
Invoke-RestMethod 'http://localhost:8080/api/v1/articles/categories'
```

## Ошибки и логи

`/health` проверяет живость процесса. `/ready` проверяет его базу, а для Moderation также Auth и для Notifications подключение потребителя к RabbitMQ. Типовые ответы содержат 401, 403, 404, 409, 422, 429 или 503 в зависимости от причины. Публичные ошибки содержат обобщённый JSON. При потере критической проверки защищённое действие отклоняется. Nginx и сервисы связывают JSON-журналы HTTP-запроса по `X-Request-ID`. [Сценарии ошибок и примеры логов](EVIDENCE.md).

## Проверки и демонстрация

```powershell
.\scripts\verify-lab2.ps1
.\scripts\smoke-test.ps1 -SecretsOnly
.\.venv\Scripts\python.exe -m pip install -r tests\stage5-requirements.txt
.\scripts\smoke-test-stage2.ps1 -RunPytest -PythonExe .\.venv\Scripts\python.exe
.\scripts\smoke-test-stage3.ps1 -PythonExe .\.venv\Scripts\python.exe
.\scripts\smoke-test-stage4.ps1 -PythonExe .\.venv\Scripts\python.exe
$env:CYBERNEWS_BROWSER_CHANNEL = 'msedge'
.\scripts\smoke-test-stage5.ps1 -PythonExe .\.venv\Scripts\python.exe
```

При первом запуске создайте тестовое окружение командой `py -3.12 -m venv .venv`. `verify-lab2.ps1` читает рабочее состояние. `smoke-test-stage2.ps1`–`smoke-test-stage5.ps1` используют отдельные Compose-проекты, в которых можно изменять данные и моделировать отказы. Исторический `smoke-test.ps1` без `-SecretsOnly` выполняет перезапуски зависимостей и не подходит для рабочего стенда.

Защита использует рабочий сайт для чтения реальной ленты и отдельный стенд для регистрации, модерации и публикаций. Фактические результаты, в том числе проверку устойчивости outbox и ограничения масштабирования, см. в [отчёте](REPORT.md) и [сценарии](DEMO.md).
