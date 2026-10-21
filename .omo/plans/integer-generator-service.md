# integer-generator-service - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**Кому поможет и что изменится:** Пользователи смогут отправлять генерации и проверять статус и баланс без повторного списания токенов. Разработчик или проверяющий сможет запустить сервис локально и проверить обработку сбоев и повторных уведомлений.

**Что будет создано:** Полностью запускаемый асинхронный сервис генераций с двумя настраиваемыми имитационными провайдерами, базой данных, миграциями, тестами и понятной документацией с чёрно-белыми схемами.

**Почему так:** Баланс вычисляется по неизменяемому журналу операций, а уникальные ключи и атомарные транзакции защищают от повторных платежей и возвратов. Все процессы сервиса согласуют исход задачи через общее состояние в базе, чтобы уведомления и сторож не фиксировали противоречивые результаты.

**Чего здесь не будет:** Пользовательского интерфейса, регистрации, настоящих платежей, реального хранения файлов или интеграций с генеративными моделями. Удалённый репозиторий не создаётся и код не публикуется.

**Effort:** Large
<!-- Effort is exactly ONE band, never hours/days. Quick = single edit, minutes of agent work; Short = one focused change, a few files; Medium = multi-file feature in one session; Large = several waves, one long session; XL = multi-session or architectural work. A written duration is rewritten to a band. -->
**Risk:** High - корректность зависит от транзакций, повторных webhook и гонок между четырьмя процессами.
**Решения для проверки:** failed-платёж остаётся терминальным; поздний callback после фиксации таймаута игнорируется; повторный `POST /generate` считается новым заказом; баланс вычисляется из журнала.

Следующий шаг: после независимого ревью план можно передать на отдельную реализацию.

---

> TL;DR (machine): Large | высокий риск | асинхронный сервис генерации, однократные операции токенов, переключение провайдеров и watchdog, Compose с четырьмя workers, тесты на PostgreSQL, русская документация, монохромные схемы.

## Scope
### Affected user and ideal state
<!-- From the draft ledger: who this touches and how they use the result, then one IS row per property with its reason, then one GAP row per difference with its reason. Every todo below closes a GAP row; ## Success criteria proves every IS row. -->
**Affected users:** A generation API caller submits work and checks its status/balance. A developer or reviewer runs the repository locally, verifies money and task-state invariants, and follows the migration and operations guide.

| Row | Statement | Reason |
| --- | --- | --- |
| IS-1 | A valid request receives a task id; invalid model/reference combinations are rejected before debit, insufficient tokens return 402, and a fourth active task returns 429. | Callers need predictable admission and must not pay for work that cannot start. |
| IS-2 | Payment credit, generation debit, and final refund each have one immutable ledger operation; the reported balance equals the sum of that user's ledger rows. | Token accounting must be auditable and duplicate deliveries must not move tokens twice. |
| IS-3 | Task status, current provider leg, and timestamped attempt/error history reflect the configured technical, moderation, payload, sync-failure, and timeout rules. | Callers/reviewers need to understand why a task succeeded or failed and whether the next provider was tried. |
| IS-4 | Four API workers can race callbacks and watchdog polling without duplicate transitions; a stale completion cannot produce both a result and a refund. | The test explicitly requires multiprocess operation and consistent handling of late provider events. |
| IS-5 | `docker compose up` brings up PostgreSQL, migrations, the API with four workers, and alpha/beta; later schema changes use Alembic revisions. | Reviewers need a reproducible local run and a clear schema-evolution workflow. |
| IS-6 | Required duplicate/concurrent webhook, failover, timeout, and signature behavior is proven against PostgreSQL and the configured pytest/Ruff/mypy toolchain. | Passing tests must demonstrate database behavior, not an in-memory approximation. |
| IS-7 | Russian documentation and monochrome architecture/lifecycle diagrams explain setup, exact-once boundaries, crash behavior, and the late-result decision. | Reviewers need to run and assess the project without reconstructing design intent from code. |
| GAP-1 | The workspace has no application, API, or validation code. | There is currently no request path that can enforce the caller-facing rules. |
| GAP-2 | There are no user/payment/ledger/task tables or migration history. | There is no durable source of truth or atomic idempotency boundary. |
| GAP-3 | Provider attempts, failure routing, callbacks, watchdog, and history do not exist. | The core generation workflow and its terminal outcomes cannot be exercised. |
| GAP-4 | No shared multiprocess persistence or watchdog coordination is configured. | Four workers would otherwise race over process-local state or duplicate timeout work. |
| GAP-5 | No Compose stack, migration runner, or fake-provider services exist. | A reviewer cannot start the requested complete service. |
| GAP-6 | No tests, locked Python environment, or lint/type-check configuration exist. | Concurrency and interface regressions have no repeatable verification path. |
| GAP-7 | No README or visual documentation exists. | A reviewer has no setup/runbook or clear view of architecture and lifecycle. |

