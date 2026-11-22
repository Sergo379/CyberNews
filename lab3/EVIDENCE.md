# Доказательства лабораторной №3

Проверка 22 ноября 2026 года на Windows 11. Рабочий Docker Compose и учебный Kubernetes использовались параллельно. Учебные записи менялись только в `cybernews-lab3`.

## Кластер, контейнеры и API

Docker Desktop 4.99.0, провайдер kind, Kubernetes v1.36.1, контекст `docker-desktop`. Узел `desktop-control-plane` — Ready. Runtime узла — containerd 2.3.1. Выделено 12 CPU и 7 983 884 KiB памяти. Default StorageClass `standard` использует `rancher.io/local-path` и `WaitForFirstConsumer`.

```powershell
kubectl --context docker-desktop get nodes
kubectl --context docker-desktop get namespace cybernews-lab3
kubectl --context docker-desktop -n cybernews-lab3 get pods,deployments,services,statefulsets,pvc,jobs
kubectl --context docker-desktop -n cybernews-lab3 describe deployment community
.\scripts\lab3-verify.ps1
```

В Kubernetes запущены семь Deployments и два StatefulSets, у каждого постоянного компонента одна Ready реплика. Каждый из шести backend Pods запускает свой образ с UID 10001. Gateway содержит frontend и запускается с UID 101. Одиннадцать Services используют ClusterIP, в том числе два headless Service StatefulSets. Запущены шесть миграционных Jobs, ревизии совпали с head. Nginx прошёл `nginx -t` в Pod. На шести API проверены Swagger, OpenAPI, liveness, readiness и закрытые для гостя и внутренних путей запросы.

| Компоненты | Ресурсы | Проверка состояния |
| --- | --- | --- |
| Шесть backend | 100m/500m CPU и 128Mi/512Mi | `/health` для startup/liveness, `/ready` для readiness |
| Gateway | 50m/500m CPU и 32Mi/128Mi | `/health` |
| PostgreSQL | 250m/1 CPU и 256Mi/768Mi | `pg_isready` на TCP |
| RabbitMQ | 250m/1 CPU и 512Mi/1Gi | `rabbitmq-diagnostics`, готовность слушателей |
| Шесть Jobs | 50m/350m CPU и 64Mi/256Mi | Завершение с кодом 0 |

Первый старт Jobs вернул `ErrImageNeverPull`. После переноса локальных образов в node containerd с проверкой CRI запустились все семь образов с `imagePullPolicy: Never`. Первый сбор RSS опередил готовность Articles. После исправления порядка и ручной синхронизации в Kubernetes успешно импортировано **75 реальных публикаций**. Записи интеграционных сценариев добавлялись отдельно в ту же учебную базу.

## Доступ, графический интерфейс и политики

