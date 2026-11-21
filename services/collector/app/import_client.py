import httpx
from pydantic import ValidationError

from cybernews_runtime.logs import request_id
from cybernews_runtime.news import FeedBatch, ImportCounts, VersionedPolicy

from .fetch import FeedError


class ArticleClient:
    def __init__(self, url, key):
        self.client = httpx.Client(
            base_url=url, timeout=4.0, trust_env=False, headers={"X-Internal-Key": key},
        )

    def close(self):
        self.client.close()

    def send(self, method, path, payload, status):
        try:
            response = self.client.request(
                method, path, json=payload.model_dump(mode="json"),
                headers={"X-Request-ID": request_id.get() or ""},
            )
        except httpx.RequestError:
            raise FeedError("article_service_unavailable") from None
        if response.status_code != status:
            code = "article_policy_conflict" if response.status_code == 409 else "article_import_failed"
            raise FeedError(code)
        return response

    def ingest(self, batch: FeedBatch) -> ImportCounts:
        response = self.send("POST", "/internal/v1/import", batch, 200)
        try:
            return ImportCounts.model_validate_json(response.content)
        except ValidationError:
            raise FeedError("invalid_import_response") from None

    def policy(self, source_id, policy: VersionedPolicy):
        self.send("PUT", f"/internal/v1/sources/{source_id}/policy", policy, 204)
