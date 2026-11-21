# Community и Notifications

Community хранит комментарии, реакции и избранное в `community_db`. Notifications хранит подписки и уведомления в `notification_db`. Articles записывает события о публикациях в `article_db` и передаёт их через RabbitMQ. Сервисы используют отдельные подключения к PostgreSQL.

## Community API

Публичный префикс — `/api/v1/community`. Для записи передайте `Authorization: Bearer …`. Гости могут читать опубликованные обсуждения, статистику и счётчики. Валидный Bearer добавляет поле `my_reaction`; для гостя оно равно `null`.

| Метод и путь | Назначение |
| --- | --- |
| `GET /articles/{article_id}/comments` | Опубликованные комментарии, `limit` (20 по умолчанию, максимум 100), `offset`, `sort=oldest\|newest`; ответ содержит `items` и `total` |
| `POST /articles/{article_id}/comments` | Создать комментарий с `{"body":"…"}`, ответ `201` |
| `GET /comments/{comment_id}` | Читать опубликованный комментарий |
| `PATCH /comments/{comment_id}` | Изменить текст собственного опубликованного комментария |
| `DELETE /comments/{comment_id}` | Логически удалить собственный комментарий, ответ `204`; повторное удаление безопасно |
| `GET /articles/{article_id}/reactions`, `GET /comments/{comment_id}/reactions` | `likes`, `dislikes`, `my_reaction` |
| `PUT /articles/{article_id}/reaction`, `PUT /comments/{comment_id}/reaction` | Установить или сменить реакцию с `{"reaction":"like"}` или `dislike`; возвращает счётчики |
| `DELETE /articles/{article_id}/reaction`, `DELETE /comments/{comment_id}/reaction` | Удалить свою реакцию и вернуть счётчики |
| `GET /bookmarks` | Личный список с `limit`, `offset`, UUID, датой, `available` и короткой ссылкой на доступную статью |
| `GET /articles/{article_id}/bookmark` | Проверить состояние своего избранного |
| `PUT /articles/{article_id}/bookmark`, `DELETE /articles/{article_id}/bookmark` | Добавить или удалить. При повторном добавлении дата не меняется. Удалять можно и связь со скрытой статьёй |
| `GET /articles/{article_id}/stats` | Число комментариев, обе реакции, своя реакция и состояние избранного |
| `POST /articles/stats` | Пакетная статистика до 100 UUID из `{"ids":[…]}`. Скрытые и неизвестные статьи исключаются. Гостевой `bookmarked=null` |

Никнейм сохраняется как снимок имени при публикации. Ответы содержат UUID автора, текст, дату создания, дату изменения, `edited`, `edited_at` и счётчики. Комментарии проходят очистку и хранятся как обычный текст с лимитом 1–5000 символов. Frontend должен отображать их через текстовые компоненты. Списки получают счётчики одним групповым запросом. Уникальный ключ «цель + пользователь» и PostgreSQL UPSERT защищают реакции и избранное от дубликатов при параллельных запросах.

Community проверяет JWT и состояние аккаунта через Auth. Перед созданием и изменением текста дополнительно проверяются публикация статьи через Articles и разрешение через Moderation. Запрет комментирования сохраняет право на удаление своего комментария. Скрытие статьи сохраняет комментарии и реакции в PostgreSQL, а публичные маршруты возвращают `404`. Избранное сохраняет связь со скрытой статьёй и показывает `available=false` с `article=null`. Лимиты на учётную запись за 60 секунд — 12 созданий, 30 правок, 120 изменений реакций и 60 изменений избранного. При превышении возвращается `429` и `Retry-After`.

Таблицы Community — `comments`, `article_reactions`, `comment_reactions`, `bookmarks`, `comment_moderation_history`, `community_rate_buckets`, `alembic_version`. Скрытые и удалённые комментарии сохраняют текст для уполномоченной модерации, публичные списки их исключают.

## Модерация комментариев и жалобы

Префикс административных действий — `/api/v1/moderation/comments`. Требуются Bearer и `X-Admin-Session`.