### Must have
- Python 3.11+; async FastAPI, Pydantic, async SQLAlchemy 2.x, PostgreSQL 18, Alembic, pytest, uv, Ruff, mypy, and Docker Compose.
- The requested layers under `app/api/controllers`, `app/api/schemas`, `app/models`, `app/services`, `app/repositories`, `app/providers`, and `app/workers`; no ORM model doubles as a public response schema.
- PostgreSQL migrations seed exactly `image-fast` (2 tokens: alpha/max 4 refs, then beta/max 10) and `video-long` (25 tokens: beta/max 2, then alpha/max 1 with `skip_on_moderation`).
- `POST /generate`, `POST /webhooks/providers/{name}`, `POST /webhooks/payments`, `GET /tasks/{id}`, and `GET /users/{id}/balance`, with the specified status codes, validation ordering, history, and ledger-derived balance plus the 20 newest ledger rows.
- Task states are exactly `queued`, `processing`, `succeeded`, and `failed`; only `queued` and `processing` count as active. `POST /generate` returns 202 with a task id, valid provider/payment webhooks return 204 (duplicates included), conflicting terminal payment-id reuse returns 409, and an invalid signature returns 401.
- Unknown user/task ids return 404; no compatible provider leg returns 400 before any token operation; an insufficient balance returns 402 and a fourth active task returns 429.
- Payment statuses are `pending`, `succeeded`, and `failed`; only a pending-to-succeeded transition credits, both terminal outcomes remain terminal, a reused payment id with conflicting user/tokens/status returns 409, and successful duplicate deliveries are idempotent.
- `GET /users/{id}/balance` derives the total from ledger deltas and returns exactly the latest 20 ledger rows; no separate cached balance column is stored.
- Both webhook paths verify a lowercase-hex HMAC-SHA256 of the raw request bytes using the shared configured secret. Missing or incorrect signatures return 401 before any database write.
- Provider failover follows the exact technical/moderation/payload rules. Fake services support configured failure probability/type, sync 503/timeout, duplicate concurrent callbacks, no callback, and late completion; their default callback delay is 2–20 seconds.
- A persisted attempt whose provider is silent past configurable `PROVIDER_TIMEOUT` (60 seconds in the default test configuration) is timed out by a bounded watchdog running in each API worker. Watchdog and callback lock the task row first and current attempt second; due-task selection uses `FOR UPDATE OF task SKIP LOCKED`.
- An attempt/deadline is committed before provider HTTP. A process crash in that gap is treated as provider silence and eventually follows timeout/failover/refund; the README states this explicitly.
- An attempt that is no longer current, or a task already terminal when a callback arrives, ignores the callback. The first committed terminal transition wins; external provider work may be wasted, but a task never has both a result and a refund.
- Tests run against PostgreSQL from Compose and include exact assertions for 20 concurrent duplicate success webhooks, 10 concurrent final-leg failures for the same task, first-leg failure/second-leg success with two history rows, late completion after watchdog commit, and invalid signatures without mutation.
- `docker compose up` starts a healthy PostgreSQL, successful migration job, four-worker API, and both fake provider services. Include a Compose test runner and `.env.example`.
- Russian README explains run/tests, migrations and adding one, exactly-once database guarantees, process death during webhook, the dispatch crash window, late completion, and the fact that repeating `POST /generate` without an idempotency key creates a new task.
- Local commits are made per verified increment with messages that explain why; use `gh` only for read-only official documentation research.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- No registration/authentication, product UI, real money/payment integration, real object storage, external image/video model integrations, or Redis/message broker.
- No required/optional `Idempotency-Key` extension to `POST /generate`; each received request is a distinct order under the supplied contract.
- No GitHub remote creation, visibility change, push, public release, or claim of production throughput/SLA not present in the assignment.
- No in-memory state, `metadata.create_all()` in place of migrations, or sleeps/polling delays in tests to win an asynchronous race.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: tests-after, with tests implemented in the same todo as the behavior; pytest + pytest-asyncio + HTTPX. Integration tests use the PostgreSQL 18 test database from Compose and independent `AsyncSession`s.
- Timing strategy: use provider configuration and an already-expired persisted deadline plus a direct watchdog `run_once()` assertion; do not add fixed sleeps or time-based test polling.
- Required database scenarios:
  - `tests/integration/test_payments.py::test_20_concurrent_duplicate_success_webhooks_credit_once`: 20 concurrent signed copies of one payment; one payment credit ledger row and one balance increase of exactly `tokens`.
  - `tests/integration/test_provider_callbacks.py::test_10_concurrent_final_leg_failures_refund_once`: 10 concurrent signed failures for one `task_id` on its last leg; one refund row, task `failed`, balance restored exactly once.
  - `tests/integration/test_generation.py::test_first_provider_failure_succeeds_on_second_with_two_attempts`: first provider fails, second completes, history has exactly two attempts in priority order.
  - `tests/integration/test_watchdog.py::test_late_completed_after_watchdog_commit_is_ignored`: expire/finalize an attempt, then submit its valid late completion; final status/output/refund remain mutually consistent.
  - `tests/integration/test_webhook_signatures.py`: invalid payment and provider signatures return 401 and leave ledger/task state unchanged.
