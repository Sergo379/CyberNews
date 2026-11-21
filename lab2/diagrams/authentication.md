# Авторизация

```mermaid
sequenceDiagram
    actor User as Браузер
    participant G as Nginx Gateway
    participant A as Auth
    participant DB as auth_db
    participant S as Защищённый сервис
    User->>G: POST auth/register
    G->>A: Регистрация
    A->>DB: Учётная запись и Argon2id
    User->>G: POST auth/login
    G->>A: Email и пароль
    A->>DB: Статус и проверка пароля
    A-->>User: Подписанный JWT через Gateway
    User->>G: Запрос с JWT
    G->>S: JWT и X-Request-ID
    S->>A: Защищённая внутренняя проверка
    A->>DB: Версия JWT, текущая роль и статус
    opt Административное действие
        User->>G: POST auth/admin/unlock с JWT и отдельным паролем
        G->>A: Проверка роли и пароля
        A->>DB: Хеш токена сессии, jti и срок
        A-->>User: Токен admin session через Gateway
        User->>G: JWT и X-Admin-Session
        G->>S: Два заголовка
        S->>A: Проверка сессии, JWT и полномочий
        A-->>S: Подтверждённая роль либо отказ
    end
```

Профиль и другие собственные операции Auth проверяются локально в Auth. Смена пароля, роли или статуса отзывает ранее выданный доступ. [Контракт Auth и Moderation](../../docs/AUTH_MODERATION_API.md)
