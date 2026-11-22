# Сценарий защиты на 10 минут

До начала проверьте `.\scripts\lab3-verify.ps1`, поднимите port-forward на `18080` и откройте окна браузера с главной, Swagger и админ-панелью. Подготовьте одну запись или комментарий на Kubernetes-стенде. [Подготовка](README.md).

| Время | Действие в PowerShell или браузере | Что объяснить |
| --- | --- | --- |
| 0:00–1:00 | Открыть [Compose на 8080](http://localhost:8080/) и [Kubernetes на 18080](http://127.0.0.1:18080/) | Один CyberNews, два независимых развёртывания с отдельными аккаунтами и базами |
| 1:00–2:00 | Открыть [архитектуру](diagrams/kubernetes-architecture.md). Выполнить `kubectl --context docker-desktop get nodes` | Один Ready-узел, семь Deployments и два StatefulSets |
| 2:00–3:00 | `kubectl --context docker-desktop -n cybernews-lab3 get pods,deployments,statefulsets,pvc` | Девять основных Pod, миграционные Jobs отделены от постоянных процессов, PVC привязаны |
| 3:00–4:00 | `kubectl --context docker-desktop -n cybernews-lab3 get services` и `Invoke-RestMethod 'http://127.0.0.1:18080/api/v1/articles/categories'`. Открыть [Swagger](http://127.0.0.1:18080/api/v1/articles/docs) | Внешний HTTP входит через Gateway, у API и брокера внутренние ClusterIP |
| 4:00–5:00 | `kubectl --context docker-desktop -n cybernews-lab3 get configmaps,secrets`. Открыть [Deployment Community](../k8s/deployments/community.yaml) | ConfigMap задаёт несекретные параметры, `secretRef` подключает credentials. Достаточно вывести имена объектов |
| 5:00–6:00 | `kubectl --context docker-desktop -n cybernews-lab3 describe deployment community`. Открыть `/api/v1/community/health` и `/ready` через Gateway | Показать probes, requests и limits. При проблеме БД readiness выводит Pod из балансировки |
| 6:00–8:20 | `.\scripts\lab3-demo.ps1`. Во втором терминале наблюдать Pods и EndpointSlice | Одна реплика становится тремя. Логи подтверждают трафик ко всем. После удаления одной реплики появляется новая. Затем скрипт повторяет удаление в одиночном режиме |
| 8:20–9:30 | `kubectl --context docker-desktop -n cybernews-lab3 get pvc`. Открыть подготовленную запись через сайт и [результаты рестартов](EVIDENCE.md) | Данные лежат в PVC, поэтому замена Pod их сохранила. Продемонстрировать outbox и уведомления по протоколу проверок |
| 9:30–10:00 | Показать [матрицу](REQUIREMENTS_MATRIX.md) и [вывод тестов](EVIDENCE.md) | Подвести итог Ready, масштабирования, хранения и параллельного Compose |

Команды наблюдения для демонстрации.

```powershell
kubectl --context docker-desktop -n cybernews-lab3 get pods -l app.kubernetes.io/name=community -w
kubectl --context docker-desktop -n cybernews-lab3 get endpointslices -l kubernetes.io/service-name=community
kubectl --context docker-desktop -n cybernews-lab3 logs deployment/gateway --tail=8
```

Если провайдер RSS временно недоступен, откройте сохранённую статью или опубликуйте собственную через [редакционный интерфейс Kubernetes](http://127.0.0.1:18080/admin/). Сценарии перезапуска PostgreSQL и RabbitMQ запускайте заранее через [интеграционные проверки](../tests/test_lab3_kubernetes.py). Во время десятиминутной демонстрации достаточно показать их результаты и Bound PVC.
