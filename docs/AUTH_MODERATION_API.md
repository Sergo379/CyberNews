# API пользователей и модерации

Auth и Moderation доступны через Gateway по префиксам `/api/v1/auth` и `/api/v1/moderation`. Здесь пути указаны относительно соответствующего префикса. Рабочие адреса Swagger UI — [Auth](http://localhost:8080/api/v1/auth/docs) и [Moderation](http://localhost:8080/api/v1/moderation/docs).

## Роли

| Действие | Guest | User | Moderator | Super Admin |
| --- | --- | --- | --- | --- |
| Регистрация, обычный вход, публичная диагностика | Да | Да | Да | Да |
| Свой профиль, пароль и отправка жалоб | — | Да | Да | Да |
| Дополнительный административный вход | — | — | Да | Да |
| Очередь жалоб, рассмотрение, список и история ограничений | — | — | Да | Да |
| Запрет комментирования | — | — | Только для User | Да |
| Снятие запрета комментирования | — | — | — | Да |
| Список пользователей, изменение чужой роли | — | — | — | Да |
| Полная блокировка и восстановление аккаунта User | — | — | — | Да |
| Просмотр аудита и статистики | — | — | Свои действия | Все действия |

Guest — состояние без авторизации. Публичная регистрация создаёт User. Операции с административными ролями требуют административной сессии действующего Super Admin. Изменение собственной роли и полная блокировка административного аккаунта запрещены. Чтобы ограничить обычный доступ бывшего администратора, действующий Super Admin сначала отзывает его роль. Перевод в роль User удаляет административный хеш. Смена роли аннулирует JWT и административные сессии целевого аккаунта. Первичное создание Super Admin выполняется интерактивной командой `docker compose exec auth python -m app.bootstrap`.

## Auth

| Метод и путь | Доступ и назначение |
| --- | --- |
| `POST /register` | Публичный. Принимает `email`, `nickname` от 3 до 32 символов и `password` от 12 до 128 символов. Возвращает профиль и `201`. Email и никнейм уникальны без учёта регистра |
| `POST /login` | Публичный. Принимает `email` и `password`. Возвращает `access_token`, `token_type` и `expires_in` |
| `GET /me` | Bearer. Возвращает профиль владельца токена |
| `PATCH /me` | Bearer. Обновляет `email` и/или `nickname` |
| `POST /change-password` | Bearer. Принимает `current_password` и `new_password`, отзывает действующие сессии и возвращает `204` |
| `PUT /admin/password` | Bearer администратора. Принимает `current_password` и отдельный `admin_password`, закрывает прежние административные сессии и возвращает `204` |
| `POST /admin/unlock` | Bearer администратора. Принимает `admin_password`, возвращает `admin_session` и `expires_at` |
| `GET /admin/session`, `POST /admin/lock` | Bearer и `X-Admin-Session`. Проверяют или закрывают текущую административную сессию |
| `GET /admin/users` | Super Admin. Возвращает список пользователей. Пагинация `limit` и `offset` |
| `GET /admin/user-search` | Moderator и Super Admin с действующей административной сессией. Параметр `q` ищет активных обычных пользователей по началу никнейма. Параметр `user_id` проверяет конкретный UUID обычного пользователя для модерации его комментария. Возвращает до 20 пар `id` и `nickname` |
| `PATCH /admin/users/{user_id}/role` | Super Admin. Принимает `role` и необязательную `reason`. Целевой пользователь после изменения роли входит заново |
| `POST /admin/users/{user_id}/suspend`, `POST /admin/users/{user_id}/restore` | Super Admin. Принимают `reason`. Восстановленный User входит заново |
| `GET /admin/audit` | Административная сессия. Возвращает записи аудита с пагинацией |

Профиль содержит UUID, email, никнейм, роль, статус, даты создания и обновления, а также дату последнего входа при её наличии. Auth хранит основной и административный пароли в виде отдельных хешей Argon2id. JWT подписан HS256. Сервер проверяет `sub`, `iat`, `exp`, `iss`, `aud`, `jti`, тип токена и версию авторизации. По умолчанию JWT живёт 15 минут, настройка ограничена 30 минутами. Административная сессия связана с конкретным JWT и истекает не позднее чем через 15 минут и не позднее JWT. В базе хранится SHA-256 административного токена. Повторный unlock для того же JWT заменяет его предыдущую административную сессию.

Попытки входа и административной разблокировки ограничены пятью на аккаунт за 60 секунд и общим лимитом на подключение к Auth. Через локальный Gateway общий лимит применяется ко всем запросам этого Gateway. При превышении сервер возвращает `429` с `Retry-After`. Для операций подтверждения пароля действуют отдельные лимиты.

## Moderation

| Метод и путь | Доступ и назначение |
| --- | --- |
| `GET /comment-permission` | Bearer. Возвращает право текущего пользователя комментировать |
| `POST /restrictions` | Административная сессия. Принимает `user_id` и `reason`, возвращает ограничение и `201`. Активное ограничение одного пользователя уникально |
| `GET /restrictions` | Административная сессия. Возвращает список с необязательным фильтром `active` |
| `GET /users/{user_id}/restrictions` | Административная сессия. Возвращает активные и снятые ограничения пользователя |
| `POST /restrictions/{restriction_id}/lift` | Super Admin. Принимает `reason`. Возвращает запись с датой снятия и UUID администратора |
| `POST /reports` | Bearer. Принимает `target_type` (`comment`, `article`, `user`), `target_id` (UUID), `reason` и необязательное `description`. Возвращает жалобу со статусом `pending` и `201` |
| `GET /reports`, `GET /reports/{report_id}` | Административная сессия. Возвращают очередь и конкретную жалобу. У очереди есть фильтр `status` |
| `PATCH /reports/{report_id}` | Административная сессия. Переводит `pending` в `reviewed` или `rejected`, принимает необязательную `reason` |
| `GET /admin/audit`, `GET /admin/stats` | Административная сессия. Возвращают журнал действий и количество операций по типам |

Ограничения комментирования бессрочные. Активный дубликат ограничения и повторная обработка завершённой жалобы возвращают `409`. Существование пользователя проверяется через Auth, а проверка UUID статьи и комментария появится при интеграции соответствующих сервисов. Списки используют `limit` и `offset` с диапазоном размера страницы 1–100.

При создании жалобы Moderation проверяет существование пользователя через Auth, опубликованной статьи через Articles или опубликованного комментария через Community. Скрытые, неопубликованные и неизвестные цели возвращают `404`, сбой сервиса проверки — `503`. Существующие жалобы сохраняются для рассмотрения.

Оба журнала хранят UUID записи, администратора и объекта, действие, время, причину, результат и `request_id`. Auth также хранит прежнюю и новую роль для событий смены полномочий. Записи создаются в транзакции со связанным изменением. Для команд Community событие Moderation фиксируется в транзакции с подтверждённым результатом. [Маршруты и история модерации комментариев](COMMUNITY_NOTIFICATIONS_API.md).

## Примеры PowerShell

Запустите стек и создайте первого Super Admin. Пароли вводятся интерактивно. Для следующих запросов определите вспомогательную функцию.

```powershell
docker compose exec auth python -m app.bootstrap

$api = 'http://localhost:8080/api/v1'
function Send-Json($Method, $Path, $Body, $Headers = @{}) {
    Invoke-RestMethod -Method $Method -Uri "$api/$Path" -Headers $Headers `
        -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Compress)
}
function Read-Password($Prompt) {
    $value = Read-Host $Prompt -AsSecureString
    [Net.NetworkCredential]::new('', $value).Password
}

