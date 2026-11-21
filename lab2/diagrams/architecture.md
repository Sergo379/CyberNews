# Общая архитектура

Шесть приложений FastAPI собираются в отдельные образы. Браузер обращается к единому Nginx Gateway, который также раздаёт статический интерфейс. PostgreSQL и RabbitMQ работают отдельными контейнерами.

```mermaid
flowchart LR
    UI["Браузер"]
    G["Nginx · интерфейс и Gateway"]
    UI -->|"HTTP на loopback"| G
    subgraph Services["Шесть бизнес-микросервисов"]
        A["Auth"]
        C["Collector"]
        R["Articles"]
        U["Community"]
        M["Moderation"]
        N["Notifications"]
    end
    subgraph DB["Один PostgreSQL · шесть баз"]
        DA[("auth_db")]
        DC[("collector_db")]
        DR[("article_db")]
        DU[("community_db")]
        DM[("moderation_db")]
        DN[("notification_db")]
    end
    G --> A & C & R & U & M & N
    A --> DA
    C --> DC
    R --> DR
    U --> DU
    M --> DM
    N --> DN
    RSS["Внешние RSS и Atom"] --> C
    R -->|"Публикация события"| Q["RabbitMQ"]
    Q -->|"Доставка события"| N
```

[Compose](../../compose.yaml) · [Взаимодействие](communication.md)
