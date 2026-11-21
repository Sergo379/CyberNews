# Межсервисное взаимодействие

Клиентский доступ идёт через Gateway. Сервисы обращаются друг к другу по DNS-именам в сети Compose.

```mermaid
flowchart LR
    C["Collector"] -->|"Нормализованный импорт и политика"| R["Articles"]
    U["Community"] -->|"Идентификация пользователя"| A["Auth"]
    U -->|"Проверка доступности публикации"| R
    U -->|"Разрешение комментирования"| M["Moderation"]
    M -->|"Проверка администратора и цели"| A
    M -->|"Проверка цели жалобы"| R
    M -->|"Проверка цели и команды модерации"| U
    N["Notifications"] -->|"Идентификация пользователя"| A
    N -->|"Доступность публикаций"| R
    C -->|"Проверка Super Admin"| A
    R -->|"Проверка Super Admin"| A
```

```mermaid
flowchart LR
    A[("Outbox Articles")] -->|"AMQP · article.published"| Q["RabbitMQ"]
    Q -->|"Доставка и подтверждение"| N["Notifications"]
    N --> DB[("Запись события и уведомлений")]
```

[Внутренние REST-клиенты](../../services/runtime/cybernews_runtime/service_client.py) · [Доставка события](article-events.md)