$member = Send-Json Post 'auth/register' @{
    email = (Read-Host 'Email нового пользователя')
    nickname = (Read-Host 'Никнейм')
    password = (Read-Password 'Основной пароль нового пользователя')
}
$memberLogin = Send-Json Post 'auth/login' @{
    email = $member.email
    password = (Read-Password 'Основной пароль пользователя')
}
$userHeaders = @{ Authorization = "Bearer $($memberLogin.access_token)" }
Invoke-RestMethod "$api/auth/me" -Headers $userHeaders

$rootLogin = Send-Json Post 'auth/login' @{
    email = (Read-Host 'Email Super Admin')
    password = (Read-Password 'Основной пароль Super Admin')
}
$adminHeaders = @{ Authorization = "Bearer $($rootLogin.access_token)" }
$unlocked = Send-Json Post 'auth/admin/unlock' @{
    admin_password = (Read-Password 'Административный пароль Super Admin')
} $adminHeaders
$adminHeaders['X-Admin-Session'] = $unlocked.admin_session
Invoke-RestMethod "$api/auth/admin/session" -Headers $adminHeaders
```

Ограничение и жалобу можно проверить на зарегистрированном пользователе. Для жалобы на статью или комментарий передавайте UUID объекта соответствующего типа.

```powershell
$restriction = Send-Json Post 'moderation/restrictions' @{
    user_id = $member.id; reason = 'Нарушение правил'
} $adminHeaders
Invoke-RestMethod "$api/moderation/comment-permission" -Headers $userHeaders
Send-Json Post "moderation/restrictions/$($restriction.id)/lift" @{
    reason = 'Ограничение пересмотрено'
} $adminHeaders

