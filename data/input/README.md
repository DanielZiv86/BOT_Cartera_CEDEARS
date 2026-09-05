# Universe source input

Place the validated bootstrap source here as:

`data/input/CEDEAR_Universe_Master_v2.json`

Expected contract:

- top-level `rows` list;
- `Universe_Count` and `Eligible_Count` metadata when available;
- row-level fields required by `src/universe/schema.py`;
- IWDA preserved with `mandate_exception=true`.

The build pipeline will NOT scrape or reconstruct the universe silently. It validates the supplied canonical source, filters eligible rows, then writes canonical JSON/Parquet outputs and the provider symbol map.

This directory is intentionally separated from `data/canonical/`: input lineage and produced canonical datasets must remain distinguishable.
