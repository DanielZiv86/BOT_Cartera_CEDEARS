from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

from src.universe.loader import eligible_universe_frame, load_universe_json, validate_universe
from src.universe.schema import validate_row
from src.universe.symbol_map import build_symbol_map, load_alias_config


def load_mandate_exclusions(path: str | Path | None) -> dict:
    if not path:
        return {"tickers": []}
    file_path = Path(path)
    if not file_path.exists():
        return {"tickers": []}
    with file_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, dict):
        raise ValueError("Mandate exclusions config must be a mapping")
    tickers = payload.get("tickers", [])
    if not isinstance(tickers, list):
        raise ValueError("Mandate exclusions 'tickers' must be a list")
    payload["tickers"] = [str(t).strip().upper() for t in tickers if str(t).strip()]
    return payload


def load_universe_inclusions(path: str | Path | None) -> dict:
    if not path:
        return {"rows": []}
    file_path = Path(path)
    if not file_path.exists():
        return {"rows": []}
    with file_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, dict):
        raise ValueError("Universe inclusions config must be a mapping")
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError("Universe inclusions 'rows' must be a list")
    for idx, row in enumerate(rows):
        errors = validate_row(row, idx)
        if errors:
            raise ValueError("Invalid universe inclusion row: " + "; ".join(errors))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical CEDEAR universe and symbol map")
    parser.add_argument("--input", required=True, help="Path to CEDEAR Universe Master JSON")
    parser.add_argument("--aliases", default="config/symbol_aliases.yml")
    parser.add_argument("--exclusions", default="config/mandate_exclusions.yml")
    parser.add_argument("--inclusions", default="config/universe_inclusions.yml")
    parser.add_argument("--output-dir", default="data/canonical")
    args = parser.parse_args()

    payload = load_universe_json(args.input)
    validation = validate_universe(payload)
    if not validation.is_valid or validation.errors:
        raise SystemExit("Universe validation failed:\n- " + "\n- ".join(validation.errors))

    source_eligible = eligible_universe_frame(payload)
    exclusion_cfg = load_mandate_exclusions(args.exclusions)
    inclusion_cfg = load_universe_inclusions(args.inclusions)
    exclusion_set = set(exclusion_cfg.get("tickers", []))

    source_tickers = set(source_eligible["cedear_ticker"].astype(str).str.upper())
    unknown_exclusions = sorted(exclusion_set - source_tickers)
    if unknown_exclusions:
        raise SystemExit(
            "Mandate exclusions contain tickers not present in source eligible universe: "
            + ", ".join(unknown_exclusions)
        )

    canonical = source_eligible.copy()
    canonical["user_mandate_excluded"] = canonical["cedear_ticker"].astype(str).str.upper().isin(exclusion_set)
    canonical["user_mandate_exclusion_reason"] = canonical["user_mandate_excluded"].map(
        lambda value: exclusion_cfg.get("reason_code", "USER_EXCLUDED_FROM_ANALYSIS") if value else None
    )
    canonical["universe_override_inclusion"] = False
    canonical["universe_override_reason"] = None

    included_tickers: list[str] = []
    for row in inclusion_cfg.get("rows", []):
        ticker = str(row["cedear_ticker"]).upper()
        if ticker in exclusion_set:
            raise SystemExit(f"Ticker {ticker} cannot be both excluded and force-included")
        if ticker in set(canonical["cedear_ticker"].astype(str).str.upper()):
            continue
        record = dict(row)
        record["user_mandate_excluded"] = False
        record["user_mandate_exclusion_reason"] = None
        record["universe_override_inclusion"] = True
        record["universe_override_reason"] = inclusion_cfg.get("reason_code", "EXPLICIT_UNIVERSE_INCLUSION")
        canonical = pd.concat([canonical, pd.DataFrame([record])], ignore_index=True)
        included_tickers.append(ticker)

    eligible = canonical.loc[~canonical["user_mandate_excluded"]].copy()
    eligible = eligible.sort_values("cedear_ticker").reset_index(drop=True)
    aliases = load_alias_config(args.aliases)
    symbol_map = build_symbol_map(eligible, aliases)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    universe_parquet = output_dir / "cedear_universe_master.parquet"
    universe_json = output_dir / "cedear_universe_master.json"
    excluded_json = output_dir / "cedear_mandate_exclusions.json"
    included_json = output_dir / "cedear_universe_inclusions.json"
    symbol_parquet = output_dir / "security_symbol_map.parquet"
    symbol_json = output_dir / "security_symbol_map.json"
    manifest_path = output_dir / "universe_manifest.json"

    eligible.to_parquet(universe_parquet, index=False)
    eligible.to_json(universe_json, orient="records", indent=2, force_ascii=False)
    canonical.loc[canonical["user_mandate_excluded"]].to_json(excluded_json, orient="records", indent=2, force_ascii=False)
    canonical.loc[canonical["universe_override_inclusion"] == True].to_json(included_json, orient="records", indent=2, force_ascii=False)
    symbol_map.to_parquet(symbol_parquet, index=False)
    symbol_map.to_json(symbol_json, orient="records", indent=2, force_ascii=False)

    excluded_tickers = sorted(exclusion_set)
    manifest = {
        "source_version": payload.get("version") or payload.get("Universe_Master_Version"),
        "declared_universe_count": payload.get("Universe_Count"),
        "source_declared_eligible_count": payload.get("Eligible_Count"),
        "user_mandate_exclusion_version": exclusion_cfg.get("version"),
        "user_mandate_excluded_count": len(excluded_tickers),
        "user_mandate_excluded_tickers": excluded_tickers,
        "universe_inclusion_version": inclusion_cfg.get("version"),
        "universe_override_included_count": len(included_tickers),
        "universe_override_included_tickers": sorted(included_tickers),
        "canonical_eligible_count": int(len(eligible)),
        "symbol_map_count": int(len(symbol_map)),
        "mapping_version": aliases.get("mapping_version", "1.0"),
        "mandate_exceptions": eligible.loc[eligible["mandate_exception"] == True, "cedear_ticker"].tolist(),
        "outputs": [str(universe_parquet), str(universe_json), str(excluded_json), str(included_json), str(symbol_parquet), str(symbol_json)],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