$report = Send-Json Post 'moderation/reports' @{
    target_type = 'user'; target_id = $member.id; reason = 'Проверка обращения'
} $userHeaders
Send-Json Patch "moderation/reports/$($report.id)" @{ status = 'reviewed' } $adminHeaders

Send-Json Post "auth/admin/users/$($member.id)/suspend" @{ reason = 'Нарушение правил' } $adminHeaders
Send-Json Post "auth/admin/users/$($member.id)/restore" @{ reason = 'Решение пересмотрено' } $adminHeaders
```

Для назначения Moderator Super Admin меняет роль. Назначенный пользователь получает новый Bearer после входа, задаёт собственный административный пароль и разблокирует административную сессию. Чтобы отозвать полномочия, передайте `role = 'user'` в тот же маршрут.

```powershell
Send-Json Patch "auth/admin/users/$($member.id)/role" @{
    role = 'moderator'; reason = 'Назначение модератора'
} $adminHeaders

$modLogin = Send-Json Post 'auth/login' @{
    email = $member.email
    password = (Read-Password 'Основной пароль модератора')
}
$modHeaders = @{ Authorization = "Bearer $($modLogin.access_token)" }
Send-Json Put 'auth/admin/password' @{
    current_password = (Read-Password 'Основной пароль модератора')
    admin_password = (Read-Password 'Индивидуальный административный пароль')
} $modHeaders
$session = Send-Json Post 'auth/admin/unlock' @{
    admin_password = (Read-Password 'Административный пароль модератора')
} $modHeaders
$modHeaders['X-Admin-Session'] = $session.admin_session
Invoke-RestMethod "$api/moderation/reports?status=pending" -Headers $modHeaders
Invoke-RestMethod "$api/auth/admin/lock" -Method Post -Headers $modHeaders
```

## Контракты сервисов и frontend

**Community.** После подтверждения Bearer в Auth сервис обращается к `GET http://moderation:8000/internal/v1/comment-permission/{user_id}` с `X-Internal-Key` и `X-Request-ID`. Ответ содержит `user_id`, `allowed` и причину. Только `allowed: true` разрешает создание и правку комментария. `GET http://auth:8000/internal/v1/principal` проверяет Bearer и возвращает UUID, актуальные роль, статус и никнейм. Параметр `require_admin=true` требует действующую административную сессию. Внутренний endpoint `GET /internal/v1/users/{user_id}` возвращает UUID, роль и статус.

**Frontend, этап 5.** Используйте публичные маршруты Gateway и OpenAPI. Учитывайте `401` для недействительного Bearer, `403` для недостающих административных прав или сессии, `409` для конфликта, `429` для лимита и `503` для недоступной зависимости. Интерфейс `/admin` должен повторно запросить отдельный пароль при истечении сессии и вызвать `POST /admin/lock` при выходе из административного режима. Локализуйте статусы и сообщения интерфейса RU/EN по статусу ответа и стабильным значениям API.
