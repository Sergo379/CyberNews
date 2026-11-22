# Манифесты CyberNews для Kubernetes

Namespace — `cybernews-lab3`. `configmaps` содержит параметры, `storage` — отдельные PVC, `statefulsets` — PostgreSQL и RabbitMQ, `jobs` — Alembic, `deployments` и `services` — приложения и их сетевые адреса.

`networkpolicies` ограничивает ingress к HTTP API, PostgreSQL и RabbitMQ. Объявленные разрешения соответствуют направлению внутренних REST и AMQP-вызовов. Gateway для браузера доступен через `kubectl port-forward`.

Порядок зависит от готовности хранилищ и миграций. Его выполняет [lab3-deploy.ps1](../scripts/lab3-deploy.ps1). Он также генерирует ConfigMaps из исходных файлов PostgreSQL и RabbitMQ и синхронизирует локальные образы с containerd kind. Сборка образов, генерация локальных секретов и диагностика описаны в [руководстве лабораторной](../lab3/README.md).
