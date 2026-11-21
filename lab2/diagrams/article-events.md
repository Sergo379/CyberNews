# Событие первой публикации

```mermaid
sequenceDiagram
    participant A as Articles
    participant O as article_db и outbox
    participant D as Dispatcher
    participant R as RabbitMQ
    participant N as Notifications
    participant P as notification_db
    A->>O: Одна транзакция для первой публикации и outbox
    D->>O: Выбрать ожидающее событие с SKIP LOCKED
    D->>R: Устойчивое сообщение article.published
    alt Получено подтверждение RabbitMQ
        R-->>D: Publisher confirm
        D->>O: Отметить delivered_at
    else Ошибка брокера или сети
        D->>O: Строка остаётся в outbox для повтора
    end
    R->>N: Доставка, возможны повторы
    alt Событие прошло проверку
        N->>P: Одна транзакция для event_id и уведомлений
        P-->>N: Commit или уже обработанный event_id
        N-->>R: ACK после commit
    else Некорректное событие
        N-->>R: Reject без повтора, доставка в DLQ
    end
```

Уникальность `event_id` устраняет повторную обработку. При ошибке транзакции потребитель допускает ограниченное число повторов RabbitMQ. [Outbox](../../services/articles/app/outbox.py) · [Consumer](../../services/notifications/app/consumer.py) · [Топология](../../services/runtime/cybernews_runtime/broker.py)
