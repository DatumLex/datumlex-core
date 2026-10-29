"""Discover and preserve original doctrine artifacts without database writes."""
import argparse
import json
from discover_ril import discover
from collect_doctrine import collect
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--limit',type=int,default=50)
    args=parser.parse_args();urls=discover(limit=args.limit)
    result=collect(import_db=False,sources=[('Senado',url) for url in urls],extract_text=False)
    print(json.dumps(result,ensure_ascii=False));raise SystemExit(2 if result['failed_this_run'] else 0)
