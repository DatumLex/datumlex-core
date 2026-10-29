"""Extract archived PDFs and import bibliography offline; never fetch publishers."""
import json
from collect_doctrine import ROOT, import_manifest, extract_entry
from etl_runtime import atomic_json,file_lock

def main():
    path=ROOT/'manifest.json';manifest=json.loads(path.read_text(encoding='utf8'))
    converted=rejected=0
    for key,entry in list(manifest.get('pending',{}).items()):
        try:
            manifest['documents'][key]=extract_entry(entry);converted+=1
        except (OSError,ValueError) as exc:
            if isinstance(exc,OSError) or 'hash mismatch' in str(exc):raise
            manifest.setdefault('rejected',{})[key]={**entry,'text_extraction_status':'needs_alternate_extraction','error_type':type(exc).__name__}
            rejected+=1
        del manifest['pending'][key]
        atomic_json(path,manifest)
    import_manifest(manifest)
    result={'imported_or_verified':len(manifest['documents']),'new_texts':converted,
            'needs_alternate_extraction':rejected,'network_requests':0}
    atomic_json(ROOT/'import-last-run.json',result)
    print(json.dumps(result))

if __name__=='__main__':
    with file_lock(ROOT/'source.lock'):
        main()
