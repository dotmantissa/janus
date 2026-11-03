"""Verify public transport confinement against actual publisher HTTP responses."""
import argparse
import hashlib
import json
import urllib.request
import urllib.error
from studio import ROOT, atomic


def fetch(url, value):
    request = urllib.request.Request(url, json.dumps(value).encode(), {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as response:
        return response.code, dict(response.headers), response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('--deployment-id', required=True)
    parser.add_argument('--deployment-url', required=True)
    args = parser.parse_args()
    results = []
    for filename, meta, prefix in [
        ('node-schedule.json', 'node-source.json', 'https://raw.githubusercontent.com/nodejs/Release/'),
        ('node-release.md', 'node-release-source.json', 'https://raw.githubusercontent.com/nodejs/nodejs.org/'),
    ]:
        source = json.loads((ROOT/'evidence'/meta).read_text())['url']
        raw = (ROOT/'evidence'/filename).read_bytes()
        record = {'url': source, 'url_prefix': prefix, 'raw_sha256': hashlib.sha256(raw).hexdigest(), 'byte_length': len(raw)}
        status, headers, body = fetch(args.url, record)
        assert status == 200 and body == raw, (status, body[:200])
        lower = {k.lower(): v for k, v in headers.items()}
        assert lower['x-janus-source-url'] == source and lower['x-janus-redirect-policy'] == 'REJECT'
        results.append({'source_url': source, 'status': status, 'raw_sha256': record['raw_sha256'], 'byte_length': len(body), 'binding_headers_verified': True})
    dummy = {'url': 'https://github.com/twitter/bootstrap', 'url_prefix': 'https://github.com/twitter/', 'raw_sha256': '1'*64, 'byte_length': 1}
    status, headers, body = fetch(args.url, dummy)
    assert status == 409 and body == b'REDIRECT_REJECTED', (status, body[:200])
    results.append({'source_url': dummy['url'], 'status': status, 'reason': body.decode()})
    for url in ['https://raw.githubusercontent.com/nodejs/Release/..', 'https://raw.githubusercontent.com/nodejs/Release/.', 'https://raw.githubusercontent.com/nodejs/Release-evil/record']:
        record = {**dummy, 'url': url, 'url_prefix': 'https://raw.githubusercontent.com/nodejs/Release/'}
        status, _, body = fetch(args.url, record)
        assert status == 409 and body == b'SOURCE_CONFINEMENT'
        results.append({'source_url': url, 'status': status, 'reason': body.decode()})
    files = ['gateway/core.mjs', 'gateway/api/fetch.mjs', 'gateway/package.json', 'gateway/vercel.json']
    atomic(ROOT/'evidence/source-transport.json', {
        'url': args.url, 'deployment_id': args.deployment_id,
        'deployment_url': args.deployment_url,
        'redirect_policy': 'REJECT', 'trust': 'DEPLOYMENT_OWNER_CONTROLLED_TRANSPORT',
        'allowed_hosts': ['raw.githubusercontent.com', 'github.com'],
        'source_sha256': {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in files},
        'live_verification': results,
    })
    print('VERIFIED public committed bytes, real redirect rejection, and source-prefix escapes', flush=True)


if __name__ == '__main__':
    main()
