# Testing Guide

This document describes the test strategy, structure, and how to run tests locally and in CI.

---

## Test philosophy

| Layer | What is tested | What is mocked |
|-------|---------------|----------------|
| **Models** | XML/JSON parse + serialise roundtrips | Nothing — pure Python |
| **Transforms** | Business logic (happy path + error paths) | DNS resolver, HTTP clients |
| **Auth** | JWT decode, scope check, JWKS cache | Keycloak HTTP, `jwt.decode` |
| **Routers** | HTTP layer (status codes, content-type, auth) | Auth dependency, DNS, Dapr pub/sub |
| **Schema** | Mapping lookup, OpenSearch index body generation | Nothing — pure Python |
| **Writers** | Upsert logic, Cypher patterns, error isolation | `httpx.AsyncClient`, Neo4j driver |
| **Ingestion main** | Dapr subscription, CloudEvent processing, health | Both writers |

**Guiding rules:**

- No test makes a real network call. All I/O is mocked at the call site.
- Tests are hermetic: order-independent, no shared mutable state between tests.
- Mocks are as narrow as possible — only the method that makes the external call.
- `autouse` fixtures reset shared module-level state (JWKS cache, writer globals).

---

## Directory layout

```text
src/
├── transform-hub/
│   ├── tests/
│   │   ├── conftest.py              # fixtures: entities, requests, auth override, TestClient
│   │   ├── test_models.py           # MaltegoEntity, TransformRequest, TransformResponse
│   │   ├── test_transforms.py       # DomainToIP, DomainToMX, URLToDomain, WHOIS, IPToGeo
│   │   ├── test_auth.py             # JWKS fetch, verify_token, scope enforcement
│   │   └── test_routers.py          # /api/v2/transforms, /api/v2/manifest, /health
│   ├── pytest.ini
│   └── requirements-test.txt
│
└── ingestion-worker/
    ├── tests/
    │   ├── conftest.py              # fixtures: event payloads, mock writers
    │   ├── test_schema.py           # ENTITY_SCHEMA, RELATIONSHIP_SCHEMA, index mappings
    │   ├── test_writers.py          # OpenSearchWriter, Neo4jWriter (all mocked I/O)
    │   └── test_main.py             # /dapr/subscribe, /ingest, /health/live, /health/ready
    ├── pytest.ini
    └── requirements-test.txt
```

---

## Running tests locally

### Transform Hub

```bash
cd src/transform-hub
pip install -r requirements-test.txt
python -m pytest -v
```

With coverage:

```bash
python -m pytest --cov=. --cov-report=term-missing
```

Run only one test file:

```bash
python -m pytest tests/test_transforms.py -v
```

Run only a specific class or test:

```bash
python -m pytest tests/test_transforms.py::TestDomainToIP::test_single_ip -v
```

### Ingestion Worker

```bash
cd src/ingestion-worker
pip install -r requirements-test.txt
python -m pytest -v
```

---

## Test inventory

### `test_models.py` — 16 tests

| Class | Tests |
|-------|-------|
| `TestMaltegoEntity` | basic fields, add_field, XML element with/without fields |
| `TestTransformRequestXML` | parse entity, parse limits, parse additional fields, missing limits defaults, malformed XML raises |
| `TestTransformRequestJSON` | parse entity, parse limits, empty entities |
| `TestTransformResponse` | XML roundtrip, UI message in XML, to_dict structure, error/partial-error responses, empty response |

### `test_transforms.py` — 22 tests

| Class | Tests |
|-------|-------|
| `TestDomainToIP` | single IP, multiple IPs, soft-limit respected, NXDOMAIN error, NoAnswer error, generic exception |
| `TestDomainToMX` | single MX, multiple MX, DNS error |
| `TestURLToDomain` | basic extraction, IP entity returned, DNS failure still returns domain, empty value error |
| `TestDomainToWHOIS` | Person entity returned, Email entity returned, HTTP error |
| `TestIPToGeolocation` | Location entity returned, HTTP error, API status=fail |
| `TestBaseTransformContract` | empty entities returns error, registry contains expected transforms, unknown transform returns None, all transforms have required meta |

### `test_auth.py` — 7 tests

| Class | Tests |
|-------|-------|
| `TestFetchJWKS` | successful fetch, fetch failure raises |
| `TestVerifyToken` | invalid token raises 401, expired token raises 401, missing scope raises 403, valid token returns claims, no required scope skips check |

