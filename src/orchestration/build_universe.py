from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.universe.loader import eligible_universe_frame, load_universe_json, validate_universe
from src.universe.symbol_map import build_symbol_map, load_alias_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical CEDEAR universe and symbol map")
    parser.add_argument("--input", required=True, help="Path to CEDEAR Universe Master JSON")
    parser.add_argument(
        "--aliases",
        default="config/symbol_aliases.yml",
        help="Provider symbol alias configuration",
    )
    parser.add_argument(
        "--output-dir",
        default="data/canonical",
        help="Canonical output directory",
    )
    args = parser.parse_args()

    payload = load_universe_json(args.input)
    validation = validate_universe(payload)
    if not validation.is_valid or validation.errors:
        raise SystemExit("Universe validation failed:\n- " + "\n- ".join(validation.errors))

    eligible = eligible_universe_frame(payload)
    aliases = load_alias_config(args.aliases)
    symbol_map = build_symbol_map(eligible, aliases)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    universe_parquet = output_dir / "cedear_universe_master.parquet"
    universe_json = output_dir / "cedear_universe_master.json"
    symbol_parquet = output_dir / "security_symbol_map.parquet"
    symbol_json = output_dir / "security_symbol_map.json"
    manifest_path = output_dir / "universe_manifest.json"

    eligible.to_parquet(universe_parquet, index=False)
    eligible.to_json(universe_json, orient="records", indent=2, force_ascii=False)
    symbol_map.to_parquet(symbol_parquet, index=False)
    symbol_map.to_json(symbol_json, orient="records", indent=2, force_ascii=False)

    manifest = {
        "source_version": payload.get("version") or payload.get("Universe_Master_Version"),
        "declared_universe_count": payload.get("Universe_Count"),
        "declared_eligible_count": payload.get("Eligible_Count"),
        "canonical_eligible_count": int(len(eligible)),
        "symbol_map_count": int(len(symbol_map)),
        "mapping_version": aliases.get("mapping_version", "1.0"),
        "mandate_exceptions": eligible.loc[
            eligible["mandate_exception"] == True, "cedear_ticker"
        ].tolist(),
        "outputs": [
            str(universe_parquet),
            str(universe_json),
            str(symbol_parquet),
            str(symbol_json),
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