- Commands after Compose setup: `docker compose config -q`; `docker compose up --build -d`; `docker compose ps`; `docker compose --profile test run --rm tests uv run pytest -q`; `docker compose --profile test run --rm tests uv run ruff check .`; `docker compose --profile test run --rm tests uv run ruff format --check .`; `docker compose --profile test run --rm tests uv run mypy .`. All must exit 0.
- Evidence: use the exact `<attemptDir>/task-1-integer-generator-service.json` through `<attemptDir>/task-10-integer-generator-service.json` path named in each todo (attemptDir = `result.currentAttemptDir` from `await agentToolkit.status()` in JS eval after importing `agentToolkit` from `${env("OMO_AGENT_TOOLKIT_SDK_ROOT")}/sdk.js`; outside ulw-loop use `.omo/evidence/`). Each artifact records the exact command, exit code, relevant assertions/output, and happy/failure QA.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.
- Wave 1 — Foundation (1–3): todo 1 establishes the package/toolchain; todos 2 and 3 then work in separate database and API-contract paths.
- Wave 2 — Business and provider lifecycle (4–7): accounting, generation, fake-provider routing, then watchdog correctness; dependencies are explicit and prevent editing the same service path concurrently.
- Wave 3 — Delivery (8–10): after watchdog behavior is stable, Compose integration and SVG diagrams can proceed in parallel; README follows both so its commands and asset links are accurate.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | — | 2, 3 | — |
| 2 | 1 | 4–8 | 3 |
| 3 | 1 | 4–6 | 2 |
| 4 | 2, 3 | 5, 6 | — |
| 5 | 2, 3, 4 | 6, 7 | — |
| 6 | 2, 3, 5 | 7, 8 | — |
| 7 | 2, 5, 6 | 8–10 | — |
| 8 | 1, 2, 6, 7 | 10 | 9 |
| 9 | 1, 2, 3, 6, 7 | 10 | 8 |
| 10 | 8, 9 | — | — |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [ ] 1. Bootstrap the async Python service and toolchain
  What to do / Must NOT do: Create the `app/` layered package, async FastAPI composition root and `/healthz`, Pydantic settings, async SQLAlchemy engine/session factory, Python 3.11+ project metadata, locked runtime/dev dependencies, `Dockerfile`/`.dockerignore`, and Ruff/mypy/pytest configuration. Ensure the Docker test image installs the locked dev group. Keep settings environment-driven and use one `AsyncSession` per request/task. Do not add business no-op endpoints or a web UI.
  Closes: GAP-1, GAP-6
  Parallelization: Wave 1 | Blocked by: — | Blocks: 2, 3
  References (executor has NO interview context - be exhaustive): User request “Технические требования” (Python 3.11+, async, FastAPI, Pydantic, SQLAlchemy, pytest, uv, Ruff, mypy); draft `.omo/drafts/integer-generator-service.md:32-38, 52-78, 127-134`; FastAPI async/dependencies docs `https://fastapi.tiangolo.com/async/`; SQLAlchemy AsyncSession concurrency docs `https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html`; uv project docs `https://docs.astral.sh/uv/guides/projects/`; Ruff config docs `https://docs.astral.sh/ruff/configuration/`.
  Acceptance criteria (agent-executable): `uv sync --locked` succeeds on Python 3.11+; `uv run pytest -q tests/unit/test_app.py` proves the app factory and `/healthz` return 200; `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy .` exit 0; invalid/missing required secret fails settings validation at startup.
  QA scenarios (name the exact tool + invocation): Happy: `uv run pytest -q tests/unit/test_app.py` asserts the health response and async settings load; failure: `uv run pytest -q tests/unit/test_settings.py::test_rejects_missing_webhook_secret` asserts startup configuration is rejected; Evidence `<attemptDir>/task-1-integer-generator-service.json`.
  Commit: Y | `chore(core): lock the async toolchain for repeatable runs`
  Recommended task executor category: `unspecified-high` — the initial scaffold establishes the package and shared runtime contracts across layers.