| Метод и путь | Доступ |
| --- | --- |
| `GET /comments`, `GET /comments/{id}` | Moderator и Super Admin. Список поддерживает `article_id`, `limit`, `offset` |
| `POST /comments/{id}/hide` | Moderator может скрывать комментарии User, Super Admin — комментарии всех ролей. Тело `{"reason":"…"}` |
| `POST /comments/{id}/restore` | Только Super Admin; требуется причина |
| `GET /comments/{id}/history` | Только Super Admin; пагинация истории |

Moderation сначала сохраняет команду в `comment_moderation_commands`. Укажите UUID в заголовке `Idempotency-Key`, чтобы повторить тот же запрос после сбоя. Community сохраняет изменение и уникальный результат команды в одной транзакции. Moderation записывает результат в `moderation_audit` только после подтверждения Community. При `503` ответ содержит ключ команды, а фоновый обработчик повторяет её с задержкой. Если изменение уже применено, Community вернёт сохранённый результат по тому же UUID. Самостоятельное повторное скрытие уже скрытого комментария возвращает `no_change`. Удалённый автором комментарий восстановлению не подлежит.

`POST /api/v1/moderation/reports` проверяет цель перед записью. Для `user` используется Auth, для `article` — опубликованная статья в Articles, для `comment` — опубликованный комментарий к опубликованной статье в Community. Недоступная или неизвестная цель возвращает `404`, недоступный сервис проверки — `503`. Уже сохранённые жалобы по-прежнему доступны для рассмотрения.

## Подписки и уведомления

Префикс — `/api/v1/notifications`. Все маршруты требуют действующего Bearer.

| Метод и путь | Назначение |
| --- | --- |
| `GET /subscriptions` | Текущие категории и даты подписки |
| `PUT /subscriptions/{category_id}`, `DELETE /subscriptions/{category_id}` | Идемпотентное управление подпиской по стабильному идентификатору категории Articles |
| `GET /` | Личные уведомления с `limit`, `offset`, `unread=true`, общим числом, UUID, временем, состоянием прочтения и доступностью статьи |
| `GET /unread-count` | Число своих непрочитанных уведомлений |
| `PATCH /{notification_id}/read` | Отметить своё уведомление прочитанным, ответ `204`. Чужое или неизвестное возвращает `404` |
| `POST /read-all` | Отметить все свои уведомления прочитанными, вернуть число изменённых |

Получатели — пользователи, у которых на момент обработки всё ещё есть подписка с `created_at <= event.created_at`. Подписка, созданная после события, и повторная подписка после отписки не добавляют старые уведомления. Отписка не удаляет полученные записи.

Notifications сохраняет только UUID статьи, категорию, тип, даты и UUID события. Заголовки запрашиваются пакетно из актуальных опубликованных статей. Для скрытой статьи список возвращает `available=false`, а поля `article_id`, `category` и `title` — `null`. Такое уведомление можно отметить прочитанным. Таблицы — `subscriptions`, `notifications`, `processed_events`, `alembic_version`.

## RabbitMQ и transactional outbox

| Компонент | Настройка |
| --- | --- |
| Topic exchange | `cybernews.events`, durable |
| Routing key | `article.published` |
| Очередь | `cybernews.notifications.article-published.v1`, durable quorum |
| Изоляция ошибочных событий | Durable exchange `cybernews.dead`, очередь `cybernews.notifications.dead.v1`, routing key `notifications.article-published.v1` |

Событие версии 1 сохраняет `event_id`, `event_type` со значением `article.published`, `event_version` со значением `1`, `article_id`, `category`, `source_id`, `published_at` и `created_at`. `source_id` и `published_at` могут быть `null`. `message_id` AMQP совпадает с UUID события, а `content_type` — `application/json`.

Первичная публикация RSS-статьи и публикация собственной статьи или черновика записывают `article_outbox` в одной транзакции со статьёй. Существующие опубликованные материалы помечены как уже опубликованные миграцией. Редактирование, восстановление и повторный импорт не добавляют строку. Outbox сохраняет UUID, основной снимок события, время попытки и подтверждение доставки. Dispatcher в контейнере Articles забирает доступную строку через `FOR UPDATE SKIP LOCKED`, отправляет persistent message с `mandatory` и ждёт publisher confirm. При сбое строка остаётся в outbox. Задержка после неудачной отправки растёт до 64 секунд. Articles продолжает обслуживать HTTP при недоступном брокере.

