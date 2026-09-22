---
name: building-audiences
description: Use when working with Intuizi audiences, cohorts or activations - building or sizing an audience, growing one with a lookalike, previewing a frequency range, or delivering an audience to a destination. Covers the order the Intuizi tools are meant to be called in and the points where the user has to confirm.
---

# Building and activating Intuizi audiences

Intuizi work is asynchronous and metered. A build consumes the organization's data-scan
allowance, and an activation delivers real data to a partner destination, so the order of
operations and the confirmation points matter.

## The sequence

1. **Resolve names to ids with `lookup_reference`.** Never guess an id. Brands, POI categories,
   apps, CTV channels, merchants and countries all come from reference catalogs. Call
   `tools/list` if unsure which dataset and catalog pair to use.
2. **Size before building with `estimate_audience_size`.** It takes the same body as
   `create_audience`, runs the same pipeline and creates nothing. Poll
   `get_audience_estimate` until the status is `completed`, `blocked` or `failed`. A `blocked`
   result explains why, often a date window outside coverage.
3. **Confirm, then build.** Report the estimate and ask the user before calling
   `create_audience`. Then poll `get_audience` until `data[0].status.id` is `104` (Completed),
   the only terminal success state.
4. **Preview before activating.** `preview_activation` returns the exact count a frequency range
   keeps, plus a `filter_hash`. Pass that hash with `freq_limit: true` to `create_activation` to
   activate exactly the previewed range.
5. **Confirm, then activate.** Ask the user before calling `create_activation`. Delivered data
   lands at the destination configured on the endpoint connection; the API returns no delivery URI.

## Things that trip agents up

- **Responses wrap data in a one-element array.** Read `data[0]`, not `data`.
- **The dataset named "Transactions" in the console is `affinity-transactions`** in reference
  lookups and `AffinityTransactions` as an audience type. The bare `Transactions` key is retired
  and rejected.
- **A lookalike seed must be completed, non-lookalike and large enough** (1,000 devices by
  default). `cancel_lookalike` stops a run that is still going.
- **Check `get_usage` before a large build** if the organization is near its data-scan limit; a
  build is refused once the limit is reached.
- **Rate limits are 120 reads and 30 writes per minute.** On HTTP 429, respect `Retry-After`.
- **Deletes are permanent.** `delete_audience`, `delete_activation`, `delete_cohort` and
  `delete_poi_submission` are annotated destructive for a reason; always confirm first.

## Reading the docs

The server publishes its own documentation as MCP resources. Call `resources/list`, then read the
response-envelope, async-model, errors and idempotency pages before improvising a request shape.