- [ ] 2. Define PostgreSQL models, repositories, catalog migration, and database Compose service
  What to do / Must NOT do: Add typed SQLAlchemy 2.x models/repositories for users, payment identities, immutable token ledger entries, generation models/legs, tasks, and attempts. Do not persist a separate user balance column. Add uniqueness/check constraints for payment id, ledger `operation_key`, `(task_id, attempt_no)`, positive model prices, and leg ordering; add indexes for per-user ledger sum/history and active-task counting. Create an async Alembic environment and initial migration that seeds exactly the requested models/legs; add PostgreSQL 18 plus `pg_isready` healthcheck to the Compose foundation. Do not use `metadata.create_all()`.
  Closes: GAP-2, GAP-5
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 4–8 | Can parallelize after todo 1 with: 3
  References (executor has NO interview context - be exhaustive): User request “Предметная область” catalog table and “Технические требования” migration requirement; draft `.omo/drafts/integer-generator-service.md:33-38, 45-50, 57-63, 127-134`; SQLAlchemy 2.0 async docs `https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html`; Alembic async cookbook `https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic`; PostgreSQL uniqueness/transaction docs `https://www.postgresql.org/docs/current/sql-insert.html` and `https://www.postgresql.org/docs/current/transaction-iso.html`; Compose healthcheck startup docs `https://docs.docker.com/compose/how-tos/startup-order/`.
  Acceptance criteria (agent-executable): `docker compose up -d db && uv run alembic upgrade head && uv run alembic current` succeeds; database queries show only the specified seed models/prices/provider priorities/ref limits/moderation flag; migrations downgrade and re-upgrade cleanly; repository tests confirm uniqueness/check constraints reject duplicate operation keys and invalid catalog values.
  QA scenarios (name the exact tool + invocation): Happy: `docker compose up -d db && uv run alembic upgrade head && uv run pytest -q tests/integration/test_catalog.py` asserts both seeded models and ordered legs; failure: `uv run pytest -q tests/integration/test_constraints.py` asserts duplicate `operation_key` and duplicate attempt number fail without partial rows; Evidence `<attemptDir>/task-2-integer-generator-service.json`.
  Commit: Y | `feat(db): seed the catalog and constrain ledger identities`
  Recommended task executor category: `unspecified-high` — schema, migrations, repositories, and database constraints form one persistent data contract.

- [ ] 3. Define validated API schemas and shared webhook signature verification
  What to do / Must NOT do: Add Pydantic request/response schemas for all five requested endpoints, strict field constraints for ids/token counts/prompt/ref image URLs/payment status/provider outcome/task states, and a shared HMAC verifier that receives raw bytes and compares lowercase-hex HMAC-SHA256 in constant time. Keep health routing functional; leave business route effects to todos 4–6. Do not add an `Idempotency-Key` to generation or verify signatures over reserialized JSON.
  Closes: GAP-1, GAP-3, GAP-6
  Parallelization: Wave 1 | Blocked by: 1 | Blocks: 4–6 | Can parallelize after todo 1 with: 2
  References (executor has NO interview context - be exhaustive): User request “API” table and “Фейковые провайдеры” signature rule; draft `.omo/drafts/integer-generator-service.md:32-38, 58-64, 75-78, 115-126, 127-134`; Pydantic v2 strict-mode docs `https://docs.pydantic.dev/latest/concepts/strict_mode/`; FastAPI async/dependency docs `https://fastapi.tiangolo.com/async/`.
  Acceptance criteria (agent-executable): schema tests accept the documented valid request shapes and reject missing/invalid status, negative token count, malformed references, unknown provider outcome, or invalid task identifier; signature tests match raw bytes and reject one-byte tampering/missing signatures with 401 before any database mutation.
  QA scenarios (name the exact tool + invocation): Happy: `uv run pytest -q tests/unit/test_api_schemas.py tests/unit/test_webhook_signatures.py` verifies exact request types and valid HMAC; failure: `uv run pytest -q tests/unit/test_webhook_signatures.py::test_rejects_modified_raw_body` asserts tampering fails before persistence; Evidence `<attemptDir>/task-3-integer-generator-service.json`.
  Commit: Y | `feat(api): validate request contracts and raw-body signatures`
  Recommended task executor category: `quick` — the bounded schema/security-helper contract can be implemented and tested without domain state transitions.

