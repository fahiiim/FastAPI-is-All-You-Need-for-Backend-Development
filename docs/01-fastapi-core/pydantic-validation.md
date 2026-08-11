# Pydantic v2 and Validation Boundaries

Pydantic turns untrusted Python or JSON-shaped data into typed objects according to an explicit schema. FastAPI uses those schemas for request validation, response serialization, JSON Schema, and OpenAPI. Pydantic can prove that data has the declared shape; it cannot prove that the caller is authorized, inventory exists, an email is deliverable, or a database invariant will survive concurrency.

This chapter uses Pydantic v2 APIs such as `model_validate`, `model_dump`, `field_validator`, and `ConfigDict`.

## 1. A model is a boundary contract

```python
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrderItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    quantity: int = Field(ge=1, le=100)
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=1, max_length=80)
    items: list[OrderItemInput] = Field(min_length=1, max_length=100)
    requested_at: datetime | None = None
```

Pydantic parses compatible input, validates constraints, and produces a model. `extra="forbid"` rejects undeclared fields, which is valuable for commands where silently ignored client mistakes are dangerous. For forward-compatible event consumers or loose metadata, ignoring or preserving extra fields may be a deliberate alternative.

Use transport models at boundaries:

- Request models allow only client-writable fields.
- Response models allow only client-visible fields.
- Domain types represent business meaning and behavior.
- ORM models represent persistence mapping and relationships.
- Integration models represent a provider's contract.

One class rarely serves all five roles safely.

## 2. Required, nullable, and default are different

In Pydantic v2, the annotation and default together determine behavior:

```python
from pydantic import BaseModel


class Example(BaseModel):
    required_text: str
    required_nullable_text: str | None
    optional_text: str = "default"
    optional_nullable_text: str | None = None
```

| Field | May be omitted | May be `null` |
| --- | --- | --- |
| `required_text` | No | No |
| `required_nullable_text` | No | Yes |
| `optional_text` | Yes | No |
| `optional_nullable_text` | Yes | Yes |

`T | None` means nullable. It does not, by itself, mean the field may be omitted. This distinction is critical in PATCH operations and generated clients.

Avoid mutable class-level defaults in ordinary Python. Pydantic handles model defaults deliberately, but an explicit factory communicates per-instance intent:

```python
from pydantic import BaseModel, Field


class SearchFilter(BaseModel):
    tags: list[str] = Field(default_factory=list)
```

## 3. Field constraints and metadata

Use `Field` for representation constraints and schema documentation:

```python
from typing import Annotated

from pydantic import BaseModel, Field

CountryCode = Annotated[
    str,
    Field(
        pattern=r"^[A-Z]{2}$",
        description="ISO 3166-1 alpha-2 country code",
        examples=["BD"],
    ),
]


class AddressInput(BaseModel):
    line1: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    country_code: CountryCode
```

Constraints protect downstream work and make OpenAPI useful. They are not a substitute for limits at the reverse proxy, database, or provider. A `max_length` check after a huge request has already been buffered does not protect the network or parser from the full cost.

Choose numeric types based on domain semantics:

- `int` for exact integral values and minor currency units.
- `Decimal` for decimal arithmetic with explicit precision and rounding.
- `float` for measurements where binary floating-point behavior is acceptable.

JSON itself does not preserve Python type distinctions. Document wire representations for decimal, timestamp, UUID, and binary values.

## 4. Nested models and collection bounds

Nested models express structure and produce nested error locations:

```python
from pydantic import BaseModel, Field


class Recipient(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    address: AddressInput


class ShipmentCreate(BaseModel):
    recipient: Recipient
    package_ids: list[str] = Field(min_length=1, max_length=50)
```

Validate both the collection and each item. A list of a million valid strings is still an availability problem. If duplicate items are invalid, use a validator that preserves a useful error rather than converting blindly to a `set` and changing order.

Deeply nested public schemas are hard to evolve and can produce expensive error payloads. Prefer an identifier for an independently managed resource instead of embedding its entire representation in every command.

## 5. Coercion versus strict input

Pydantic supports useful coercion. For example, a JSON string may parse into a UUID or datetime. Coercion also creates ambiguity when `"1"`, `1`, and `true` should not be treated alike.

Enable strict behavior at the appropriate scope:

```python
from pydantic import BaseModel, ConfigDict, StrictInt


class InventoryAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    delta: StrictInt
```

Or request strict validation at a direct boundary:

```python
adjustment = InventoryAdjustment.model_validate(raw_data, strict=True)
```

