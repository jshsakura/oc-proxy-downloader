"""One normal browser visit, retaining markup/session for offline parser repair."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from patchright.sync_api import sync_playwright


def inspect(url, output):
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (output / 'result.json').exists():
        raise ValueError('This visit already ran; no automatic repeat')
    events = []
    result = {'started_at': datetime.now(timezone.utc).isoformat(), 'automatic_retries': 0,
              'file_requests': 0, 'deletion_confirmed': False}
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=False)
        context = instance.new_context(accept_downloads=False)
        page = context.new_page()

        def observe(response):
            req = response.request
            if req.resource_type not in {'document', 'xhr', 'fetch'}:
                return
            event = {'url': response.url, 'status': response.status, 'method': req.method,
                     'type': response.headers.get('content-type', '')}
            events.append(event)
            if ('html' in event['type'] or 'json' in event['type']) and sum(p.stat().st_size for p in output.glob('*') if p.is_file()) < 30 * 1024**2:
                try:
                    body = response.body()
                    if len(body) <= 2 * 1024**2:
                        (output / (hashlib.sha256(response.url.encode()).hexdigest()[:16]+'.body')).write_bytes(body)
                except Exception:
                    pass

        page.on('response', observe)
        try:
            response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
            result['http_status'] = response.status if response else None
            if response and response.status < 400:
                page.wait_for_timeout(12000)
            result['visible_text'] = page.locator('body').inner_text(timeout=5000)[:6000]
        except Exception as exc:
            result['error_type'] = type(exc).__name__
        finally:
            try:
                (output/'page.html').write_text(page.content())
                page.screenshot(path=str(output/'page.png'), timeout=5000)
                context.storage_state(path=str(output/'session-private.json'))
                (output/'context-private.json').write_text(json.dumps({'url':page.url,'user_agent':page.evaluate('navigator.userAgent')}))
            except Exception:
                pass
            result['final_host'] = urlparse(page.url).hostname
            result['finished_at'] = datetime.now(timezone.utc).isoformat()
            (output/'http-private.json').write_text(json.dumps(events, indent=2))
            (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            instance.close()
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--links', type=Path, required=True)
    parser.add_argument('--id', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    row = next(r for r in json.loads(args.links.read_text()) if r['id'] == args.id)
    inspect(row['download_url'], args.output)
