# Procurement Notice Deduplication

## Section A: Similarity and Reduced Form

The duplicate signal should be computed from normalized content tokens rather than raw notice text. Portal boilerplate, legal preambles, dates, reference numbers, and aggregator-specific text create misleading overlap between unrelated notices.

The recommended similarity pipeline is:

1. Lowercase and normalize title and body text.
2. Remove punctuation, numbers, boilerplate, and generic legal terms.
3. Retain meaningful procurement content tokens.
4. Compute token-set Jaccard similarity.
5. Apply a conservative threshold because false merges are more costly than missed duplicate cards.

The labelled corpus contains 900 pairs: 279 same pairs and 621 different pairs. The measured filtered-token similarity was:

- Same-pair mean: `0.7168`
- Different-pair mean: `0.5409`

The threshold scan showed:

- Threshold `0.30`: precision `0.3218`, recall `0.9964`
- Threshold `0.35`: precision `0.3342`, recall `0.9606`

A threshold in the `0.30`-`0.35` range is a practical starting point. It preserves very high recall while making the false-merge tradeoff explicit and tunable.

### Reduced representation

Store a compact content-token signature for candidate generation and comparison instead of repeatedly processing the full notice body. The measured mean absolute error against the full representation was:

| Signature size | Mean absolute error |
|---:|---:|
| 16 tokens | 0.1919 |
| 32 tokens | 0.1836 |
| 64 tokens | 0.1464 |
| 128 tokens | 0.1395 |
| 256 tokens | 0.0205 |

The 256-token signature is the most defensible compact representation for this corpus because it provides substantially better fidelity while remaining much smaller than the full text.

## Section B: Schema and Access Method

Use a persistent SQLite-backed inverted index rather than comparing every notice with every other notice.

Recommended logical tables:

- `notices`: notice identity, portal, URL, title, body, normalized text, reduced signature, and timestamps.
- `notice_tokens`: `notice_id`, token, and term frequency.
- `notice_clusters`: deterministic cluster id and canonical notice id.
- `candidate_pairs`: candidate ids, similarity, decision, and decision timestamp.

The nightly access path is:

1. Tokenize each notice and update the inverted index.
2. Retrieve candidates from token postings.
3. Intersect or rank postings to keep the candidate set bounded.
4. Compute the more expensive similarity only for those candidates.
5. Merge pairs that pass the configured threshold.
6. Assign a deterministic canonical cluster id.

This changes retrieval from an O(N²) all-pairs comparison into a postings-based candidate search, which is suitable for a 20-minute nightly budget.

Measured retrieval results were:

- Mean candidate count: `50`
- Candidate-count p95: `50`
- Same-pair survival through retrieval: `0.2366`
- Different-pair survival through retrieval: `0.0048`

The low different-pair survival rate is the important safety result: most unrelated pairs are excluded before expensive scoring.

### Hotspot mitigation and stable bookmarks

The corpus is unevenly distributed:

- Nodal portal notice share: `0.38875`
- Nodal token-load share: `0.4537`

Process notices in portal-scoped batches and maintain postings deterministically. High-volume or nodal portals should be monitored separately so their repeated boilerplate does not dominate candidate generation.

For stable bookmarks, choose the cluster canonical notice deterministically, for example the minimum notice id in each connected component. Persist that canonical id and reuse it across reruns. This prevents cluster identifiers from changing merely because ingestion order changes.

## Conclusion

The evidence supports a pipeline based on boilerplate removal, content-token Jaccard similarity, compact signatures, a persistent inverted index, conservative thresholding, and deterministic canonical cluster ids. This design addresses both the false-merge risk and the retrieval-cost constraints of the 12,000-notice corpus.
