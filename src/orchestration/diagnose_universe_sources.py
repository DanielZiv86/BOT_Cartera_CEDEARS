from __future__ import annotations
import io,json,re
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
import requests
from src.universe.official_sources import COMAFI_PROGRAM_CATALOG_URL,COMAFI_PROGRAMS_URL,COMAFI_SHARES_DETAIL_URL,BYMA_CEDEARS_URL,_norm

URLS={"comafi_catalog":COMAFI_PROGRAM_CATALOG_URL,"comafi_programs":COMAFI_PROGRAMS_URL,"comafi_shares_detail":COMAFI_SHARES_DETAIL_URL,"byma_product":BYMA_CEDEARS_URL}

def inspect(name,url):
    row={"source":name,"requested_url":url}
    try:
        r=requests.get(url,timeout=30,headers={"User-Agent":"CEDEAR-MVP/1.0"},allow_redirects=True)
        row.update(status_code=r.status_code,final_url=r.url,bytes=len(r.content),content_type=r.headers.get("content-type"),redirects=[x.url for x in r.history])
        r.raise_for_status()
        try: tables=pd.read_html(io.StringIO(r.text))
        except Exception: tables=[]
        row["table_count"]=len(tables); row["tables"]=[{"index":i,"rows":len(t),"columns":[_norm(c) for c in t.columns]} for i,t in enumerate(tables)]
        row["contains_cedear"]=bool(re.search("cedear",r.text,re.I))
    except Exception as e: row["error"]=f"{type(e).__name__}: {e}"
    return row

def main():
    out=Path("data/canonical"); out.mkdir(parents=True,exist_ok=True)
    payload={"created_at":datetime.now(timezone.utc).isoformat(),"sources":[inspect(k,v) for k,v in URLS.items()]}
    (out/"universe_source_diagnostics.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(payload,indent=2,ensure_ascii=False))
if __name__=="__main__": main()