Notifications подтверждает доставку вручную после фиксации записи события и уведомлений одной транзакцией. Повтор по UUID события не создаёт уведомления второй раз. Повреждённые сообщения и неизвестные версии отклоняются в dead-letter очередь. При временной ошибке записи доставка повторяется с ограниченной задержкой до пяти попыток, затем сообщение отправляется в dead-letter очередь для разбора. Рабочая очередь допускает доставку не менее одного раза. После перезапуска брокера оба воркера переподключаются. Готовность Notifications учитывает PostgreSQL и подключение к RabbitMQ.

## Межсервисные ключи

`ARTICLE_READ_SECRET` используется только для внутренних проверок опубликованных статей и пакетного получения их заголовков. `COMMUNITY_MODERATION_SECRET` доступен Moderation и Community и защищает чтение целей жалоб, команды и историю модерации. `INTERNAL_AUTH_SECRET` используется для подтверждения личности и проверки разрешения комментирования. `ARTICLE_IMPORT_SECRET` по-прежнему ограничен импортом. Gateway закрывает `/internal/` и удаляет клиентский `X-Internal-Key`. Серверы игнорируют клиентские заголовки роли и идентификатора пользователя.

## Запуск и проверка в PowerShell

```powershell
.\scripts\init-env.ps1
docker compose up -d --build
docker compose exec -T articles alembic upgrade head
docker compose exec -T community alembic upgrade head
docker compose exec -T moderation alembic upgrade head
docker compose exec -T notifications alembic upgrade head

# При необходимости создайте окружение: python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r tests/stage3-requirements.txt
.\scripts\smoke-test-stage4.ps1 -PythonExe .\.venv\Scripts\python.exe
```

Изолированный smoke-тест использует отдельные PostgreSQL, RabbitMQ и динамический порт Gateway. RSS в тестовом стенде подменяется постоянными фикстурами. Рабочий каталог, очередь и учётные записи остаются в основном проекте.

Для ручной проверки получите обычный и административный Bearer по [инструкции Auth](AUTH_MODERATION_API.md). Ниже `$userHeaders` — заголовки подписчика, `$adminHeaders` — Bearer и административная сессия.

```powershell
$api = 'http://localhost:8080/api/v1'
Invoke-RestMethod "$api/notifications/subscriptions/research" -Method Put -Headers $userHeaders
$articleJson = @{
    title = 'Публикация CyberNews'; content = '<p>Собственный материал.</p>'
    category = 'research'; status = 'published'
} | ConvertTo-Json -Compress
$article = Invoke-RestMethod "$api/articles/admin/articles" -Method Post -Headers $adminHeaders `
    -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($articleJson))
$notice = (Invoke-RestMethod "$api/notifications/" -Headers $userHeaders).items |
    Where-Object { $_.article_id -eq $article.id } | Select-Object -First 1
if ($notice) {
    Invoke-RestMethod "$api/notifications/$($notice.id)/read" -Method Patch -Headers $userHeaders
}
$commentJson = @{ body = 'Мой комментарий' } | ConvertTo-Json -Compress
$comment = Invoke-RestMethod "$api/community/articles/$($article.id)/comments" -Method Post -Headers $userHeaders `
    -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($commentJson))
Invoke-RestMethod "$api/community/comments/$($comment.id)/reaction" -Method Put -Headers $userHeaders `
    -ContentType 'application/json' -Body '{"reaction":"like"}'
Invoke-RestMethod "$api/community/articles/$($article.id)/bookmark" -Method Put -Headers $userHeaders
```

Уведомление может появиться после первого запроса списка, поскольку доставка асинхронная. Через Swagger можно проверить [Community](http://localhost:8080/api/v1/community/docs), [Notifications](http://localhost:8080/api/v1/notifications/docs), [Articles](http://localhost:8080/api/v1/articles/docs) и [Moderation](http://localhost:8080/api/v1/moderation/docs).
