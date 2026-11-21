# Протокол проверок

Проверка 22 ноября 2026 года в Windows 11, Docker Desktop и Linux-контейнерах. Исходный SHA проекта `6dbe567ac52e636435fb785e81bfd31d8c2d2af3`. Рабочее дерево при старте было чистым. Тестовые записи, перезапуски зависимостей и повторные миграции выполнялись в отдельных проектах Compose.

## Рабочий стенд

```powershell
docker compose config --quiet
docker compose ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'
docker compose exec -T gateway nginx -t
.\scripts\verify-lab2.ps1
```

`verify-lab2.ps1` прошёл в Windows PowerShell 5.1 и PowerShell 7. Все девять контейнеров показали `healthy`. Проверены шесть Dockerfile, конфигурации, миграции и запуск приложений от непривилегированного пользователя. `/health` Gateway вернул JSON. `/` и `/admin/` вернули HTML с CSP и nosniff. У каждого из шести API ответили `/health`, `/ready`, Swagger и OpenAPI. Схемы содержали публичный префикс и исключали внутренние маршруты. Гостевые запросы к выбранным шести закрытым операциям получили 401, внутренние пути через Gateway — 404. Получен список из семи категорий.

| Показатель | До | После |
| --- | ---: | ---: |
| Пользователи | 1 | 1 |
| Опубликованные статьи | 75 | 76 |
| RSS-источники | 3 | 3 |
| Комментарии | 1 | 1 |
| Подписки | 0 | 0 |
| Уведомления | 0 | 0 |

Дополнительная статья пришла от BleepingComputer через штатный сбор RSS. Для сравнения использовались агрегаты COUNT в режиме чтения. Пользовательские поля, тексты комментариев и учётные данные не выгружались.

| Сервис | Состояние Alembic до и после |
| --- | --- |
| Auth | `0001_auth (head)` |
| Collector | `0001_collector (head)` |
| Articles | `0002_article_outbox (head)` |
| Community | `0001_community (head)` |
| Moderation | `0002_comment_commands (head)` |
| Notifications | `0001_notifications (head)` |

Проверка [PostgreSQL](../tests/postgres-smoke.sh) подтвердила, что все шесть сервисных ролей подключаются к своим UTF-8 базам и имеют CONNECT только к своей базе. Приложения закрыты от прямого доступа с хоста, а Gateway, PostgreSQL и RabbitMQ Management привязаны к IPv4 loopback. Начальный снимок зафиксировал 75 опубликованных статей, девять healthy и те же шесть ревизий. [Механизм миграций](../services/runtime/cybernews_runtime/migration.py).

## Браузерные доказательства

