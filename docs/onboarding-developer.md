# Onboarding — Business Developer

Welcome. This guide gets you from zero to shipping your first transform in under an hour.
You do not need to understand Kubernetes, Helm, or Terraform to contribute.

**Your job**: write a Python class that takes a Maltego entity as input and returns enriched
entities as output. The platform handles authentication, rate-limiting, TLS, logging, and
deployment automatically.

---

## Prerequisites

You need these on your laptop:

| Tool | Version | Install |
|------|---------|---------|
| Python | `3.12+` | [python.org](https://python.org) or `pyenv` |
| Poetry or pip | any | `pip install poetry` |
| Docker | any | [docker.com](https://docker.com) |
| Git | any | OS package manager |
| A Keycloak account | — | Ask your admin (see [Who to ask](#who-to-ask)) |

You do **not** need `kubectl`, `helm`, `terraform`, or cloud CLI tools.

---

## 1. Clone and set up the local environment

```bash
git clone <repo-url>
cd repo0

# Install Python dependencies
cd src/transform-hub
pip install -r requirements.txt

# Verify everything imports correctly
python -c "from transforms import list_transforms; print(list_transforms())"
```

You should see the built-in transforms listed (DomainToIP, DomainToWHOIS, etc.).

---

## 2. Understand the project structure

```
src/transform-hub/
├── main.py                  # FastAPI app assembly — you don't touch this
├── config.py                # Settings (env-driven) — you don't touch this
├── auth.py                  # JWT validation — you don't touch this
├── models/
│   └── maltego.py           # MaltegoEntity, TransformRequest, TransformResponse
├── transforms/
│   ├── __init__.py          # @register decorator + auto-discovery — you don't touch this
│   ├── base.py              # BaseTransform, TransformMeta — inherit from this
│   ├── domain_to_ip.py      # ← example: read this first
│   └── ...                  # ← your files go here
└── routers/                 # HTTP routing — you don't touch this
```

Your entire contribution is a single file in `transforms/`.

---

## 3. Read an existing transform

Open `src/transform-hub/transforms/domain_to_ip.py`. Notice:

1. It imports `BaseTransform`, `TransformMeta`, and `register`.
2. The `@register` decorator is the only wiring needed — no config files to edit.
3. `meta` declares what Maltego shows in the UI.
4. `run()` receives a `MaltegoEntity` and a `TransformRequest`, returns a `TransformResponse`.
5. The function calls `dns.resolver.resolve()` — that is the entire business logic.

Everything else (auth, rate-limiting, XML serialisation, routing) happens outside your file.

---

## 4. Write your first transform

Create `src/transform-hub/transforms/my_transform.py`:

```python
from .base import BaseTransform, TransformMeta
from ..models.maltego import MaltegoEntity, TransformRequest, TransformResponse
from . import register


@register
class DomainToMXRecord(BaseTransform):
    name = "DomainToMXRecord"
    meta = TransformMeta(
        display_name="Domain To MX Records",
        description="Returns mail exchange records for a domain",
        input_entity="maltego.Domain",
        author="Your Name <you@example.com>",
        version="1.0",
    )

    def run(self, entity: MaltegoEntity, request: TransformRequest) -> TransformResponse:
        import dns.resolver

        response = TransformResponse()
        try:
            answers = dns.resolver.resolve(entity.value, "MX")
            for r in answers:
                response.add_entity(
                    "maltego.MXRecord",
                    {
                        "value": str(r.exchange).rstrip("."),
                        "mxrecord.priority": str(r.preference),
                    },
                )
        except Exception as exc:
            response.add_ui_message(f"DNS lookup failed: {exc}", message_type="PartialError")

        return response
```

### Rules

- Always catch exceptions and return a `PartialError` message rather than raising.
- Always use pinned library versions in `requirements.txt` when adding a new dependency.
- Never store credentials in code — use `os.environ["SECRET_NAME"]` (injected by Dapr).
- Input validation: `entity.value` is already a string, but always handle empty/None gracefully.

---

## 5. Test locally

### Unit test (no server needed)

```python
# test_my_transform.py
from transforms.my_transform import DomainToMXRecord
from models.maltego import MaltegoEntity, TransformRequest

def test_domain_to_mx():
    transform = DomainToMXRecord()
    entity = MaltegoEntity(type="maltego.Domain", value="gmail.com")
    request = TransformRequest(entity=entity)
    response = transform.run(entity, request)
    assert len(response.entities) > 0
    assert all(e.type == "maltego.MXRecord" for e in response.entities)
```

Run with:

```bash
cd src/transform-hub
python -m pytest test_my_transform.py -v
```

### Integration test (with running server)

```bash
# Start the server
uvicorn main:app --reload --port 8080

# In another terminal — call via XML (Maltego format)
curl -s -X POST http://localhost:8080/api/v2/transforms/DomainToMXRecord \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/xml" \
  -d '<MaltegoMessage><MaltegoTransformRequestMessage>
        <Entities><Entity Type="maltego.Domain"><Value>gmail.com</Value></Entity></Entities>
        <Limits SoftLimit="12" HardLimit="12"/>
      </MaltegoTransformRequestMessage></MaltegoMessage>'
```

> **Token**: get one from Keycloak (see [Getting a token](#getting-a-token-for-local-testing)).

---

## 6. Getting a token for local testing

```bash
curl -s -X POST \
  "https://auth.example.com/realms/maltego-hub/protocol/openid-connect/token" \
  -d "grant_type=client_credentials" \
  -d "client_id=<your-client-id>" \
  -d "client_secret=<your-client-secret>" \
  | jq -r .access_token
```

Ask your admin for `client_id` and `client_secret`. Store them in a `.env` file locally
(never commit this file — it is in `.gitignore`).

---

## 7. Submit a pull request

```bash
git checkout -b feat/domain-to-mx
git add src/transform-hub/transforms/my_transform.py
git commit -m "feat: add DomainToMXRecord transform"
git push origin feat/domain-to-mx
# Open PR on GitHub
```

The CI pipeline automatically runs:

| Check | What it does | You need to fix if… |
|-------|-------------|---------------------|
| Unit tests | Runs `pytest` | Any test fails |
| Trivy image scan | Checks your new dependency for CVEs | CRITICAL CVE found in a new lib |
| Doc coverage | Checks if code paths have matching docs | New transform not mentioned in `docs/transform-hub.md` |
| Markdown lint | Lints any `.md` files you changed | Line length, heading structure violations |

If doc coverage flags your transform, add a row to the transform table in
`docs/transform-hub.md`. Template:

```markdown
| `DomainToMXRecord` | `maltego.Domain` | `maltego.MXRecord` | DNS MX record lookup |
```

---

## 8. After your PR merges

1. The `applications.yaml` CI pipeline builds and pushes the image automatically.
2. Dapr's `_autodiscover()` picks up your transform at pod startup — no manual registration.
3. Your transform appears in `GET /api/v2/manifest` within minutes of deployment.
4. Any Maltego client that has imported the hub will see the new transform on next refresh.

---

## Key Concepts — Quick Reference

| Concept | Where it lives | You need to know |
|---------|---------------|-----------------|
| `@register` | `transforms/__init__.py` | Decorates your class — that's all the wiring needed |
| `BaseTransform` | `transforms/base.py` | Inherit from it; implement `run()` |
| `TransformMeta` | `transforms/base.py` | Describes your transform to Maltego |
| `MaltegoEntity` | `models/maltego.py` | Input: `.type` and `.value` are the key fields |
| `TransformResponse` | `models/maltego.py` | Output: call `.add_entity(type, fields)` |
| `TransformRequest` | `models/maltego.py` | Full request context; `.entity` is the input |
| Entity types | Maltego docs | Use `maltego.Domain`, `maltego.IPv4Address`, etc. |

---

## Who to Ask

| Question | Contact |
|----------|---------|
| I need a Keycloak client credential | Platform admin |
| My transform is deployed but not appearing in Maltego | Platform admin (check pod logs) |
| I need a new data source API key injected as a secret | Platform admin |
| Deployment pipeline is failing for a non-code reason | Platform admin |
| Code review / transform logic | Team lead / peer review on PR |

See [docs/developer-experience.md](./developer-experience.md) for the full platform philosophy
and a detailed explanation of what the platform handles so you don't have to.
