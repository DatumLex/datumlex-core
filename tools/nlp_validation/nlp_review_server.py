"""Loopback-only blind review UI. No external calls, DB access or model predictions."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlparse

import nlp_validation as validation


def handler(directory, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, value, status=200):
            raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == '/':
                raw = (Path(__file__).with_name('nlp_review.html')).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Frame-Options', 'DENY')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                self.wfile.write(raw)
                return
            manifest, _ = validation.load_dataset(directory)
            if parsed.path == '/api/documents':
                self.reply({'token': token, 'dataset_id': directory.name,
                    'labels': validation.LABELS, 'adoptions': validation.ADOPTIONS,
                    'documents': [{k: d[k] for k in ('id', 'court', 'date', 'period_field', 'length')}
                                  for d in manifest['documents']]})
                return
            query = parse_qs(parsed.query)
            document = next((d for d in manifest['documents'] if d['id'] == query.get('id', [None])[0]), None)
            if document is None:
                self.reply({'error': 'document_not_found'}, 404)
                return
            reviewer = query.get('reviewer', [''])[0].strip().casefold()
            if parsed.path == '/api/document':
                path = validation.review_path(directory, document['id'], reviewer)
                saved = validation.read(path) if reviewer and path.exists() else None
                self.reply({'document': {k: document[k] for k in ('id', 'court', 'date', 'period_field', 'text', 'text_sha256')},
                            'saved': saved})
                return
            if parsed.path == '/api/adjudication':
                rows = validation.reviews_for(directory, document)
                identities = {r['reviewer'] for r in rows}
                if len(identities) < 2 or reviewer in identities or not reviewer:
                    self.reply({'error': 'Exige duas revisões completas e um terceiro identificador para decidir.'}, 400)
                    return
                self.reply({'reviews': rows})
                return
            self.reply({'error': 'not_found'}, 404)

        def do_POST(self):
            if self.headers.get('X-Review-Token') != token:
                self.reply({'error': 'invalid_token'}, 403)
                return
            if self.path not in ('/api/review', '/api/adjudication', '/api/diagnostic'):
                self.reply({'error': 'not_found'}, 404)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2_000_000:
                    raise ValueError('invalid_body_size')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('object_required')
                if self.path == '/api/diagnostic':
                    reviewer = payload.get('reviewer')
                    if not isinstance(reviewer, str) or not reviewer.strip():
                        raise ValueError('reviewer_required')
                    result = validation.evaluate(directory, single_reviewer=reviewer)
                    self.reply(result['single_reviewer_diagnostic'])
                    return
                validation.store_review(directory, payload, self.path == '/api/adjudication')
                self.reply({'saved': True})
            except (ValueError, KeyError, TypeError) as exc:
                self.reply({'error': str(exc)}, 400)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    directory = args.directory or Path(validation.read(validation.BASE / 'nlp-validation/current.json')['directory'])
    validation.load_dataset(directory)
    server = HTTPServer(('127.0.0.1', args.port), handler(directory, secrets.token_urlsafe(32)))
    print(f'Revisão local: http://127.0.0.1:{args.port}/', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
