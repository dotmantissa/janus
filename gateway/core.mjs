import { createHash } from 'node:crypto';

export const MAX_BYTES = 49152;
// Deployment-owned transport. It never interprets evidence; validators still
// independently fetch and verify committed bytes. Only public publisher hosts
// used by this integration and the GitHub redirect probe are routable here.
const ALLOWED_HOSTS = new Set(['raw.githubusercontent.com', 'github.com']);

export function canonicalUrl(value) {
  if (typeof value !== 'string' || value.length > 1024) return null;
  const match = /^https:\/\/([a-z0-9.-]+)(?::([0-9]{1,5}))?(\/[A-Za-z0-9/_.:~-]*)$/.exec(value);
  if (!match) return null;
  const [, host, port, path] = match;
  if (host.split('.').some(label => !label || label.startsWith('-') || label.endsWith('-'))) return null;
  if (port && (!(Number(port) >= 1 && Number(port) <= 65535) || String(Number(port)) !== port || port === '443')) return null;
  if (path.includes('//') || path.split('/').some(part => part === '.' || part === '..')) return null;
  const parsed = new URL(value);
  return parsed.href === value ? parsed : null;
}

function rejected(code, status = 409) {
  return new Response(code, { status, headers: { 'cache-control': 'no-store' } });
}

export async function fetchCommitted(request, fetcher = fetch) {
  if (request.method !== 'POST') return rejected('POST_REQUIRED', 405);
  let record;
  try {
    const input = await request.text();
    if (Buffer.byteLength(input) > 4096) return rejected('INPUT_BOUNDS', 400);
    record = JSON.parse(input);
  } catch {
    return rejected('INPUT_JSON', 400);
  }
  if (!record || typeof record !== 'object' || Array.isArray(record) || Object.keys(record).sort().join(',') !== 'byte_length,raw_sha256,url,url_prefix') return rejected('INPUT_SCHEMA', 400);
  const source = canonicalUrl(record.url);
  const prefix = canonicalUrl(record.url_prefix);
  if (!source || !prefix || !record.url_prefix.endsWith('/') || source.origin !== prefix.origin || !source.pathname.startsWith(prefix.pathname) || !ALLOWED_HOSTS.has(source.hostname) || source.port) return rejected('SOURCE_CONFINEMENT');
  if (!Number.isSafeInteger(record.byte_length) || record.byte_length < 1 || record.byte_length > MAX_BYTES || typeof record.raw_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(record.raw_sha256)) return rejected('COMMITMENT_BOUNDS', 400);
  try {
    // Every redirect is rejected, including same-origin and in-prefix hops.
    const response = await fetcher(record.url, { redirect: 'manual', headers: { 'accept-encoding': 'identity' }, signal: AbortSignal.timeout(20000) });
    if (response.status >= 300 && response.status < 400) {
      await response.body?.cancel();
      return rejected('REDIRECT_REJECTED');
    }
    if (response.status !== 200 || !response.body || (response.url && response.url !== record.url) || response.redirected) {
      await response.body?.cancel();
      return rejected('SOURCE_UNAVAILABLE');
    }
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > record.byte_length) {
        await reader.cancel();
        return rejected('SOURCE_BYTES_CHANGED');
      }
      chunks.push(Buffer.from(value));
    }
    const bytes = Buffer.concat(chunks, size);
    if (size !== record.byte_length || createHash('sha256').update(bytes).digest('hex') !== record.raw_sha256) return rejected('SOURCE_BYTES_CHANGED');
    return new Response(bytes, { headers: { 'content-type': 'application/octet-stream', 'cache-control': 'no-store', 'x-janus-source-url': record.url, 'x-janus-redirect-policy': 'REJECT' } });
  } catch (error) {
    console.error('Janus transport fetch failed', error.name);
    return rejected('SOURCE_UNAVAILABLE', 502);
  }
}