Strict mode is not automatically better. HTTP query parameters arrive as strings, and useful parsing is part of FastAPI's ergonomics. Decide strictness by contract and test edge cases. Do not turn it on globally without assessing clients and source formats.

## 6. Field validators

Field validators normalize or constrain one field beyond built-in metadata:

```python
from pydantic import BaseModel, ConfigDict, field_validator


class RegistrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: str
    display_name: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        local, separator, domain = value.rpartition("@")
        if not separator or not local or not domain:
            raise ValueError("email must contain a local part and domain")
        return f"{local}@{domain.lower()}"
```

Be cautious with email normalization. Lowercasing a domain is safe, while changing the local part can alter identity depending on product policy and provider behavior. A dedicated email validation library can validate syntax, but deliverability still requires an ownership verification flow.

Validator modes have different trust levels:

- `before` receives raw input and is useful for controlled normalization.
- `after` receives a value already validated as the annotated type.
- `plain` replaces ordinary inner validation and is easy to misuse.
- `wrap` can run code around inner validation and should remain rare and focused.

Prefer `after` when possible because the value already satisfies the field type. A `before` validator must handle every raw input shape it may receive.

## 7. Model validators and cross-field invariants

Use a model validator when a rule relates multiple fields:

```python
from datetime import datetime
from typing import Self

from pydantic import BaseModel, model_validator


class ReservationWindow(BaseModel):
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def ends_after_start(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("timestamps must include timezone information")
        return self
```

This is valid model-level validation because it is deterministic and depends only on supplied data. Do not query a database, call a provider, or perform slow I/O in a Pydantic validator:

- Pydantic validators are synchronous in normal validation flow.
- I/O hides latency inside parsing.
- The check can race before the eventual write.
- Validation becomes difficult to reuse and test.

Check database-backed uniqueness in a service for a friendly failure and enforce it with a database constraint for correctness.

## 8. Reusable custom validation

`Annotated` can package a domain parser without forcing every model to repeat a decorator:

```python
from typing import Annotated

from pydantic import AfterValidator, BaseModel


def normalize_reference(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized.startswith("ORD-"):
        raise ValueError("reference must start with ORD-")
    if len(normalized) > 40:
        raise ValueError("reference is too long")
    return normalized


OrderReference = Annotated[str, AfterValidator(normalize_reference)]


class OrderLookup(BaseModel):
    reference: OrderReference
```

A value-object class may be more appropriate when the value owns behavior and appears throughout the domain. An annotation is useful when the main need is boundary parsing plus JSON Schema.

Custom validators should be deterministic, bounded, and free of secrets in their errors. Avoid regular expressions with pathological backtracking on untrusted long strings.

## 9. Discriminated unions

Use a discriminator when a field can contain one of several explicit shapes:

```python
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class CardPayment(BaseModel):
    kind: Literal["card"]
    payment_method_id: str


class BankTransferPayment(BaseModel):
    kind: Literal["bank_transfer"]
    bank_account_id: str


Payment = Annotated[
    CardPayment | BankTransferPayment,
    Field(discriminator="kind"),
]


class CheckoutInput(BaseModel):
    payment: Payment
```

The discriminator makes validation predictable and produces clearer OpenAPI than trying each union member based on overlapping fields. Treat discriminator values as public API surface. Adding a new member can break clients that assume an exhaustive enum even if the server considers the change additive.

## 10. Deserialization entry points

Pydantic v2 provides explicit validation methods:

```python
payload = OrderCreate.model_validate(python_mapping)
payload_from_json = OrderCreate.model_validate_json(raw_json_bytes)
```

Use `model_validate` for Python objects and mappings. Use `model_validate_json` when Pydantic owns parsing of raw JSON, which can avoid an extra Python JSON intermediate. FastAPI already manages its request parsing path, so do not manually reparse request bodies just to call it.

For attributes on ORM or other objects:

```python
from pydantic import BaseModel, ConfigDict


class OrderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str


view = OrderView.model_validate(orm_order)
```

Attribute access can trigger lazy database I/O. In async SQLAlchemy it can also fail when implicit I/O is not allowed. Load the required fields and relationships deliberately, or map query rows to response models explicitly.

## 11. Serialization and field selection

Use `model_dump` for Python data and `model_dump_json` for serialized JSON:

```python
python_data = payload.model_dump(mode="python")
json_ready = payload.model_dump(mode="json")
json_text = payload.model_dump_json()
```

The `json` mode converts supported values such as UUID and datetime to JSON-compatible forms. FastAPI applies its own response serialization pipeline, so returning `model_dump_json()` from a normal route can accidentally double-encode JSON as a string.

Useful field-selection options include:

