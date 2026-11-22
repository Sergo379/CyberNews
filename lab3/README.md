# Лабораторная работа №3. Docker и Kubernetes

Цель — перенести готовый CyberNews в Kubernetes и показать управление репликами, сетевой доступ, проверки готовности и сохранность состояния. [Методичка PAD](https://github.com/Randwow/PAD#лабораторная-работа-3-docker-и-kubernetes) · [Матрица требований](REQUIREMENTS_MATRIX.md).

Рабочий [Docker Compose](http://localhost:8080/) и [версия Kubernetes](http://127.0.0.1:18080/) используют одну кодовую базу и отдельные данные. Kubernetes создаёт свои базы, аккаунты, очереди и секреты в пространстве `cybernews-lab3`. Для доступа к Kubernetes нужен запущенный port-forward.

## Материалы защиты

- [Отчёт](REPORT.md), [доказательства](EVIDENCE.md), [сценарий на 10 минут](DEMO.md), [40 ответов](DEFENSE.md).
- [Архитектура](diagrams/kubernetes-architecture.md), [сеть](diagrams/networking.md), [хранилища](diagrams/storage.md), [масштабирование](diagrams/scaling.md) и [восстановление](diagrams/recovery.md).
- [Манифесты](../k8s/README.md), [приложение из лабораторной №2](../lab2/README.md).

## Подготовка Windows 11

1. Запустите Docker Desktop в режиме Linux containers. Нужны Docker CLI с BuildKit, `kubectl` и Windows PowerShell 5.1 или PowerShell 7.
2. В Docker Desktop откройте Kubernetes → Create cluster. Для проверенной конфигурации выберите встроенный kind с одним узлом, затем создайте кластер. Хранилище образов Docker Desktop и runtime узла проверяются отдельно. [Инструкция Docker](https://docs.docker.com/desktop/use-desktop/kubernetes/).
3. Проверьте текущий контекст и default StorageClass. Скрипты ограничены доверенным локальным контекстом `docker-desktop`, Ready-узлом Docker Desktop и namespace лабораторной.

```powershell
docker desktop kubernetes status
kubectl config current-context
kubectl --context docker-desktop get nodes
kubectl --context docker-desktop get storageclass
```

## Сборка и развёртывание

Выполните из корня CyberNews.

```powershell
.\scripts\lab3-build.ps1
.\scripts\lab3-init-secrets.ps1
.\scripts\lab3-deploy.ps1
```

Сборка использует шесть существующих Dockerfile с build context `runtime=./services/runtime`. Backend-образы `cybernews/{service}:lab3` запускаются с UID 10001. Отдельный образ `cybernews/gateway:lab3` включает HTML, CSS, JavaScript, RU/EN и favicon и запускается с UID 101. Дизайн и маршруты совпадают с Compose. Для встроенного kind deploy сверяет идентификаторы образов через CRI и импортирует отсутствующие или обновлённые образы в containerd узла. Старт Jobs и Pods подтверждает доступ к локальным образам с `imagePullPolicy: Never`.

Deploy создаёт Namespace, ConfigMaps и Secrets, затем два PVC, Services и StatefulSets. Готовность PostgreSQL и RabbitMQ проверяется до старта шести Alembic Jobs. После завершения всех Jobs применяются Services и Deployments приложений. Каждый Job выполняет `alembic upgrade head` для собственной базы. Основные Pods стартуют с `python -m cybernews_runtime`. Повторный deploy создаёт новые Jobs, сверяет уже существующие credentials и сохраняет PVC.

Параметры без секретов лежат в [ConfigMaps](../k8s/configmaps). `backend-config` задаёт PostgreSQL и логирование. Карты сервисов задают имена баз и ролей, адреса REST, TTL токенов, параметры RSS и брокера. `postgres-init` и `rabbitmq-runtime` создаются из файлов существующей инфраструктуры, окончания строк нормализуются до LF. `gateway-config` задаёт порт upstream. Namespace поступает в Gateway из Downward API, сервер DNS и домен Services — из `/etc/resolv.conf` самого Pod.

[Шаблон секретов](../secrets/lab3.env.example) содержит только имена. Генератор создаёт `secrets/lab3.env` с уникальными 32-байтными случайными значениями. Deploy формирует восемь неизменяемых Secrets и передаёт их через stdin kubectl. StatefulSets и backend/Job читают собственные Secret references. Kubernetes Secret кодирует значения в Base64 при передаче ресурса. Шифрование etcd и управление доступом к кластеру относятся к отдельной конфигурации.

## Ресурсы и доступ

| Компонент | Контроллер | Сервис и порт | CPU request / limit | RAM request / limit |
| --- | --- | --- | --- | --- |
| Auth, Collector, Articles, Community, Moderation, Notifications | Отдельный Deployment, по 1 реплике | Шесть ClusterIP на 8000 | 100m / 500m | 128Mi / 512Mi |
| Nginx Gateway | Deployment, 1 реплика | `gateway`, 8080 | 50m / 500m | 32Mi / 128Mi |
| PostgreSQL | StatefulSet, 1 реплика | `postgres` и `postgres-headless`, 5432 | 250m / 1 | 256Mi / 768Mi |
| RabbitMQ | StatefulSet, 1 реплика | `rabbitmq`, 5672 и 15672, и `rabbitmq-headless`, 5672 | 250m / 1 | 512Mi / 1Gi |
| Alembic | Шесть Jobs | Без Service | 50m / 350m | 64Mi / 256Mi |

Два RWO PVC по 2 GiB привязываются через default `standard`, provisioner `rancher.io/local-path`. PostgreSQL хранит шесть баз в `PGDATA` внутри своего PVC. Официальный entrypoint запускает инициализацию при пустом каталоге. RabbitMQ сохраняет идентичность `rabbit@rabbitmq-0` и состояние в своём PVC. Локальные PV сохраняют состояние после замены Pod на этом узле. Перенос на другой узел, потеря диска и удаление PVC с reclaim policy `Delete` требуют отдельной стратегии.

Во втором PowerShell запустите port-forward и оставьте его открытым.

```powershell
kubectl --context docker-desktop -n cybernews-lab3 port-forward svc/gateway 18080:8080 --address 127.0.0.1
```

Откройте [главную](http://127.0.0.1:18080/), [админ-панель](http://127.0.0.1:18080/admin/) или [Swagger Auth](http://127.0.0.1:18080/api/v1/auth/docs). Остальные Swagger находятся по `/api/v1/{service}/docs`. Backend, PostgreSQL и RabbitMQ используют внутренние ClusterIP. Gateway блокирует служебные маршруты и поддерживает прямые ссылки SPA. NetworkPolicy ограничивает входящий трафик и разрешает используемые внутренние связи. Collector сохраняет исходящий доступ к RSS. [Правила ingress](../k8s/networkpolicies/ingress.yaml).

Для чистого стенда создайте первого администратора через скрытые интерактивные запросы CLI.

```powershell
kubectl --context docker-desktop -n cybernews-lab3 exec -it deployment/auth -- python -m app.bootstrap
```

Collector начинает отдельный RSS-сбор после запуска. При недоступном внешнем RSS Super Admin может опубликовать собственную демонстрационную статью. Рабочий каталог Compose в Kubernetes не импортируется.

## Проверки

```powershell
.\scripts\lab3-verify.ps1
.\scripts\lab3-demo.ps1
.\scripts\verify-lab2.ps1
```

`lab3-verify.ps1` читает состояние объектов, endpoint-адреса, схемы Alembic и HTTP. `lab3-demo.ps1` масштабирует Community, подтверждает распределение запросов по журналам всех трёх Pods, удаляет одну реплику за раз и восстанавливает исходный масштаб. Штатные probes у backend используют `/health` для liveness и startup и `/ready` для readiness. Gateway проверяется через `/health`, PostgreSQL через `pg_isready`, RabbitMQ через `rabbitmq-diagnostics`. При недоступности PostgreSQL Pod приложения продолжает отвечать на `/health` и исключается из Ready endpoints по `503` на `/ready`.

[Тесты Kubernetes](../tests/test_lab3_kubernetes.py) проверяют регистрацию, роли, приватность, комментарии, реакции, подписки, RabbitMQ и сохранность PVC при замене stateful Pods. Они требуют явного `CYBERNEWS_LAB3_RUN=1` и отдельного администратора через переменные окружения. Запускайте их последовательно в `cybernews-lab3`. Команда запуска и диагностика приведены в [доказательствах](EVIDENCE.md).

Одна реплика Collector остаётся основным вариантом. Advisory lock координирует планировщик, а переключение лидера между репликами требует отдельного эксперимента. Articles использует outbox и `SKIP LOCKED`, Notifications подтверждает сообщение после записи с уникальным `event_id`. Их масштабирование не входит в эксперимент с Community.