1. Открыть [Kubernetes-версию](http://127.0.0.1:18080/) через запущенный [port-forward](README.md#ресурсы-и-доступ). `/health` содержит маркер `environment: kubernetes`.
2. [Публичный каталог с фильтром по RSS-источнику](evidence/kubernetes-catalog.jpg) и [Swagger Community](evidence/kubernetes-swagger.jpg) сняты в гостевых вкладках Edge с этого адреса. Playwright проверил поиск, категории, фильтр источника, сортировку, ссылку на первоисточник, RU/EN и обе темы. На мобильном viewport проверены вход, административный unlock, открытие статьи и обновление страницы. Прямые маршруты регистрации, входа, кабинета и админ-панели возвращают HTML.
3. Временно созданная deny-ingress политика прекратила доставку HTTP к тестовому Pod, подтвердив поддержку установленным kindnet. В постоянной конфигурации восемь NetworkPolicy. Тестовый Pod без разрешающих labels не смог подключиться к Community, PostgreSQL и RabbitMQ. Gateway сохранил HTTP 200 к Community. [Политики](../k8s/networkpolicies/ingress.yaml).
4. Через Gateway `/internal/v1` возвращает 404, служебные маршруты исключены из OpenAPI. Восемь неизменяемых Secrets остаются в Kubernetes; значения не включаются в материалы. Проверка Git использовала фактические локальные значения как закрытые шаблоны поиска.

Для демонстрации имён и журналов из PowerShell.

```powershell
kubectl --context docker-desktop -n cybernews-lab3 get configmaps,secrets,networkpolicies
kubectl --context docker-desktop -n cybernews-lab3 logs deployment/gateway --tail=10
kubectl --context docker-desktop -n cybernews-lab3 logs deployment/notifications --since=15m |
    Select-String -SimpleMatch 'Article publication event recorded'
```

## Изолированные эксперименты

| Сценарий | Наблюдение |
| --- | --- |
| Community 1 → 3 | У Service появились три Ready EndpointSlice-адреса. Pods `community-755c5c66b4-nw24j`, `community-755c5c66b4-rlk94` и `community-755c5c66b4-vfjlz` обработали соответственно 9, 24 и 12 из 45 запросов через Service |
| Конкурентные реакции | Двенадцать одинаковых PUT от одного читателя дали одну сохранённую реакцию. Комментарий и значение счётчика сохранились после замены Pod |
| Замена Pod при трёх репликах | ReplicaSet заменил `community-755c5c66b4-nw24j` на `community-755c5c66b4-tb5r6`. Gateway возвращал HTTP 200 через доступные адреса |
| Замена одиночного Community Pod | `community-755c5c66b4-phgg6` заменил `community-755c5c66b4-vfjlz`, стал Ready, Gateway снова получил HTTP 200. Демонстрация завершилась исходным масштабом 1 |
| Отказ PostgreSQL | У Articles `/health` дал 200, `/ready` — 503, endpoint исключён. UID `postgres-0` сменился с `5900bb17-3b08-4b25-b8fa-246ecf7dccbe` на `e8c974e5-db5d-461e-99e5-92d2817e3312`, PV `pvc-863c0bfa-3efd-40be-a07b-e509d78571c2` сохранился. API восстановились без рестарта Articles |
| Отказ RabbitMQ | UID `rabbitmq-0` сменился с `3579dff5-c699-4bbc-8221-62876ac6f902` на `9a66ccd0-e8a6-464a-90a3-3d8fb80f7e75`, PV `pvc-c28a30f4-cd9d-4d1f-a9db-a10f4d2cce20` сохранился. Подтверждённое сообщение пережило замену Pod. Публикация при остановленном брокере осталась в PostgreSQL outbox. После восстановления оба события дали по одному уведомлению |
| Повторное развёртывание | Шесть миграционных Jobs выполнены повторно. До и после было 16 пользователей, 93 статьи, 9 комментариев и 55 уведомлений в учебном namespace |

```powershell
.\scripts\lab3-demo.ps1
kubectl --context docker-desktop -n cybernews-lab3 get endpointslices -l kubernetes.io/service-name=community
kubectl --context docker-desktop -n cybernews-lab3 get pvc -o wide
```

## Регрессии и воспроизведение

| Проверки | Результат |
| --- | --- |
| Auth и Moderation | 33 pytest прошли |
| RSS и Articles | 48 pytest прошли |
| Community, Notifications и инфраструктура | 39 pytest прошли |
| Compose в Edge и WebKit | По 5 Playwright-сценариев, из них по одному на рабочем каталоге в режиме чтения |
| Изолированный Kubernetes | 7 проверок pytest (103,62 с). Проверены каталог и интерфейс, JWT, создание, изменение и удаление комментариев, реакции и избранное, жалобы, скрытие и ограничения с проверкой ролей, подписки и прочтение уведомлений. Также пройдены масштабирование, блокировка запрещённого трафика и сохранность двух PVC |
| Манифесты и документация | Клиентский и серверный dry-run, Kubectl diff, PowerShell, пять отрисованных Mermaid-диаграмм |

Для повторения упражнений используйте уже заведённого **учебного** Super Admin. Для браузерной проверки фильтра источника и ссылки на первоисточник в каталоге должна быть хотя бы одна импортированная RSS-статья. Следующая команда запускает эксперименты с остановкой зависимостей и сменой числа реплик только в выделенном namespace. Корреляция выполняется по реальным Pods, данным и API.

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests\stage5-requirements.txt
$env:CYBERNEWS_BROWSER_CHANNEL = 'msedge'
$env:CYBERNEWS_LAB3_RUN = '1'
$env:CYBERNEWS_LAB3_SUPER_EMAIL = Read-Host 'Lab 3 admin email'
$env:CYBERNEWS_LAB3_SUPER_PASSWORD = [Net.NetworkCredential]::new('', (Read-Host 'Account password' -AsSecureString)).Password
$env:CYBERNEWS_LAB3_ADMIN_PASSWORD = [Net.NetworkCredential]::new('', (Read-Host 'Administrative password' -AsSecureString)).Password
try {
    .\.venv\Scripts\python.exe -m pytest -q -s tests\test_lab3_kubernetes.py
} finally {
    Remove-Item Env:CYBERNEWS_LAB3_RUN, Env:CYBERNEWS_LAB3_SUPER_EMAIL, Env:CYBERNEWS_LAB3_SUPER_PASSWORD, Env:CYBERNEWS_LAB3_ADMIN_PASSWORD
}
```

Финальный read-only Compose показал девять healthy, шесть актуальных миграций, 76 опубликованных статей, 1 пользователя, 1 комментарий, 3 источника, 0 подписок и 0 уведомлений. Тесты этапов 2–5 использовали временные проекты Compose и не изменяли эти данные. [Рабочий стенд](http://localhost:8080/).