- `exclude_unset=True` for fields omitted by the caller, commonly in partial updates.
- `exclude_none=True` only when the public contract says null-valued fields should disappear.
- `exclude_defaults=True` when omitting defaults is intentional and compatible.
- `by_alias=True` when serialization aliases define the wire contract.

Do not use exclusions as an ad hoc security layer on a broad model. Define a response model that never contains the secret field.

### Serialization aliases

An internal Python name can differ from a legacy or external field:

```python
from pydantic import BaseModel, Field


class LegacyCustomerView(BaseModel):
    customer_id: str = Field(serialization_alias="customerId")
```

Aliases are useful at integration boundaries. Excessive aliasing inside core models makes code harder to follow. Keep one canonical internal vocabulary and translate at the edge.

## 12. Field serializers and computed fields

A field serializer controls wire representation:

```python
from datetime import datetime, timezone

from pydantic import BaseModel, field_serializer


class AuditEvent(BaseModel):
    occurred_at: datetime

    @field_serializer("occurred_at")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
```

Use custom serialization to implement a real contract, not cosmetic inconsistency. Ensure input parsing, OpenAPI, examples, and tests match the chosen representation.

Computed fields expose derived values during serialization:

```python
from decimal import Decimal

from pydantic import BaseModel, computed_field


class InvoiceView(BaseModel):
    subtotal: Decimal
    tax: Decimal

    @computed_field
    @property
    def total(self) -> Decimal:
        return self.subtotal + self.tax
```

Computed fields should be pure and cheap. Do not hide database queries, network calls, or expensive aggregation behind property access during serialization.

## 13. Model configuration

`ConfigDict` makes model-level policy explicit:

```python
from pydantic import BaseModel, ConfigDict


class CommandModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )
```

Useful options include:

- `extra`: ignore, allow, or forbid undeclared input.
- `from_attributes`: allow validation from object attributes.
- `strict`: select strict validation at model scope.
- `frozen`: prevent normal attribute assignment after creation.
- `validate_assignment`: validate later assignment for mutable models.
- `validate_by_name` and `validate_by_alias`: control whether field names and aliases are accepted during validation.
- `json_schema_extra`: add documented examples or schema metadata.

Do not create one inherited base configuration for every model without reviewing boundaries. Provider payloads, public commands, internal events, and responses can require different policies.

`frozen=True` discourages mutation but does not make nested mutable values deeply immutable. Prefer immutable nested types when immutability is part of the design.

## 14. Validation errors and public error design

Pydantic raises `ValidationError` with structured error entries:

```python
from pydantic import ValidationError

try:
    OrderCreate.model_validate(candidate)
except ValidationError as exc:
    for error in exc.errors(include_input=False):
        print(error["loc"], error["type"], error["msg"])
```

FastAPI converts request validation errors into its default HTTP response. A production API may register a handler to map them into a stable Problem Details format. Preserve useful locations and machine codes, but do not reflect passwords, authorization values, full documents, or other sensitive input.

Separate three categories:

1. **Transport validation**: wrong type, missing field, malformed UUID. Usually 4xx.
2. **Domain rejection**: invalid transition, insufficient stock. Mapped to a deliberate 4xx such as 409.
3. **Server contract violation**: response does not match the response model. A 500-class error and operational signal.

Changing validation strictness, requiredness, a constraint, or error shape is an API compatibility decision.

## 15. PATCH without losing intent

An update model must distinguish omitted from explicit null:

```python
from pydantic import BaseModel, ConfigDict, Field


class AccountPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=30)


patch = AccountPatch.model_validate({"phone": None})
assert patch.model_fields_set == {"phone"}
assert patch.model_dump(exclude_unset=True) == {"phone": None}
```

The service still needs a writable-field policy, authorization, and concurrency protection. `model_dump(exclude_unset=True)` should not be passed blindly into a database update when field names, transformations, audit rules, or permissions differ.

## 16. Pydantic models versus ORM models

Treating a SQLAlchemy model as the API schema creates several hazards:

- Persistence columns become accidentally writable or visible.
- Relationships can trigger N+1 queries during serialization.
- Database nullability and API optionality are conflated.
- Internal migration choices become public API changes.
- A session-bound entity leaks beyond its transaction lifetime.
- Domain invariants become scattered among validators and ORM hooks.

Map explicitly at the boundary:

```python
class UserResponse(BaseModel):
    id: str
    display_name: str


def to_user_response(user: UserRecord) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        display_name=user.display_name,
    )
```

For simple internal CRUD, `from_attributes=True` can reduce mapping code. The tradeoff is acceptable when fields are reviewed, queries eagerly load required data, and response tests guard against leakage. Abstraction should follow risk, not ceremony.

