# Чеклист сдачи лабораторной №2

PASS обозначает выполненную проверку. NOT VERIFIED обозначает проверку, оставленную за пределами результата.

| Проверка | Статус | Где показать |
| --- | --- | --- |
| Шесть работающих backend-микросервисов, собственные API и ответственность | PASS | [Матрица](REQUIREMENTS_MATRIX.md), [архитектура](diagrams/architecture.md) |
| Шесть отдельных баз, гранты, миграции и сохранность после перезапуска | PASS | [Базы](diagrams/databases.md), [доказательства](EVIDENCE.md) |
| Межсервисный REST и fail closed | PASS | [Взаимодействие](diagrams/communication.md), [сценарии отказов](EVIDENCE.md#отказы-и-восстановление) |
| RabbitMQ, outbox, повтор доставки и DLQ | PASS | [Событие](diagrams/article-events.md), [тесты](../tests/test_stage4.py) |
| Gateway, health/readiness, Swagger и OpenAPI шести API | PASS | [Безопасная проверка](../scripts/verify-lab2.ps1) |
| JWT, дополнительные административные сессии и разграничение ролей | PASS | [Авторизация](diagrams/authentication.md), [тесты Auth](../tests/test_stage2.py) |
| Логирование без реквизитов и корреляция, обработка ошибок | PASS | [Протокол](EVIDENCE.md#журналы-и-rabbitmq) |
| Docker Compose, девять healthy | PASS | [Compose](../compose.yaml), [протокол](EVIDENCE.md#рабочий-стенд) |
| Автоматические backend-тесты и браузерные проверки | PASS | [Результаты](EVIDENCE.md#результаты-регрессии) |
| Отчёт, матрица, диаграммы и подтверждения | PASS | [Комплект](README.md#материалы-для-защиты) |
| Сценарий с отдельным стендом и 33 ответа для защиты | PASS | [DEMO](DEMO.md), [DEFENSE](DEFENSE.md) |
| Секреты вне Git и логов проверяемого набора | PASS | [Проверки безопасности](EVIDENCE.md#проверки-безопасности) |
| История Git и публикация на GitHub | PASS | [Репозиторий CyberNews](https://github.com/Sergo379/CyberNews) |
| Проверка на физическом iPhone, сканирование слоёв системных образов, многоузловой Kubernetes | NOT VERIFIED | [Границы проверки](REPORT.md#найденные-недостатки-и-остаточные-ограничения) |
