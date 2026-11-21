# RSS и каталог новостей

Collector загружает RSS 2.0 и Atom, сохраняет источники и историю попыток в `collector_db`. Articles принимает нормализованные записи через внутренний HTTP API, хранит каталог в `article_db` и отдаёт его через Gateway. Каждый сервис изменяет только свою базу.

## Источники и расписание

| Источник | RSS | Начальный режим |
| --- | --- | --- |
| The Hacker News | [RSS](https://feeds.feedburner.com/TheHackersNews) | `external_source` |
| BleepingComputer | [RSS](https://www.bleepingcomputer.com/feed/) | `external_source` |
| Krebs on Security | [RSS](https://krebsonsecurity.com/feed/) | `external_source` |

Первый запуск Collector ставит автоматическую задачу в очередь. Следующие циклы запускаются через `RSS_SYNC_INTERVAL_SECONDS`, по умолчанию каждые 1800 секунд. `RSS_AUTO_SYNC=false` отключает автоматическое расписание, сохраняя ручной запуск. В Compose Collector работает в одной реплике. При переносе в Kubernetes сохраняйте одну реплику планировщика и общий PostgreSQL: advisory lock и частичный уникальный индекс защищают от повторного запуска.

Ручной и автоматический запуск используют общую очередь PostgreSQL. `202` означает, что задача поставлена в очередь, `409` — что уже есть ожидающая или выполняемая задача либо что выбранный источник отключён. При остановке планировщик заканчивает текущий ограниченный по времени запрос и сохраняет статус. После аварийного завершения следующая реплика отмечает незавершённую попытку `interrupted`. Результат сохраняется для каждого источника отдельно. Ошибки HTTP, DNS, XML и импорта записываются безопасным диагностическим кодом. Сбой одного источника оставляет остальные доступными. Неудачный импорт повторяется в следующем обычном или ручном цикле. Повторный запрос для временного сбоя подключения ограничен двумя проверенными IP.

Collector соединяется только по HTTP или HTTPS на порту по умолчанию. Каждый хост, включая перенаправления, должен быть в `RSS_ALLOWED_HOSTS`. Это список точных публичных доменов, которые добавляются оператором после проверки. При каждой загрузке и переадресации Collector проверяет все полученные DNS-адреса и соединяется с проверенным публичным IP, сохраняя исходные Host, TLS SNI и проверку сертификата. У HTTPS отключён переход на HTTP; предел — четыре перенаправления. Максимальный размер RSS задаёт `RSS_MAX_BYTES` (по умолчанию 2 МиБ). Клиент запрашивает несжатый ответ, использует отдельный User-Agent и ограничивает время и объём загрузки. ETag и Last-Modified привязаны к конечному URL и обновляются после успешного импорта. Заголовки внутренней авторизации используются только для внутренних REST-запросов.

## Данные и публикация

- `rss_sources` содержит UUID, название, RSS-адрес, сайт, язык, активность, состояние, счётчик, даты и политику использования контента.
- `rss_sync_runs` и `rss_source_runs` хранят историю запусков и результаты по каждому источнику. `collector_audit` хранит административные действия.
- `articles` содержит UUID, заголовок, краткое описание, разрешённый HTML, автора, категорию, оригинальный язык, ссылки, GUID, даты и статус. `categories` хранит стабильные идентификаторы для будущей локализации.
- `article_url_keys` и `article_guid_keys` защищают от дубликатов. `article_source_policies` хранит версию подтверждённой политики источника. `article_audit` хранит действия редакторов.

Для UUID статьи используется один каталог. Импорт последовательно фиксируется в транзакции PostgreSQL, уникальные ключи вычисляются из нормализованной ссылки и пары `(source_id, GUID)`. Нормализация убирает известные tracking-параметры и сохраняет порядок и значения значимых параметров. Поле `original_url` хранит исходную ссылку на конкретную публикацию. При конфликте уже связанных URL и GUID импорт сообщает `conflicted` и сохраняет оба прежних UUID. Повторная загрузка обновляет данные источника, сохраняя идентификатор, редакторские изменения и статус скрытия. Дата из RSS преобразуется в UTC. При её отсутствии `published_at` имеет значение `null`; `collected_at` содержит время получения.

Для внешней записи без подтверждения используются `external_source`, заголовок, краткая выдержка из предоставленного RSS-описания (до 320 символов) и ссылка на оригинал. Поля `content` и `image_url` отсутствуют по значению, если соответствующие права не подтверждены. Интерфейс может показать текст «Полный текст статьи доступен на сайте первоисточника» по `content_mode`. Повтор всего текста RSS в поле описания отбрасывается.

`full_article` применяется к собственным материалам CyberNews, а также к материалам из RSS с документированным разрешением. Super Admin передаёт ссылку или номер подтверждающего документа в `rights_reference`. Разрешение на изображения указывается отдельно в `allow_images` и должно быть покрыто тем же документом. Запись настройки представляет подтверждение принятых редактором прав. При изменении или отзыве разрешения Collector синхронно применяет новую версию политики в Articles. Сервис убирает контент, переставший быть разрешённым, и отклоняет импорт со старой версией. Подходящая структура HTML сохраняется, скрипты, обработчики событий и опасные атрибуты отфильтровываются. Frontend показывает заголовки и описания как текст и использует только очищенное поле `content` для отображения HTML.

Одна основная категория выбирается по первому совпавшему правилу из заголовка, сокращённого описания и RSS-категорий. Порядок правил следующий: Vulnerabilities, Malware, Data Breaches, Cyberattacks, Research, Software Security, Other. Редактор может назначить категорию вручную. Поиск по заголовку и описанию использует PostgreSQL `websearch_to_tsquery` и GIN-индекс. Конфигурация `simple` работает с оригинальными словами RU/EN без перевода.

## REST API

Ранее доступные `/health`, `/ready`, `/docs` и `/openapi.json` сохранены. Административные пути требуют токена `Authorization: Bearer …` и `X-Admin-Session` Super Admin. Публичный каталог возвращает только опубликованные статьи.

| Метод и путь Articles | Назначение |
| --- | --- |
| `GET /api/v1/articles/`, `GET /api/v1/articles/search` | Список и поиск. Параметры `q`, `category`, `source_id`, `published_from`, `published_to`, `sort=newest|oldest`, `limit`, `offset`. Ответ содержит `items`, `total`, `limit`, `offset`. Записи без даты идут в конце |
| `GET /api/v1/articles/{id}` | Детали статьи с `content_mode`, очищенным `content` или `null` и `original_url`. Неизвестная, скрытая и неопубликованная статья возвращают `404` |
| `GET /api/v1/articles/categories`, `GET /api/v1/articles/sources` | Категории и источники опубликованного каталога. Источник локальных статей CyberNews имеет `id: null` |
| `GET /api/v1/articles/admin/articles` | Список публикаций, включая черновики и скрытые. Поддерживаются `status`, `limit`, `offset` |
| `POST /api/v1/articles/admin/articles` | Создание собственной статьи. `title` и `content` обязательны. По умолчанию `status=draft`. `status=published` публикует сразу |
| `PATCH /api/v1/articles/admin/articles/{id}` | Редактирование. Полный текст внешних статей поступает из лицензированного RSS |
| `POST /api/v1/articles/admin/articles/{id}/hide`, `/restore` | Скрытие и восстановление предыдущего состояния |
| `GET /api/v1/articles/admin/audit` | Журнал редакторских действий |

| Метод и путь Collector | Назначение |
| --- | --- |
| `GET /api/v1/collector/sources`, `POST /api/v1/collector/sources` | Список источников с состоянием и создание. При создании укажите `name`, `feed_url`, `website_url` и при необходимости `language` |
| `PATCH /api/v1/collector/sources/{source_id}` | Настройки источника, активность, `content_policy`, `rights_reference`, `allow_images` |
| `POST /api/v1/collector/sync`, `POST /api/v1/collector/sources/{source_id}/sync` | Постановка в очередь синхронизации всех активных или одного активного источника |
| `GET /api/v1/collector/status` | Состояние планировщика, интервал и последний запуск |
| `GET /api/v1/collector/runs`, `GET /api/v1/collector/runs/{run_id}` | История с пагинацией и подробности по источникам. Счётчики `seen`, `skipped`, `created`, `updated`, `unchanged`, `conflicted` |
| `GET /api/v1/collector/admin/audit` | Журнал изменений источников и ручных запусков |

Внутри сети Compose Collector и Articles подтверждают роль через `GET /internal/v1/principal?require_admin=true` Auth. Collector передаёт до 20 записей в `POST http://articles:8000/internal/v1/import` и обновляет политику через `PUT /internal/v1/sources/{source_id}/policy`. Оба запроса защищены отдельным `ARTICLE_IMPORT_SECRET` в заголовке `X-Internal-Key`. Nginx закрывает внутренние маршруты и удаляет переданный снаружи `X-Internal-Key`. `X-Request-ID` связывает HTTP-запрос, запуск синхронизации, операции импорта и JSON-логи.

## PowerShell

Поиск и открытие первого результата доступны без авторизации.

```powershell
$api = 'http://localhost:8080/api/v1'
$query = [Uri]::EscapeDataString('malware')
$page = Invoke-RestMethod "$api/articles/?q=$query&limit=5&sort=newest"
$page.items | Select-Object id, title, category, published_at
if ($page.items.Count) {
    Invoke-RestMethod "$api/articles/$($page.items[0].id)"
}
```

Для ручной синхронизации используйте рабочую административную сессию. Как получить токен и административную сессию, описано в [руководстве Auth](AUTH_MODERATION_API.md).

```powershell
$headers = @{
    Authorization = "Bearer $($rootLogin.access_token)"
    'X-Admin-Session' = $unlocked.admin_session
}
$run = Invoke-RestMethod "$api/collector/sync" -Method Post -Headers $headers
Invoke-RestMethod "$api/collector/runs/$($run.id)" -Headers $headers
```

Для одного источника используйте `POST $api/collector/sources/{source_id}/sync`. UUID можно получить из `GET $api/collector/sources`. На странице подробностей запуска повторяйте запрос до конечного статуса `completed`, `partial`, `failed` или `interrupted`.

Публикация собственной статьи выполняется теми же административными заголовками.

```powershell
$body = @{
    title = 'Отчёт CyberNews'
    category = 'research'
    language = 'ru'
    status = 'published'
    content = '<h2>Результаты</h2><p>Текст собственного материала.</p>'
} | ConvertTo-Json
Invoke-RestMethod "$api/articles/admin/articles" -Method Post -Headers $headers `
    -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

## Миграции и проверка

```powershell
.\scripts\init-env.ps1
docker compose up -d --build
docker compose exec -T collector alembic upgrade head
docker compose exec -T articles alembic upgrade head
docker compose exec -T collector alembic check
docker compose exec -T articles alembic check

.\.venv\Scripts\python.exe -m pip install -r tests/stage3-requirements.txt
.\scripts\smoke-test-stage3.ps1 -PythonExe .\.venv\Scripts\python.exe
```

Создайте `.venv` через `python -m venv .venv`, если её ещё нет. Тесты используют локальные XML-фикстуры и подмену HTTP-транспорта только в отдельном Compose-проекте. Обычный Docker Compose активирует реальные RSS. Результаты фактической загрузки проверяются по логам Collector, списку `/articles/` и запросам к таблицам `rss_source_runs` и `articles`.

## Будущее событие RabbitMQ

Контракт `article.published` версии 1 предназначен для первого перехода статьи в опубликованное состояние. Доставка и transactional outbox относятся к этапу №4.

| Поле | Тип и смысл |
| --- | --- |
| `event_id` | UUID события для дедупликации доставки |
| `event_type` | `article.published` |
| `event_version` | Целое число `1` |
| `article_id` | UUID статьи |
| `category` | Стабильный идентификатор категории |
| `source_id` | UUID источника или `null` для материала CyberNews |
| `published_at` | Дата публикации в UTC или `null`, если RSS её не указал |
| `created_at` | Время создания события в UTC |