## 17. Settings are a separate concern

Pydantic settings moved to the `pydantic-settings` package in the v2 ecosystem. Settings models read configuration sources and should be instantiated at startup or through a cached dependency, not separately in every request.

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORDERS_", extra="ignore")

    database_url: SecretStr
    provider_timeout_seconds: float = 5.0
```

`SecretStr` reduces accidental display but does not encrypt a secret or prevent deliberate access. Do not serialize the settings model into logs or responses.

## 18. Performance decisions

Pydantic v2 uses `pydantic-core`, but validation and serialization are not free. Measure before optimizing.

Practical guidance:

- Validate once at the boundary rather than repeatedly rebuilding identical models between layers.
- Reuse a `TypeAdapter` for non-model types instead of constructing one in a hot loop.
- Use `model_validate_json` when your code truly starts with raw JSON and Pydantic owns parsing.
- Page or stream large collections rather than validating enormous response lists.
- Avoid deeply recursive or highly ambiguous unions.
- Keep validators deterministic and bounded.
- Select only fields required for a response so ORM loading does not dominate serialization.
- Profile end-to-end latency before removing response validation that protects a public contract.

Example for a reusable non-model adapter:

```python
from pydantic import TypeAdapter

order_ids_adapter = TypeAdapter(list[str])


def parse_order_ids(raw_json: bytes) -> list[str]:
    return order_ids_adapter.validate_json(raw_json)
```

`model_construct()` bypasses validation. It is not a faster parser for untrusted data and can create invalid model state. Use it only when data is already trusted and profiling justifies the added risk.

## 19. Common mistakes

| Mistake | Consequence | Better choice |
| --- | --- | --- |
| Assuming `str | None` is omittable | Unexpected required-field errors | Add a default when omission is allowed |
| Reusing one model everywhere | Mass assignment and field leakage | Separate command, response, domain, and ORM types |
| Database calls in validators | Hidden blocking, races, poor reuse | Perform I/O in a service and enforce constraints in storage |
| Blind coercion | Ambiguous booleans and numbers | Choose and test strictness per boundary |
| `model_dump()` as an update statement | Unauthorized or incorrectly mapped writes | Map an allow-list explicitly |
| Serializing lazy ORM relations | N+1 queries or async I/O failures | Load required data deliberately |
| Returning `model_dump_json()` normally | Double-encoded JSON | Return the model or an explicit JSON response |
| Dynamic error text as client protocol | Brittle consumers | Publish stable status and error codes |
| `model_construct()` on input | Invalid state bypasses checks | Validate untrusted data |
| Expensive computed field | Serialization causes latency spikes | Precompute in a service or query |

## Interview prompts

1. **What changed about optional fields in Pydantic v2?** A nullable annotation does not imply an omission default. `str | None` without a default is required but accepts null; add `= None` if omission is valid.
2. **Where should uniqueness validation live?** A service may pre-check for a friendly error, but the database constraint is authoritative under concurrency. Translate the constraint violation.
3. **Why separate response and ORM models?** They have different security, compatibility, loading, nullability, and lifetime concerns. Direct ORM serialization can expose fields and trigger unexpected I/O.
4. **When should you use a model validator?** For deterministic invariants involving multiple fields. Not for authorization, database lookups, or provider calls.
5. **How would you implement PATCH?** Use a dedicated update schema, preserve `model_fields_set`, dump with `exclude_unset`, authorize each change, map fields explicitly, and protect against lost updates.
6. **What is response validation buying you?** It catches server contract violations, supports OpenAPI, serializes declared types, and filters output. It has cost, so page large data and profile rather than abandoning the boundary casually.
7. **What does `from_attributes=True` risk?** Attribute access may trigger lazy loads, N+1 queries, or session/async errors. The output model is still explicit, but data loading must be deliberate.

## Sources

- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/)
- [Pydantic fields](https://docs.pydantic.dev/latest/concepts/fields/)
- [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/)
- [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/)
- [Pydantic serialization](https://docs.pydantic.dev/latest/concepts/serialization/)
- [Pydantic unions and discriminators](https://docs.pydantic.dev/latest/concepts/unions/)
- [Pydantic configuration](https://docs.pydantic.dev/latest/api/config/)
- [Pydantic errors](https://docs.pydantic.dev/latest/errors/errors/)
- [Pydantic performance guidance](https://docs.pydantic.dev/latest/concepts/performance/)
- [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [FastAPI response models](https://fastapi.tiangolo.com/tutorial/response-model/)