- [ ] 4. Implement the token ledger and idempotent payment webhook
  What to do / Must NOT do: Implement payment repository/service/controller and `GET /users/{id}/balance`. Derive balance from `SUM(ledger.delta)` and return the 20 latest entries; lock the user row before a balance-affecting write; make ledger entries append-only with unique operation keys. Accept `pending -> succeeded|failed` only, keep terminal states terminal, credit only `succeeded`, create a user on the first successful payment, and reject payment-id reuse with changed identity/terminal data as 409. Do not add a stored balance projection or registration endpoint.
  Closes: GAP-2, GAP-6
  Parallelization: Wave 2 | Blocked by: 2, 3 | Blocks: 5, 6
  References (executor has NO interview context - be exhaustive): User request “Предметная область”, `POST /webhooks/payments`, `GET /users/{id}/balance`, rules 7–8 and mandatory test 1; draft `.omo/drafts/integer-generator-service.md:33, 57-64, 99-111, 115-126, 127-134`; PostgreSQL `INSERT ... ON CONFLICT`, transaction isolation, and row-lock docs; SQLAlchemy per-concurrent-task `AsyncSession` docs.
  Acceptance criteria (agent-executable): twenty concurrent signed deliveries of one success payment using separate sessions and a test pool sized for at least 20 connections produce exactly one payment-credit ledger row and balance delta `tokens`; pending/failed add no tokens; same terminal duplicate is a no-op; mismatched identity/status returns 409 without mutation; unknown user returns 404; balance response uses `COALESCE(SUM(delta), 0)` and returns exactly the 20 newest ledger rows. An exception before commit rolls back payment/user/ledger changes together; retry after a committed-but-unacknowledged delivery is a no-op.
  QA scenarios (name the exact tool + invocation): Happy: `docker compose up -d db && uv run pytest -q tests/integration/test_payments.py::test_20_concurrent_duplicate_success_webhooks_credit_once` asserts 20 responses, one credit, exact balance; failure: `uv run pytest -q tests/integration/test_webhook_signatures.py::test_invalid_payment_signature_changes_no_ledger tests/integration/test_payments.py::test_reused_terminal_payment_id_returns_409 tests/integration/test_payments.py::test_rollback_before_commit_leaves_no_credit` asserts 401/409/rollback and unchanged ledger; Evidence `<attemptDir>/task-4-integer-generator-service.json`.
  Commit: Y | `feat(wallet): credit each successful payment once in the ledger`
  Recommended task executor category: `deep-low` — concurrent payment identity and derived balance correctness need transaction-level reasoning, but the database contract settles the design.

- [ ] 5. Implement generation admission, debit, task status, and history APIs
  What to do / Must NOT do: Implement generation/task services and controllers. Select all model legs compatible with `len(ref_images)` before charging; no compatible leg returns 400 without a ledger row. Under a user-row lock, sum ledger balance and count tasks in `queued|processing`; return 402 for insufficient tokens and 429 at three active tasks; otherwise atomically insert one `queued` task, one debit ledger row, and its first attempt. After provider accepts, transition to `processing`; provider completion/failure transitions once to `succeeded|failed`. Return 202 with `task_id`; implement task status/current leg/attempt history lookup. Use a provider-port test double with the exact 202/external-id contract until todo 6 wires the real fake-provider services. A repeated POST without an idempotency key is a new order. Do not send network requests while holding the DB transaction.
  Closes: GAP-1, GAP-2, GAP-3
  Parallelization: Wave 2 | Blocked by: 2, 3, 4 | Blocks: 6, 7
  References (executor has NO interview context - be exhaustive): User request `POST /generate`, `GET /tasks/{id}`, rules 1 and 7–8; draft `.omo/drafts/integer-generator-service.md:32-35, 61-64, 75-78, 99-111, 115-126, 127-134`.
  Acceptance criteria (agent-executable): compatible request debits exactly one model price and persists a task/attempt; no-compatible-leg returns 400 before any write; unknown user/task ids return 404; insufficient balance returns 402; three active tasks accept no fourth (429); invalid request/provider routes do not debit; every task response includes stored status/current leg and timestamped provider/error attempt history.
  QA scenarios (name the exact tool + invocation): Happy: `uv run pytest -q tests/integration/test_generation.py::test_valid_request_debits_once_and_returns_task_id tests/integration/test_generation.py::test_task_status_includes_attempt_history`; failure: `uv run pytest -q tests/integration/test_generation.py::test_unknown_user_returns_404_without_debit tests/integration/test_generation.py::test_no_compatible_leg_returns_400_without_debit tests/integration/test_generation.py::test_fourth_active_task_returns_429_without_debit`; Evidence `<attemptDir>/task-5-integer-generator-service.json`.
  Commit: Y | `feat(generation): admit tasks only after locked balance validation`
  Recommended task executor category: `deep-low` — task admission combines row locking, aggregate balance checks, active-task limits, and ledger writes.

