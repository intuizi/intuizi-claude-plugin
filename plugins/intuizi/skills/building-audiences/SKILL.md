---
name: building-audiences
description: Use when working with Intuizi audiences, cohorts or activations - building or sizing an audience, growing one with a lookalike, previewing a frequency range, or delivering an audience to a destination. Covers the order the Intuizi tools are meant to be called in and the points where the user has to confirm.
---

# Building and activating Intuizi audiences

Intuizi work is asynchronous and metered. A build consumes the organization's data-scan
allowance, and in an organization billed in credits it costs credits. An activation delivers real
data to a partner destination. So the order of operations and the confirmation points matter.

## The sequence

1. **Resolve names to ids with `lookup_reference`.** Never guess an id. Brands, POI categories,
   apps, CTV channels, merchants and countries all come from reference catalogs. Call
   `tools/list` if unsure which dataset and catalog pair to use.
2. **Size before building with `estimate_audience_size`.** It takes the same body as
   `create_audience` and creates nothing. Read its response before you poll: it may already hold
   the finished estimate (`data[0].status` `completed`, `data[0].estimate.method` `sketch`, and
   `data[0].estimate.as_of` for when its data was read), and then there is nothing to poll. Call
   `get_audience_estimate` with `data[0].id` only while the status is `pending` or `processing`,
   and repeat until it is `completed`, `blocked` or `failed`. If it still answers `pending` after
   about 8 calls (about 2 minutes), stop, tell the user the estimate is still running, give them
   `data[0].id` and read it again later. A `blocked` result explains why, often a date window
   outside coverage.
3. **Quote the price when the organization is billed in credits.** The tools list then includes
   `quote_audience`. Call it with the exact body you will send to `create_audience`: it validates
   the same way, creates nothing and is free. `data[0].credits` is the price and
   `data[0].available_after` the credits left after the run. `quote_lookalike_audience` does the
   same for `create_lookalike_audience`. Without these tools the organization is not billed in
   credits, so skip this step.
4. **Confirm, then build.** Report the estimate, and the price when there is one, and ask the user
   before calling `create_audience`. Then poll `get_audience` until `data[0].status.id` is `104`
   (Completed), the only terminal success state.
5. **Preview before activating.** `preview_activation` returns the exact count a frequency range
   keeps, plus a `filter_hash`. Pass that hash with `freq_limit: true` to `create_activation` to
   activate exactly the previewed range.
6. **Confirm, then activate.** Ask the user before calling `create_activation`. Delivered data
   lands at the destination configured on the endpoint connection; the API returns no delivery URI.

## Things that trip agents up

- **Responses wrap data in a one-element array.** Read `data[0]`, not `data`.
- **Only some estimates answer at once.** A single-dataset POI estimate at country or state level
  usually comes back `completed` in the `estimate_audience_size` response itself: a fast answer.
  It does not count toward the build budget and is still metered on the bytes it reads. For a POI
  dataset a fast answer equals a full estimate run on the same data, and a full estimate run later
  can differ a little as new data arrives. Any other estimate, and the few POI estimates that fall
  back, is answered by a worker and can take minutes, for example AND, OR, NOTIN, and city, DMA or
  ZIP requests.
- **The dataset named "Transactions" in the console is `affinity-transactions`** in reference
  lookups and `AffinityTransactions` as an audience type. The bare `Transactions` key is retired
  and rejected.
- **A lookalike seed must be completed, non-lookalike and large enough** (1,000 devices by
  default). `cancel_lookalike` stops a run that is still going.
- **Check `get_usage` before a large build** if the organization is near its data-scan limit; a
  build is refused once the limit is reached. In an organization billed in credits, its `credits`
  block also shows the credits left.
- **A failed, cancelled or empty run gets its credits back.** `credits_charged` on `get_audience`
  shows what a run cost after any refund.
- **Rate limits are 120 reads and 30 writes per minute.** On HTTP 429, respect `Retry-After`.
- **Deletes are permanent.** `delete_audience`, `delete_activation`, `delete_cohort` and
  `delete_poi_submission` are annotated destructive for a reason; always confirm first.

## Reading the docs

The server publishes its own documentation as MCP resources. Call `resources/list`, then read the
response-envelope, async-model, errors and idempotency pages before improvising a request shape.
