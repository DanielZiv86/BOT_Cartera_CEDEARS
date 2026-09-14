from __future__ import annotations

import argparse,json
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

import yaml


def _load_policy(path:str)->dict[str,Any]:
    raw=yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    buckets=raw.get('buckets',{}) or {}
    code_to_bucket:dict[str,str]={}
    for bucket,spec in buckets.items():
        for code in (spec or {}).get('blocker_codes',[]) or []:
            code_to_bucket[str(code)]=bucket
    return {'code_to_bucket':code_to_bucket,'buckets':buckets,'default_bucket':str(raw.get('default_bucket') or 'uncatalogued_blocker_needs_triage_update'),'methodology_version':str(raw.get('methodology_version') or 'TRIAGE-UNKNOWN')}


def _diagnostic_context(row:dict[str,Any],buckets:dict[str,Any],matched_buckets:list[str])->dict[str,Any]:
    fields:set[str]=set()
    for bucket in matched_buckets:
        fields.update((buckets.get(bucket) or {}).get('diagnostic_fields',[]) or [])
    return {f:row.get(f) for f in sorted(fields) if f in row}


def triage_scenario_review(rows:list[dict[str,Any]],policy:dict[str,Any])->tuple[list[dict[str,Any]],dict[str,int]]:
    code_to_bucket=policy['code_to_bucket']; buckets=policy['buckets']; default_bucket=policy['default_bucket']
    triaged:list[dict[str,Any]]=[]; summary:dict[str,int]={}
    for row in rows:
        if bool(row.get('scenario_validated',False)):continue
        raw_blockers=row.get('scenario_review_blockers'); blockers=raw_blockers if isinstance(raw_blockers,list) else []
        if not blockers:blockers=['SCENARIO_VALIDATION_FAILED_NO_BLOCKER_RECORDED']
        matched=sorted({code_to_bucket.get(b,default_bucket) for b in blockers})
        for bucket in matched:summary[bucket]=summary.get(bucket,0)+1
        triaged.append({'cedear_ticker':row.get('cedear_ticker'),'blockers':blockers,'buckets':matched,'diagnostic_context':_diagnostic_context(row,buckets,matched)})
    return triaged,summary


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--scenario-review',required=True); p.add_argument('--policy',default='config/g4_blocker_triage_policy.yml'); p.add_argument('--output-dir',required=True)
    a=p.parse_args()
    rows=json.loads(Path(a.scenario_review).read_text(encoding='utf-8')); policy=_load_policy(a.policy)
    triaged,summary=triage_scenario_review(rows,policy)
    out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    (out/'g4_blocker_triage.json').write_text(json.dumps(triaged,indent=2,ensure_ascii=False),encoding='utf-8')
    manifest={'layer':'G4 Blocker Triage','created_at':datetime.now(timezone.utc).isoformat(),'methodology_version':policy['methodology_version'],'policy_file':a.policy,'scenario_review_count':len(rows),'triaged_count':len(triaged),'bucket_summary':summary}
    (out/'g4_blocker_triage_summary.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(manifest,indent=2)); return 0


if __name__=='__main__':raise SystemExit(main())
