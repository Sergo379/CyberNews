# Матрица методички PAD

Матрица фиксирует результат проверок, а итоговую оценку выставляет преподаватель. [Официальный README курса](https://github.com/Randwow/PAD#лабораторная-работа-3-docker-и-kubernetes) · [Подробности проверок](EVIDENCE.md).

| Критерий | Вес | Реализация и ресурс | Проверка | Результат | Статус |
| --- | ---: | --- | --- | --- | --- |
| Dockerfile для сервисов | 15% | Шесть [Dockerfile backend](../services), отдельный [образ Gateway](../gateway/Dockerfile.k8s) | `.\scripts\lab3-build.ps1`, image inspect и imageID Pods | Семь образов, UID 10001 для backend и 101 для Nginx, образы в containerd | PASS |
| Docker Compose | 10% | [Существующий Compose](../compose.yaml), свой Gateway и тома | `.\scripts\verify-lab2.ps1` и регрессии этапов 2–5 | 9 healthy и работающий сайт на 8080 | PASS |
| Kubernetes Deployments | 20% | Namespace [cybernews-lab3](../k8s/namespace.yaml), [семь Deployments](../k8s/deployments) | `kubectl -n cybernews-lab3 get deploy,pods` | Все семь Deployments Ready | PASS |
| Kubernetes Services | 15% | [ClusterIP приложений](../k8s/services/apps.yaml) и [storage services](../k8s/services/storage.yaml), отдельный Gateway | `.\scripts\lab3-verify.ps1`, EndpointSlices и браузер | Одиннадцать Services, loopback Gateway 18080 и рабочие шесть Swagger/OpenAPI | PASS |
| ConfigMap / Secrets | 10% | [ConfigMaps](../k8s/configmaps), восемь Secrets, безопасная генерация и передача | `kubectl -n cybernews-lab3 get cm,secrets`, проверка Git | Службы используют собственные ссылки, рабочие значения исключены из Git | PASS |
| Health checks | 10% | `startupProbe`, `livenessProbe` и `readinessProbe` в [Deployment](../k8s/deployments/articles.yaml) и StatefulSets | `.\scripts\lab3-verify.ps1`, PostgreSQL outage в pytest | 200 от живого Pod, 503 readiness во время отказа, восстановление EndpointSlice | PASS |
| Resource limits | 5% | CPU и память заданы для [Deployments](../k8s/deployments), [StatefulSets](../k8s/statefulsets) и [Jobs](../k8s/jobs) | `kubectl describe deploy community`, `.\scripts\lab3-verify.ps1` | Requests и limits присутствуют у всех постоянных и миграционных контейнеров | PASS |
| Масштабирование | 5% | [Community Deployment](../k8s/deployments/community.yaml) и Service | `.\scripts\lab3-demo.ps1` и pytest | 1 → 3 → 1, три Ready endpoints и HTTP-трафик ко всем трём, данные общие | PASS |
| Демонстрация и документация | 10% | [Демонстрация](DEMO.md), [отчёт](REPORT.md), [ответы](DEFENSE.md), [доказательства](EVIDENCE.md) | Запуск сценария, Playwright, проверка ссылок и рендеринг Mermaid | Рабочий API и браузер, замена Pod, проверены пять диаграмм | PASS |

Дополнительные требования подтвердили [PostgreSQL и RabbitMQ StatefulSets](../k8s/statefulsets), [два PVC](../k8s/storage), миграционные Jobs до запуска приложений и восстановление обоих StatefulSets с тем же PV. [Протокол](EVIDENCE.md).