### `test_routers.py` — 12 tests

| Class | Tests |
|-------|-------|
| `TestManifestRouter` | returns 200, contains transforms, transform has required keys, requires auth |
| `TestTransformRouter` | XML 200, JSON 200, unknown transform 404, malformed body 400, list transforms, XML content-type, JSON content-type |
| `TestHealthEndpoint` | returns 200, returns `{status: ok}` |

### `test_schema.py` — 22 tests

| Class | Tests |
|-------|-------|
| `TestEntitySchema` | all 10 expected types present, every mapping has index/label/id_property/fields/value/first_seen/last_seen |
| `TestGetEntityMapping` | known type returns mapping, unknown returns None, IP mapping, location geo_point |
| `TestRelationshipSchema` | 6 expected relationships present, all rel_types non-empty + UPPERCASE, all have source/target labels |
| `TestGetRelationshipMapping` | known triple returns mapping, unknown triple returns None, specific WHOIS/geo lookups, wrong transform name |
| `TestOpenSearchIndexMapping` | explicit mapping for known type, dynamic=false, fallback for unknown, entity_type field always present, IP type, date fields |

### `test_writers.py` — 14 tests

| Class | Tests |
|-------|-------|
| `TestEntityDocId` | same inputs same ID, different types different ID, different values different ID, ID is hex string |
| `TestOpenSearchWriter` | ensure_index creates if not exists, skips if exists, uses cache, upsert calls POST, uses deterministic ID, bulk sends ndjson, bulk empty noop, unknown type uses fallback index |
| `TestNeo4jWriter` | ingest merges input node, merges relationship, no relationship for unknown triple, ensure_constraints for all labels, MERGE in Cypher, unknown type uses generic label |

### `test_main.py` — 16 tests

| Class | Tests |
|-------|-------|
| `TestDaprSubscribe` | returns 200, returns list, subscription fields, topic name |
| `TestIngestEndpoint` | valid event SUCCESS, malformed event DROP, OS writer called, Neo4j writer called, correct transform name, event without data key, OS failure doesn't block Neo4j, Neo4j failure doesn't block OS, WHOIS event, empty output entities |
| `TestHealthEndpoints` | liveness 200, readiness 200 when healthy, readiness when no writers |

---

## Coverage targets

| Package | Minimum | Enforced in CI? |
|---------|---------|----------------|
| `src/transform-hub` | 70% | ✅ `--cov-fail-under=70` |
| `src/ingestion-worker` | 70% | ✅ `--cov-fail-under=70` |

Coverage is measured with `pytest-cov`. Reports are uploaded as CI artifacts.

---

## CI integration

Tests run in the `applications.yaml` pipeline as two parallel jobs:

```text
validate-manifests ──┐
                     ├──► build ──► deploy-dev ──► deploy-prod
test-transform-hub ──┤
test-ingestion-worker┘
```

Both test jobs must pass before the image build starts. A coverage drop below 70% fails the job
and blocks the PR.

Coverage XML reports are uploaded as workflow artifacts (`transform-hub-coverage`,
`ingestion-worker-coverage`) and are available for 90 days.

---

## Adding tests for a new transform

1. Add a new test class to `test_transforms.py`:

```python
class TestMyNewTransform:
    @patch("src.transform_hub.transforms.my_transform.some_external_call")
    def test_happy_path(self, mock_call):
        from ..transforms.my_transform import MyNewTransform
        mock_call.return_value = ...   # mock the external response
        resp = run(MyNewTransform, "maltego.InputType", "input-value")
        assert len(resp.entities) > 0
        assert resp.entities[0].type == "maltego.OutputType"

    @patch("src.transform_hub.transforms.my_transform.some_external_call")
    def test_error_path(self, mock_call):
        from ..transforms.my_transform import MyNewTransform
        mock_call.side_effect = Exception("external failure")
        resp = run(MyNewTransform, "maltego.InputType", "input-value")
        assert len(resp.ui_messages) > 0   # error message returned
        assert len(resp.entities) == 0
```

1. If the transform introduces a new entity type or relationship, add corresponding tests
   to `test_schema.py` in the `TestEntitySchema.EXPECTED_TYPES` list and
   `TestRelationshipSchema.EXPECTED_RELATIONSHIPS`.

---

## Markers

```bash
# Skip slow tests
pytest -m "not slow"

# Skip integration tests (require live services)
pytest -m "not integration"

# Run only fast unit tests
pytest -m "not slow and not integration"
```