- [ ] 6. Implement configurable fake providers and ordered failover callbacks
  What to do / Must NOT do: Implement the async provider port/client, fake alpha/beta FastAPI application, provider callback controller, and current-attempt state transition service. Fake providers return 202/external id and expose config for failure rate/type, sync 503/timeout, duplicate concurrent callbacks, omitted callback, and late completion. Enforce exact technical/moderation/payload routing and `skip_on_moderation`; append every attempt outcome/time; valid webhooks including duplicates/stale callbacks return 204; final exhausted/payload failure invokes the one-time refund path. Test first-leg failure followed by second-leg success and exactly two history rows. Do not treat `payload` as retryable or trust stale callbacks.
  Closes: GAP-3, GAP-6
  Parallelization: Wave 2 | Blocked by: 2, 3, 5 | Blocks: 7–9
  References (executor has NO interview context - be exhaustive): User request “Фейковые провайдеры”, provider webhook API, rules 2–4; draft `.omo/drafts/integer-generator-service.md:34, 59-70, 99-111, 116-126, 127-134`.
  Acceptance criteria (agent-executable): `alpha` and `beta` each answer POST `/tasks` with 202/external id; deterministic test settings exercise configured failure rate/type, 503, POST timeout, duplicate concurrent callbacks, omitted callbacks, and late completion; technical and sync errors advance; moderation skips only marked next legs; payload fails immediately without trying another leg; stale/non-current callback makes no task/ledger mutation; repeated last-leg failures for the same task produce exactly one refund; a DB error before callback commit rolls back attempt/task/ledger changes together for retry.
  QA scenarios (name the exact tool + invocation): Happy: `uv run pytest -q tests/integration/test_provider_callbacks.py::test_first_provider_failure_succeeds_on_second_with_two_attempts tests/integration/test_provider_callbacks.py::test_moderation_skips_flagged_leg`; failure: `uv run pytest -q tests/integration/test_provider_callbacks.py::test_sync_503_and_timeout_fail_over tests/integration/test_provider_callbacks.py::test_payload_failure_is_terminal tests/integration/test_provider_callbacks.py::test_10_concurrent_final_leg_failures_refund_once tests/integration/test_webhook_signatures.py::test_invalid_provider_signature_changes_no_task_state tests/integration/test_provider_callbacks.py::test_rollback_before_callback_commit_preserves_attempt`; Evidence `<attemptDir>/task-6-integer-generator-service.json`.
  Commit: Y | `feat(providers): route signed outcomes through the eligible next leg`
  Recommended task executor category: `deep-low` — provider responses, callback replay, and per-leg policy must converge on one guarded state transition.

- [ ] 7. Coordinate watchdog timeouts and late callbacks across API workers
  What to do / Must NOT do: Start a bounded watchdog loop from every API worker's FastAPI lifespan using `WATCHDOG_POLL_INTERVAL_SECONDS=1`, `WATCHDOG_BATCH_SIZE=50`, and `PROVIDER_TIMEOUT=60` defaults (all configurable). Select due task rows with `FOR UPDATE OF task SKIP LOCKED`, lock the current attempt second, and commit timeout/fallback/refund atomically; add an index for unresolved attempts by deadline. A timeout-eligible callback races the same task row; the first commit wins. Do not use in-memory locks or fixed sleeps in tests.
  Closes: GAP-3, GAP-4, GAP-6
  Parallelization: Wave 2 | Blocked by: 2, 5, 6 | Blocks: 8–10
  References (executor has NO interview context - be exhaustive): User request rules 3–8, especially provider timeout, late completion, and four-process requirement; draft `.omo/drafts/integer-generator-service.md:35, 65-70, 115-126, 127-134`; PostgreSQL row locking/transaction docs; SQLAlchemy AsyncSession concurrency docs.
  Acceptance criteria (agent-executable): four concurrent watchdog ticks cannot claim the same task; process death releases row locks; timeout completes fallback/refund once; a callback after watchdog commit cannot change terminal state or add a result; an attempt persisted before an interrupted provider POST is later treated as silent and follows the same timeout/failover rule.
  QA scenarios (name the exact tool + invocation): Happy: `uv run pytest -q tests/integration/test_watchdog.py::test_late_completed_after_watchdog_commit_is_ignored` forces a persisted deadline into the past, runs `watchdog.run_once()`, posts a valid late completion, then asserts final task/output/refund and ledger sum; failure: `uv run pytest -q tests/integration/test_watchdog.py::test_concurrent_watchdogs_claim_task_once tests/integration/test_watchdog.py::test_provider_silence_times_out_and_fails_over tests/integration/test_watchdog.py::test_crash_before_provider_post_times_out_and_fails_over`; Evidence `<attemptDir>/task-7-integer-generator-service.json`.
  Commit: Y | `feat(watchdog): claim due tasks once across all workers`
  Recommended task executor category: `deep-low` — correctness depends on one shared row-lock/CAS arbiter and crash-window behavior across processes.

- [ ] 8. Complete Docker Compose service graph and PostgreSQL test runner
  What to do / Must NOT do: Extend `compose.yaml` so plain `docker compose up` starts the application PostgreSQL, one-shot Alembic migration service, the API with `uvicorn --workers 4`, and two independently configured fake-provider services from the shared provider image. Add healthchecks and `service_healthy`/`service_completed_successfully` dependencies. Add a `test` profile with a separate PostgreSQL test database, test-migration service, test-runner service, and `tests/unit/test_compose_contract.py` so `docker compose up` does not run tests and test fixtures never mutate the application database. Keep Compose free of `container_name` so service replication semantics remain valid.
  Closes: GAP-4, GAP-5, GAP-6
  Parallelization: Wave 3 | Blocked by: 1, 2, 6, 7 | Blocks: 10 | Can parallelize with: 9
  References (executor has NO interview context - be exhaustive): User request “Технические требования” Compose requirement and rules 7–8; draft `.omo/drafts/integer-generator-service.md:35-38, 68-78, 127-134`; official Compose startup-order docs `https://docs.docker.com/compose/how-tos/startup-order/` and service definition docs `https://docs.docker.com/reference/compose-file/services/`.
  Acceptance criteria (agent-executable): `docker compose config -q` exits 0; `docker compose up --build -d` yields healthy application PostgreSQL/API/alpha/beta and completed app migrations; API process command visibly contains `--workers 4`; `docker compose --profile test run --rm tests uv run pytest -q` migrates and uses the separate PostgreSQL test database and exits 0; API startup is gated on healthy database and completed migration.
  QA scenarios (name the exact tool + invocation): Happy: `docker compose config -q && docker compose up --build -d && docker compose ps && docker compose --profile test run --rm tests uv run pytest -q` proves all required services and real-DB tests; failure: `uv run pytest -q tests/unit/test_compose_contract.py::test_api_requires_healthy_database_and_completed_migration` fails if the health/migration dependency contract is removed; Evidence `<attemptDir>/task-8-integer-generator-service.json`.
  Commit: Y | `build(compose): gate four-worker startup on database readiness`
  Recommended task executor category: `unspecified-high` — multi-service wiring, readiness, migrations, and database-backed test execution must agree.

