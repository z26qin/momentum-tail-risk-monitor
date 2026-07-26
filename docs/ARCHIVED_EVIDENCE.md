# Archived point-in-time evidence

The active MVP supports two explicitly separate evidence tracks:

- `fixture`: committed, post-date curated examples used only to demonstrate
  gating and passage checks;
- `archived`: strict point-in-time retrieval from a supplied archive-content
  corpus.

The archived provider never reads or falls back to fixture data.

## Why inventory metadata is not enough

[GDELT 2.0 began on 2015-02-19](https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/).
Its [GKG 2.0](https://blog.gdeltproject.org/introducing-gkg-2-0-the-next-generation-of-the-gdelt-global-knowledge-graph/)
records discovery metadata and source URLs, while the
[official GKG index](https://data.gdeltproject.org/gkg/index.html) exposes the
historical inventory. The GKG does not preserve the original article body.
Consequently:

- GDELT inventory can prove discovery for 2015 onward;
- exact passage grounding additionally requires versioned page or WARC bytes
  captured by the assessment cutoff;
- the 2009 validation episode needs an official-release archive or another
  inventory that predates GDELT 2.0.

No current file in `data/corpus/` satisfies all three conditions, so archive
mode correctly reports `unavailable` until one is supplied.

## Corpus contract

`src/evidence/corpus_schema.py` requires
`schema_version = archived-evidence-v1` and these exact root fields:

```text
schema_version
corpus_version
selection_method
selection_query
archive_inventory
documents
```

Allowed selection methods are `gdelt_gkg_inventory` and
`official_release_archive`. `selection_query` is versioned as
`momentum-archive-query-v1` and records the unique terms, language, and
timezone-aware start/end timestamps.

Each document must provide:

```text
document_id, title, source, source_category, url, passage
publication_timestamp, discovery_timestamp, availability_timestamp
content_version_timestamp, availability_status
archive_source, archive_locator, acquisition_timestamp, content_sha256
```

`content_sha256` is recomputed from the title, URL, passage, and content-version
timestamp. `verified_archived_content` means the corpus builder can prove that
the exact passage version existed by `content_version_timestamp`.
`content_version_uncertain` is accepted into the corpus for audit but always
excluded from retrieval.

## Retrieval gate

For an elevated primary state, `archived_evidence_provider_v1`:

1. checks publication, discovery, availability, and content-version timestamps
   against the assessment timestamp;
2. applies the frozen 120-day lookback and mechanism-term query;
3. excludes disallowed sources and records every reason;
4. ranks deterministically, deduplicates by normalized URL, content hash, and
   normalized title, then keeps at most eight documents;
5. hashes the request and complete retrieval result.

No matched candidates yields `unavailable`. Matched candidates without a valid
classifier response yield `retrieved_unclassified`; both states emit zero
supporting, contradicting, or contextual items.

## Classifier response contract

The response schema is `mvp-evidence-classifier-v1`; the approved prompt is
`momentum-evidence-classifier-v2`. The exact root fields are:

```text
schema_version, as_of_date, timestamp_cutoff, retrieval_sha256
classifier_input_sha256, prompt_version, model_identifier
classifier_mode, temperature, items
```

The model identifier must be explicit, versioned, and contain a digit rather
than being `unknown` or `unspecified`.
Allowed modes are `deterministic_cached_response` and `live_model_response`.
The input hash binds the response to the immutable prompt text and the exact
bounded document payload; that payload contains no primary risk probability.
There must be exactly one item for every retrieved document, with these fields:

```text
document_id, classification, mechanism, extracted_passage
confidence, rationale, exclusion_reason
```

Relevant classifications are `supporting`, `contradicting`, and `contextual`.
Their mechanism must have matched retrieval and their extracted passage must be
an exact substring of the archived passage. `irrelevant` requires
`mechanism = other`, a null passage, and an exclusion reason.

The schema has no risk-probability field. A valid response can add context to
the PM brief but cannot change the DM/PIT primary state or probability.

## Run states

```bash
# Strict corpus absent: elevated dates return unavailable.
uv run python -m src.pipeline \
  --as-of-date 2020-03-24 \
  --evidence-provider archived

# Strict corpus supplied: retrieved_unclassified unless response is supplied.
uv run python -m src.pipeline \
  --as-of-date 2020-03-24 \
  --evidence-provider archived \
  --archived-corpus /path/to/corpus.json

# Directional evidence only after every classifier gate passes.
uv run python -m src.pipeline \
  --as-of-date 2020-03-24 \
  --evidence-provider archived \
  --archived-corpus /path/to/corpus.json \
  --classifier-response /path/to/response.json
```

Quiet primary states skip retrieval regardless of configured files.
