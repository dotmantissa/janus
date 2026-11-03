# Deterministic temporal semantics and limits

## Intervals

UTC is the only normalization timezone. Bounds are integer Unix seconds. Every interval uses `[lower, upper)`: lower inclusive, upper exclusive. `null` means an unknown or unbounded endpoint. An explicit offset is mandatory for timestamp strings. Gregorian date-only values are allowed only when the policy sets `date_only_utc: true`, in which case a date denotes UTC midnight.

| Qualifier | Interval |
| --- | --- |
| EXACT timestamp `t` | `[t, t + 1 second)` |
| EXACT date `d` | `[UTC midnight d, next UTC midnight)` |
| RANGE start and end | `[start, end)` |
| FROM start | `[start, null)` |
| BEFORE boundary | `[null, boundary)` |
| AFTER timestamp or date | Begins after that entire timestamp second or date day |
| UNKNOWN | `[null, null)` with no affirmative role coverage |

Intersection selects the greatest known lower bound and least known upper bound. If both are known and lower is greater than or equal to upper, the intersection is empty. Materially incompatible assertions for the same occurrence or effective role produce UNKNOWN. A single request must describe one proposition whose assertions share the relevant temporal interval. Independent events with separate intervals require separate requests; Janus does not combine them into a false joint interval.

Supported dates span `1970-01-01T00:00:00Z` through `9999-12-31T23:59:59Z`. Offsets are at most 14 hours, with minute values below 60. Leap seconds, non-Gregorian calendars, fractional source timestamps and timezone names are unsupported. A model must select a supported verbatim date substring from a verified witness. It cannot fabricate a reformatted date. An unrepresentable assertion must be UNKNOWN; malformed output fails the assessment and remains subject to the reserved-attempt recovery limit.

`first_publication_upper` is an inclusive availability bound from signed observation support. Its interval representation uses an exclusive upper endpoint of `first_publication_upper + 1`. A source's claimed publication heading may appear in the semantic decision vector, but never changes this supported availability bound. When multiple controlling sources are required for a proposition, the certificate conservatively uses the latest of their observation upper bounds.

## Ceilings

| Item | Enforced ceiling |
| --- | --- |
| Committed records per assessment | 4 |
| Temporal assertions per request | 6 |
| Bytes per source | 48 KiB, exact committed length |
| Decoded UTF-8 bytes per source | 48 KiB |
| Complete source packet | 64 KiB total |
| Full serialized model input | 90,000 UTF-8 bytes |
| Conservative input-token upper bound | 90,000, using UTF-8 bytes as a tokenizer-independent bound |
| Model calls | 1 per participant per assessment |
| Parsed model output | 12,000 UTF-8 bytes |
| Spans per source | 24 |
| Bytes per committed span text | 2,048 |
| Source manifest and request JSON | 20,000 bytes each |
| Proposition | 2,048 UTF-8 bytes |
| Policy rules | 8, each instruction at most 1,000 characters |
| Authorized assessment parties | 4 |
| Application assessment reservations per revision | 3 |
| Delivery broadcasts per operation | 3 |
| Source-confirmation broadcasts per revision | 3 |
| History page | 50 IDs |
| Each bounded registry/history | Constructor capacity, at most 10,000 |
| Policy and source revision | Unsigned 32-bit, checked before storage |
| Request generation | Unsigned 64-bit, checked before storage |
| Notice period | 0 through 315,360,000 integer seconds |

Limits are applied before substantive model evaluation. Complete packet inspection is mandatory. If any committed record is missing, changed, unavailable or fails span verification, no partial material conclusion is inferred. Oversized complete tasks fail without truncation. The runtime web API does not expose a response-size option or model output-token option. The contract prechecks committed lengths and bounds retrieved bytes and decoded text before model use; output size is checked after the runtime returns it. Host download and generation limits remain network-managed. The conservative input token bound avoids assuming an unavailable tokenizer.

No contract loop manufactures validator rotation or finality. Reserved attempts survive separately submitted failed assessments. An unavailable attempt leaves the request OPEN while reservations remain; the third unavailable assessment becomes UNKNOWN with RETRY_EXHAUSTED. Malformed output fails validation without applying state; after three reserved attempts the owner or parties can call `expire_record` to expose unresolved recovery. At the deadline, that method produces UNKNOWN with TIMEOUT. Terminal requests cannot be recertified in place.

The published verification report gives measured source sizes and observed Studio execution times. An enforced ceiling is not a claim that the Studio model provider will successfully process every input at that ceiling. Outages and resource failures remain unavailable or fail validation, and the retry/recovery protocol preserves that distinction.
