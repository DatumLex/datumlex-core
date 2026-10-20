"""Build a portable source installer using an allowlist (no local data or secrets)."""

import argparse
from pathlib import Path
import zipfile


def build(output: Path):
    root = Path(__file__).resolve().parents[2]
    files = {root / '.dockerignore'}
    for relative in ('backend/config', 'backend/src', 'frontend/src', 'frontend/public', 'deploy/local-server'):
        for path in (root / relative).rglob('*'):
            if not path.is_file():
                continue
            if any(part.startswith('.') or part in {'__pycache__', 'backups', 'clientes'} for part in path.relative_to(root).parts):
                continue
            if path.suffix in {'.pyc', '.dump', '.sqlite3', '.zip', '.crt', '.key'} or path.name in {'ACESSO-INICIAL.txt', 'server.json'}:
                continue
            files.add(path)
    for relative in ('backend/manage.py', 'backend/requirements.txt', 'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html', 'frontend/vite.config.js'):
        files.add(root / relative)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, 'DatumLex-Servidor/' + path.relative_to(root).as_posix())
        archive.writestr('DatumLex-Servidor/DISTRIBUTION.txt', 'DatumLex local server distribution. No data or credentials included.\n')
        archive.writestr('DatumLex-Servidor/INSTALAR.cmd', '@echo off\r\ncall "%~dp0deploy\\local-server\\Instalar.cmd"\r\n')
        archive.write(root / 'deploy/local-server/LEIA-ME.md', 'DatumLex-Servidor/LEIA-ME.md')
    print(output.resolve())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)