- [ ] 9. Create monochrome architecture and lifecycle graphics
  What to do / Must NOT do: Add `docs/architecture.svg` and `docs/task-lifecycle.svg` as clean black/white vector diagrams showing controllers→services→repositories→PostgreSQL/provider flow and task/attempt transitions including timeout, refund, and stale completion. Add a small automated XML/color-contract check for these machine-consumed assets. Do not add a product UI, external image dependency, font/CDN, or gray/color palette.
  Closes: GAP-7
  Parallelization: Wave 3 | Blocked by: 1, 2, 6, 7 | Blocks: 10 | Can parallelize with: 8
  References (executor has NO interview context - be exhaustive): User request requires modern minimal black-and-white repository graphics; draft `.omo/drafts/integer-generator-service.md:38, 45-50, 63-70, 115-126, 127-134`.
  Acceptance criteria (agent-executable): both SVGs parse as XML, have accessible titles/descriptions, use only black/white fills/strokes, and label both provider paths and terminal failure/refund/late-callback behavior. Todo 10 verifies their README-relative links.
  QA scenarios (name the exact tool + invocation): Happy: `uv run pytest -q tests/docs/test_diagrams.py` asserts the SVG elements/text/colors; failure: `uv run pytest -q tests/docs/test_diagrams.py::test_rejects_external_assets_and_non_monochrome_colors` rejects an external href or non-black/white color; Evidence `<attemptDir>/task-9-integer-generator-service.json`.
  Commit: Y | `docs(graphics): map service boundaries and terminal task outcomes`
  Recommended task executor category: `visual-engineering` — deliver the requested polished, minimal vector diagrams as repository assets.

- [ ] 10. Write the Russian README and migration/runbook guide
  What to do / Must NOT do: Write `README.md` in Russian with service purpose, architecture and linked SVGs, endpoint table, environment setup, `docker compose up`, real-PostgreSQL test/lint/type-check commands, initial migration command and exact command for generating/applying a later migration, and the database guarantees. Add `scripts/smoke.py` that signs a test payment, creates a user/task through the live API, and verifies task/balance responses without polling for a provider callback; add `tests/docs/test_readme_contract.py` to verify relative asset links and executable command targets, not prose wording. Explain (a) unique operation keys + one transaction for ledger/status, (b) crash before webhook commit rolls back and after commit a retry is a no-op, (c) attempt-commit/provider-HTTP crash window, (d) first committed timeout/completion outcome and ignored stale completion, and (e) identical POST `/generate` without an idempotency key is a new order. Do not claim exactly-once HTTP/provider execution or production SLA.
  Closes: GAP-5, GAP-7
  Parallelization: Wave 3 | Blocked by: 1–9 | Blocks: — | Can parallelize with: none
  References (executor has NO interview context - be exhaustive): User request “Результат” README requirements and “Технические требования” migrations; draft `.omo/drafts/integer-generator-service.md:57-78, 99-111, 115-126, 127-134`.
  Acceptance criteria (agent-executable): README commands match `compose.yaml`/`pyproject.toml`; `docker compose up --build -d`, the documented test runner, `ruff check`, `ruff format --check`, `mypy`, and Alembic upgrade all execute successfully; README links resolve to both local SVGs and every requested guarantee/decision is present in the implementation contract.
  QA scenarios (name the exact tool + invocation): Happy: `BASE_URL=http://localhost:8000 uv run python scripts/smoke.py` creates a signed payment/user/task and checks the real task/balance endpoints; also run `docker compose --profile test run --rm tests uv run pytest -q && docker compose --profile test run --rm tests uv run ruff check . && docker compose --profile test run --rm tests uv run ruff format --check . && docker compose --profile test run --rm tests uv run mypy .`; failure: `uv run pytest -q tests/docs/test_readme_contract.py::test_rejects_broken_relative_asset_link` reports a missing README asset as failure; Evidence `<attemptDir>/task-10-integer-generator-service.json`.
  Commit: Y | `docs(readme): explain ledger guarantees and local operations`
  Recommended task executor category: `writing` — the remaining deliverable is precise Russian developer documentation and command/runbook alignment.

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
  Verify every user-assignment requirement maps to one of todos 1–10 and every IS-1…IS-7 has a named QA scenario/evidence artifact; check all explicit exclusions remain out of scope. Evidence `<attemptDir>/final-plan-audit-integer-generator-service.json`.
  Recommended task executor category: `unspecified-high` — independently audit scope coverage, assumptions, task dependencies, and acceptance evidence.
