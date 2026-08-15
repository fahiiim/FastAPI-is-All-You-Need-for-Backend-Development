from __future__ import annotations

from app.providers.fake import FakeBehavior, FakeProvider
from app.worker import JobWorker


async def test_job_submission_is_idempotent_and_records_usage(
    app_runner,
    settings_factory,
    auth_headers,
) -> None:
    settings = settings_factory()
    provider = FakeProvider()
    async with app_runner(settings, provider) as harness:
        request = {"prompt": "durable work", "max_output_tokens": 20}
        headers = {**auth_headers, "Idempotency-Key": "job-request-001"}

        accepted = await harness.client.post(
            "/v1/jobs",
            headers=headers,
            json=request,
        )
        repeated = await harness.client.post(
            "/v1/jobs",
            headers=headers,
            json=request,
        )

        assert accepted.status_code == 202
        assert repeated.status_code == 202
        assert accepted.json()["created"] is True
        assert repeated.json()["created"] is False
        assert repeated.json()["id"] == accepted.json()["id"]
        assert accepted.headers["location"] == f"/v1/jobs/{accepted.json()['id']}"

        worker = JobWorker(
            database=harness.app.state.database,
            provider=provider,
            settings=settings,
        )
        assert await worker.process_one("test-worker:0") is True
        assert await worker.process_one("test-worker:0") is False

        result = await harness.client.get(
            accepted.headers["location"],
            headers=auth_headers,
        )

    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "completed"
    assert body["attempts"] == 1
    assert body["output_text"] == "Fake provider response: durable work"
    assert body["provider_response_id"].startswith("fake_")
    assert body["usage"] == {
        "input_tokens": 2,
        "output_tokens": 5,
        "total_tokens": 7,
    }
    assert body["completed_at"] is not None


async def test_idempotency_key_rejects_a_different_request(
    app_runner,
    settings_factory,
    auth_headers,
) -> None:
    async with app_runner(settings_factory()) as harness:
        headers = {**auth_headers, "Idempotency-Key": "same-key"}
        first = await harness.client.post(
            "/v1/jobs",
            headers=headers,
            json={"prompt": "first request"},
        )
        conflict = await harness.client.post(
            "/v1/jobs",
            headers=headers,
            json={"prompt": "different request"},
        )

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        "Idempotency-Key was already used for a different request"
    )


async def test_retriable_job_failure_stops_at_the_attempt_bound(
    app_runner,
    settings_factory,
    auth_headers,
) -> None:
    settings = settings_factory(job_max_attempts=2)
    provider = FakeProvider(
        FakeBehavior(
            fail_prompts=frozenset({"retry me"}),
            failure_retriable=True,
        )
    )
    async with app_runner(settings, provider) as harness:
        accepted = await harness.client.post(
            "/v1/jobs",
            headers=auth_headers,
            json={"prompt": "retry me"},
        )
        worker = JobWorker(
            database=harness.app.state.database,
            provider=provider,
            settings=settings,
        )

        assert await worker.process_one("test-worker:0") is True
        first_attempt = await harness.client.get(
            accepted.headers["location"],
            headers=auth_headers,
        )
        assert first_attempt.json()["status"] == "queued"
        assert first_attempt.json()["attempts"] == 1

        assert await worker.process_one("test-worker:0") is True
        assert await worker.process_one("test-worker:0") is False
        terminal = await harness.client.get(
            accepted.headers["location"],
            headers=auth_headers,
        )

    assert terminal.json()["status"] == "failed"
    assert terminal.json()["attempts"] == 2
    assert terminal.json()["max_attempts"] == 2
    assert terminal.json()["error_code"] == "fake_provider_failure"
    assert terminal.json()["usage"] is None
    assert terminal.json()["completed_at"] is not None


async def test_jobs_are_hidden_without_the_api_key(
    app_runner,
    settings_factory,
) -> None:
    async with app_runner(settings_factory()) as harness:
        response = await harness.client.post(
            "/v1/jobs",
            json={"prompt": "private job"},
        )

    assert response.status_code == 401