| Материал | Что подтверждает | Как воспроизвести |
| --- | --- | --- |
| [Рабочая лента](evidence/catalog.jpg) | Публичные RSS-статьи, категории и поиск, финальный счётчик 76 | Открыть [главную](http://localhost:8080/) как Guest в Edge, viewport 1440 × 900 |
| [Swagger Articles](evidence/swagger-articles.jpg) | Рабочий Swagger Articles и значение серверного префикса | Открыть [Swagger Articles](http://localhost:8080/api/v1/articles/docs), дождаться списка операций |

Swagger [Auth](http://localhost:8080/api/v1/auth/docs) и [Community](http://localhost:8080/api/v1/community/docs) воспроизводятся прямо из Gateway. Playwright проверял регистрацию, профиль, пользовательские функции, роли, скрытие комментариев, создание статьи, подписку и уведомление. Публичный сценарий открывал рабочую ленту, менял тему и язык, проверял History API и отсутствие горизонтального переполнения от 360 до 2560 px. Мобильные ширины проверены в эмуляции. Скрипт не фиксирует конкретный размер рабочего каталога.

## Журналы и RabbitMQ

Фактические обезличенные строки одной проверки `GET /api/v1/articles/health`. Часы в записях в UTC. `duration_ms` сервиса и `duration_seconds` Gateway имеют разные единицы.

```json
{"timestamp":"2026-11-21T23:04:45+00:00","service":"gateway","level":"info","request_id":"lab2-evidence-533c69d7","message":"HTTP request completed","method":"GET","status":200,"duration_seconds":0.004}
{"timestamp":"2026-11-21T23:04:45.919345+00:00","service":"articles","level":"INFO","request_id":"lab2-evidence-533c69d7","message":"HTTP request completed","method":"GET","status":200,"duration_ms":1.3}
```

Воспроизведение из PowerShell.

```powershell
$requestId = 'lab2-' + [Guid]::NewGuid().ToString('N')
Invoke-RestMethod 'http://localhost:8080/api/v1/articles/health' -Headers @{'X-Request-ID' = $requestId}
docker compose logs --no-color --no-log-prefix --tail 100 articles gateway | Select-String -SimpleMatch $requestId
docker compose exec -T rabbitmq sh -c 'rabbitmqctl -q list_queues -p "$RABBITMQ_DEFAULT_VHOST" name type durable'
```

На рабочем RabbitMQ проверены запуск узла, слушатели и авторизованное чтение `/api/overview` и списка очередей в Management. Список показал durable quorum `cybernews.notifications.article-published.v1` и durable classic `cybernews.notifications.dead.v1`. Для просмотра в интерфейсе откройте [Management](http://localhost:15672/) и вкладку **Queues and Streams** после локального входа. В изолированном тесте `test_confirmed_persistent_message_survives_broker_restart_without_consumer` подтверждённое сообщение дождалось запуска Notifications и породило уведомление. Тест `test_duplicate_rabbit_event_and_invalid_version_are_handled` подтвердил один результат при повторе события и поступление некорректного события в DLQ. [Интеграционные проверки](../tests/test_stage4.py).

## Результаты регрессии

| Группа | Итог |
| --- | --- |
| Этап 1 · инфраструктура | PASS. Рабочие HTTP, порты, БД, логи и брокер проверены на чтение. Изолированные PostgreSQL и RabbitMQ проверены на отказы и восстановление |
| Этап 2 · Auth и Moderation | 33 passed |
| Этап 3 · Collector и Articles | 48 passed |
| Этап 4 · Community, Moderation, Notifications и инфраструктура | 39 passed |
| Этап 5 · Edge | 4 passed в изоляции и 1 passed на рабочем каталоге |
| Этап 5 · WebKit | 4 passed в изоляции и 1 passed на рабочем каталоге |

Итого 130 успешных запусков тестов. Это 120 backend-тестов и 5 отдельных браузерных сценариев, повторённых на двух движках. Проверены 205 относительных Markdown-ссылок в 26 файлах репозитория. Mermaid CLI отрисовал шесть блоков из пяти файлов. [Входные файлы диаграмм](diagrams).

В режиме `-Demo` наблюдались запуск временного Gateway, интерактивное создание Super Admin со скрытым вводом, ответ `/health`, одна публикация по запросу `Acorn` и штатное завершение проекта после Enter. [Сценарий для защиты](DEMO.md).

Воспроизведение backend и Edge.

```powershell
py -3.12 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r tests\stage5-requirements.txt
.\scripts\smoke-test-stage2.ps1 -RunPytest -PythonExe $python
.\scripts\smoke-test-stage3.ps1 -PythonExe $python
.\scripts\smoke-test-stage4.ps1 -PythonExe $python
$env:CYBERNEWS_BROWSER_CHANNEL = 'msedge'
$env:CYBERNEWS_BROWSER_ENGINE = 'chromium'
.\scripts\smoke-test-stage5.ps1 -PythonExe $python
$env:CYBERNEWS_LIVE_READONLY_URL = 'http://localhost:8080'
& $python -m pytest -q tests\test_stage5.py -k live_catalog
```

Для WebKit установите браузер один раз. Затем повторите изолированный и read-only сценарии с тем же URL.

```powershell
& $python -m playwright install webkit
Remove-Item Env:CYBERNEWS_BROWSER_CHANNEL -ErrorAction SilentlyContinue
$env:CYBERNEWS_BROWSER_ENGINE = 'webkit'
.\scripts\smoke-test-stage5.ps1 -PythonExe $python
& $python -m pytest -q tests\test_stage5.py -k live_catalog
```

## Отказы и восстановление

| Сценарий в изоляции | Наблюдение и сохранность | Проверка |
| --- | --- | --- |
| PostgreSQL остановлен | Все шесть `/health` возвращают 200. `/ready` возвращают 503 до запуска и 200 после. Исходная статья возвращается без изменений | `test_postgres_outage_preserves_liveness_and_catalog` |
| Auth недоступен | Moderation возвращает 503. После восстановления Auth проверка разрешения на комментарий снова отвечает 200 | `smoke-test-stage2.ps1`, проверка Auth dependency failure |
| Articles недоступен | Community возвращает 503 при зависимых запросах. После восстановления читается список без отклонённых записей. Collector фиксирует ошибку импорта и сохраняет каталог | `test_article_outage_fails_closed`, `test_import_unavailable_and_persistence_after_restart` |
| Moderation недоступен | Создание и обновление комментария возвращают 503. Владелец может удалить свой комментарий через отдельную проверку Community. После восстановления создание снова возвращает 201 | `test_moderation_outage_fails_closed_but_deletion_works` |
| Community недоступен при модерации | Команда и ключ повтора сохраняются. Возвращается 503, после восстановления подтверждаются результат и аудит | `test_moderation_durable_command_retries_after_dependency_outage` |
| RabbitMQ недоступен | Статья сохраняется, одна строка ожидает в outbox. После восстановления брокера подписчик получает уведомление | `test_outbox_survives_broker_downtime_and_late_subscriptions` |
| RabbitMQ перезапущен до появления потребителя | Уже подтверждённое сообщение остается в очереди и обрабатывается после запуска Notifications | `test_confirmed_persistent_message_survives_broker_restart_without_consumer` |
| RSS вернул ошибку или не ответил | Фикстура HTTP 502 регистрируется как ошибка источника. Симулированный тайм-аут чтения классифицируется как `feed_timeout`. Независимые источники обрабатываются | `test_source_admin_controls_and_error_history`, `test_rss_read_timeout_is_reported`, `test_startup_keeps_other_feeds_running_after_xml_error` |
| Невалидный UUID или неизвестная статья | API возвращает 422 или 404 соответственно. Публичный список прежний | `test_pagination_search_filters_sort_and_missing` |
| Чужое уведомление или комментарий | Чужое уведомление не находится с токеном другого пользователя. Редактирование или удаление чужого комментария отклоняется. Записи остаются у владельца | `test_notifications_are_private_and_unread_count_is_idempotent`, `test_comment_owner_only` |
| Некорректный DTO или созданная клиентом роль | Возвращается 422. Регистрация и запись комментария не принимают служебные поля | `test_registration_validation_and_role_injection`, `test_comment_validation` |
| Истекла административная сессия | Операция получает 403 при действующем JWT. Браузер вновь запрашивает административный пароль | `test_admin_session_expiration_and_password_rotation`, `test_moderator_permissions_and_review` |
| Повтор события или некорректное сообщение | Уникальный event_id исключает дубликат, недопустимая версия попадает в DLQ | `test_duplicate_rabbit_event_and_invalid_version_are_handled` |
| Конкурентные команды | Одна активная блокировка, одна реакция пользователя и один совместимый запуск RSS | `test_duplicate_active_restriction_is_concurrency_safe`, `test_concurrent_reactions_have_one_active_row`, `test_parallel_manual_runs_have_one_winner` |
| Перезапуск с данными | Комментарий, закладка и прочитанное уведомление переживают перезапуск. Повтор `alembic upgrade head` сохраняет запись | `test_comment_bookmark_and_notification_persist_after_restart`, `test_database_isolation_and_idempotent_migrations` |

[Auth и роли](../tests/test_stage2.py) · [RSS API](../tests/test_stage3_api.py) · [RSS unit](../tests/test_stage3_unit.py) · [Брокер и зависимости](../tests/test_stage4.py) · [Браузер](../tests/test_stage5.py).

## Проверки безопасности

- **Полномочия.** В тестах проверены хеши Argon2id, неправильный и просроченный JWT, отозванный доступ после смены роли, пароля и блокировки, отсутствующий заголовок admin session, неверный административный пароль и полномочия Moderator. [Тесты Auth](../tests/test_stage2.py).
- **Границы ввода.** Проверены длина и тип полей, UUID, выдача чужих приватных записей, rate limiting, список допустимых RSS-хостов, отказ без соединения с закрытыми DNS-адресами, очистка HTML и текстовый вывод комментариев. Проверка SQL состояла в анализе привязки параметров в ORM и штатных тестах поиска и валидации. [RSS и очистка](../tests/test_stage3_unit.py) · [Community](../tests/test_stage4.py).
- **Журналы и Git.** В выборке из 1 400 строк рабочего Gateway и шести сервисов выполнен поиск 13 настроенных секретов, JWT и строк подключения с реквизитами. Совпадений не найдено. Тесты Auth дополнительно проверяют фактические временные токены и пароли в изолированной среде. Индекс и кандидаты репозитория проверены через `.\scripts\smoke-test.ps1 -SecretsOnly`.
- **Python.** `pip-audit --no-deps --disable-pip` с 36 уникальными зафиксированными runtime-требованиями сообщил `No known vulnerabilities found`. Сканер читает записи шести `services/*/requirements.txt`. Системные Docker-слои находятся вне этой проверки.

[Ограничения и итог](REPORT.md#найденные-недостатки-и-остаточные-ограничения).
