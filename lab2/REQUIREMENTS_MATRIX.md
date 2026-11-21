# Матрица соответствия методичке PAD

Редакция курса `b7beb3d0ec64cf48275c26b5ffe36a699a214db2`, проверка 22 ноября 2026 года. Оценку выставляет преподаватель. Статусы относятся к локальному стенду и его изолированной тестовой копии. [Методичка PAD](https://github.com/Randwow/PAD/blob/b7beb3d0ec64cf48275c26b5ffe36a699a214db2/README.md#лабораторная-работа-2-микросервисное-приложение)

## Критерии с весами

| Требование | Реализация | Файлы | Проверка | Результат |
| --- | --- | --- | --- | --- |
| 5–6+ сервисов · 20% | Auth, Collector, Articles, Community, Moderation и Notifications со своими процессами и образами | [Compose](../compose.yaml), [сервисы](../services) | `verify-lab2.ps1` проверяет артефакты шести сервисов, отдельные ответы и девять контейнеров | PASS |
| Архитектура · 20% | Собственные данные, конфигурации, lifecycle и доменные API | [Архитектура](../docs/ARCHITECTURE.md), [схема](diagrams/architecture.md) | Проверки сборок этапов 2–5. При остановке Articles и Moderation остальные процессы остаются доступны | PASS |
| Взаимодействие · 15% | REST с иным контрактом для каждого владельца данных. AMQP для событий публикации | [HTTP-клиенты](../services/runtime/cybernews_runtime/service_client.py), [outbox](../services/articles/app/outbox.py) | `test_moderation_durable_command_retries_after_dependency_outage`, `test_outbox_survives_broker_downtime_and_late_subscriptions` | PASS |
| Database / persistence · 10% | Шесть БД и ролей PostgreSQL, Alembic и локальные ограничения | [Инициализация PostgreSQL](../infrastructure/postgres/10-initialize.sh), [данные](diagrams/databases.md) | `test_database_isolation_and_idempotent_migrations`, `test_comment_bookmark_and_notification_persist_after_restart` | PASS |
| API и документация · 10% | FastAPI и шесть Swagger/OpenAPI через Gateway, примеры команд | [Gateway](../gateway/default.conf.template), [API в README](README.md#api-и-права) | `verify-lab2.ps1` сверяет префикс, тип ответа, Swagger и отсутствие внутренних маршрутов. Регрессии проверяют модели и методы | PASS |
| Authentication / authorization · 5% | Argon2id, JWT, отзыв доступа, роль сервера и отдельная административная сессия | [Auth](../services/auth/app/api.py), [токены](../services/auth/app/tokens.py), [AdminClient](../services/runtime/cybernews_runtime/admin_client.py) | `test_rejects_invalid_jwt`, `test_admin_session_expiration_and_password_rotation`, `test_role_boundaries_and_revocation` | PASS |
| Logging / error handling · 10% | JSON, X-Request-ID, статусы API, тайм-ауты, отказ при потере проверяемой зависимости | [FastAPI runtime](../services/runtime/cybernews_runtime/application.py), [логирование](../services/runtime/cybernews_runtime/logs.py) | `verify-lab2.ps1` связывает запросы каждого сервиса с Gateway. `test_postgres_outage_preserves_liveness_and_catalog` проверяет 503 и восстановление | PASS |
| Тестирование · 10% | Pytest, PowerShell, Edge и WebKit с изоляцией операций записи | [Тесты](../tests), [скрипты](../scripts) | Полные регрессии и безопасная проверка [сводка](EVIDENCE.md) | PASS |

## Обязательные свойства и оформление

| Требование | Реализация | Файлы | Проверка | Результат |
| --- | --- | --- | --- | --- |
| Собственная ответственность и независимый запуск | Каждый Dockerfile запускает своё FastAPI-приложение с нужными зависимостями | [Dockerfile Auth](../services/auth/Dockerfile), [Dockerfile Notifications](../services/notifications/Dockerfile) | Отдельная сборка backend-образов в тестовых Compose-проектах | PASS |
| REST/gRPC API | REST со схемами Pydantic, Auth и остальные сервисы через собственные префиксы | [Основные операции](README.md#api-и-права) | Автотесты API и схема маршрутов шести сервисов | PASS |
| Разделение данных | Один сервер PostgreSQL, шесть баз, отсутствие межбазовых FK | [Диаграмма данных](diagrams/databases.md), [проверка PostgreSQL](../tests/postgres-smoke.sh) | Проверка грантов CONNECT и нерутовых сервисных ролей. Повтор миграций и рестарт на временных данных | PASS |
| Configuration management | Переменные окружения, общий шаблон и отдельные настройки сервисов | [Шаблон](../.env.example), [Compose](../compose.yaml), [конфигурация runtime](../services/runtime/cybernews_runtime/config.py) | `docker compose config --quiet`, сканирование Git index и рабочей конфигурации через `-SecretsOnly` | PASS |
| Health check endpoints | `/health` и `/ready` всех сервисов, `/health` Gateway | [Общий runtime](../services/runtime/cybernews_runtime/application.py), [Compose](../compose.yaml) | Read-only проверка и последовательности `200 → 503 → 200` у готовности во время изолированного отказа | PASS |
| Обработка типовых ошибок | Валидация, отказ в доступе, отсутствующие записи, сетевые тайм-ауты и сбои БД | [Доказательства](EVIDENCE.md#отказы-и-восстановление) | Регрессии pytest и Playwright, без выхода за пределы тестового проекта | PASS |
| API Gateway и асинхронность · рекомендации | Nginx, durable topic exchange, quorum queue, DLQ и идемпотентный потребитель | [Маршрутизация](../gateway/default.conf.template), [брокер](../services/runtime/cybernews_runtime/broker.py) | `test_duplicate_rabbit_event_and_invalid_version_are_handled`, `test_confirmed_persistent_message_survives_broker_restart_without_consumer` | PASS |
| Обоснование стека и компромиссов | Назначение и альтернативы технологий, различие локального и публичного стенда | [Технические решения](../docs/ARCHITECTURE.md#выбор-технологий-и-компромиссы), [отчёт](REPORT.md) | Сверка с кодом и ответы на защите | PASS |
| Самостоятельный README и структура пакета | Код лежит в корне, материалы и ссылки — в отдельной `lab2/` | [README лабораторной](README.md), [сценарий](DEMO.md), [вопросы](DEFENSE.md) | Проверка относительных ссылок и рендеринга диаграмм | PASS |
| Git и защита | История этапов, отдельный осмысленный коммит, демонстрация и ответы о решениях | [Чеклист](SUBMISSION_CHECKLIST.md), [сценарий](DEMO.md) | Сверка локальной и удалённой веток перед сдачей | PASS |

Отдельные ограничения публичного размещения и многорепличного запуска разобраны в [отчёте](REPORT.md). Закрытие лабораторной №2 подтверждает развёртывание в Compose.