- [ ] F2. Code quality review
  Run `docker compose --profile test run --rm tests uv run ruff check . && docker compose --profile test run --rm tests uv run ruff format --check . && docker compose --profile test run --rm tests uv run mypy . && docker compose --profile test run --rm tests uv run pytest -q`; report any finding with exact path and output. Evidence `<attemptDir>/final-quality-integer-generator-service.json`.
  Recommended task executor category: `unspecified-high` — review cross-module correctness and the full automated quality gate.
- [ ] F3. Real manual QA
  Run `docker compose up --build -d`, assert all required services are healthy and migrations completed, then run `curl -fsS http://localhost:8000/healthz`, `curl -fsS http://localhost:8000/docs`, and `BASE_URL=http://localhost:8000 uv run python scripts/smoke.py`; the smoke script must demonstrate signed payment→balance→generate→task-status on the actual running service. Evidence `<attemptDir>/final-manual-qa-integer-generator-service.json`.
  Recommended task executor category: `unspecified-high` — prove the delivered public API and Compose services work on the real surface.
- [ ] F4. Ideal-state fidelity
  Independently compare delivery to IS-1…IS-7 row by row using the named integration tests and evidence from F2/F3; any shortfall becomes a new numbered implementation todo. Evidence `<attemptDir>/final-fidelity-integer-generator-service.json`.
  Recommended task executor category: `unspecified-high` — verify the actual delivery, not the plan author's report, against every affected-user outcome.

## Commit strategy
Create one local commit per completed implementation todo, only after that todo's tests pass; use the exact rationale-bearing message listed on that todo. Keep the history linear and reviewable. Do not create a GitHub remote or push. If a todo fails its acceptance criteria, fix it before committing rather than recording a green commit that does not build.

## Success criteria
> One row per IS row. The plan is complete only when every IS row has a delivering todo and a proving QA scenario; F4 checks the delivered behavior against these rows 1:1, and a shortfall becomes new `- [ ] N.` rows, never a note.
| IS | Delivering todo(s) | Proving QA scenario | Evidence |
| --- | --- | --- | --- |
| IS-1 | 3, 5 | `test_valid_request_debits_once_and_returns_task_id`; `test_no_compatible_leg_returns_400_without_debit`; `test_fourth_active_task_returns_429_without_debit` | `<attemptDir>/task-3-integer-generator-service.json`, `<attemptDir>/task-5-integer-generator-service.json` |
| IS-2 | 2, 4, 5, 6 | `test_20_concurrent_duplicate_success_webhooks_credit_once`; `test_10_concurrent_final_leg_failures_refund_once`; balance equals ledger sum | `<attemptDir>/task-2-integer-generator-service.json` through `<attemptDir>/task-6-integer-generator-service.json` |
| IS-3 | 2, 5, 6, 7 | `test_first_provider_failure_succeeds_on_second_with_two_attempts`; sync/moderation/payload matrix; timeout history assertions | `<attemptDir>/task-5-integer-generator-service.json` through `<attemptDir>/task-7-integer-generator-service.json` |
| IS-4 | 6, 7, 8 | `test_concurrent_watchdogs_claim_task_once`; `test_late_completed_after_watchdog_commit_is_ignored`; four-worker Compose check | `<attemptDir>/task-6-integer-generator-service.json` through `<attemptDir>/task-8-integer-generator-service.json` |
| IS-5 | 2, 8, 10 | `alembic upgrade head`; `docker compose up --build -d`; service health assertions and documented next-migration command | `<attemptDir>/task-2-integer-generator-service.json`, `<attemptDir>/task-8-integer-generator-service.json`, `<attemptDir>/task-10-integer-generator-service.json` |
| IS-6 | 1–8, 10 | four required integration tests, invalid-signature tests, `ruff`, format check, mypy, full pytest on PostgreSQL, README command/link contract | `<attemptDir>/task-1-integer-generator-service.json` through `<attemptDir>/task-8-integer-generator-service.json`, `<attemptDir>/task-10-integer-generator-service.json` |
| IS-7 | 9, 10 | SVG asset contract tests; README links/commands and guarantee checks | `<attemptDir>/task-9-integer-generator-service.json`, `<attemptDir>/task-10-integer-generator-service.json` |
