# Владельцы данных

Стрелка указывает единственную базу приложения. Идентификаторы из других сервисов передаются по контрактам HTTP или в событиях. Внешние ключи SQL связывают таблицы только внутри базы владельца.

```mermaid
flowchart LR
    A["Auth"] --> AData[("auth_db · аккаунты, admin sessions и аудит")]
    C["Collector"] --> CData[("collector_db · RSS-источники и синхронизации")]
    R["Articles"] --> RData[("article_db · статьи, категории и outbox")]
    U["Community"] --> UData[("community_db · комментарии, реакции и закладки")]
    M["Moderation"] --> MData[("moderation_db · жалобы, ограничения, команды и аудит")]
    N["Notifications"] --> NData[("notification_db · подписки, события и уведомления")]
```

Роль каждого сервиса владеет только своей базой. Для подключения к PostgreSQL применяются отдельные учётные данные. [Инициализация PostgreSQL](../../infrastructure/postgres/10-initialize.sh) · [Проверка доступа](../../tests/postgres-smoke.sh)
