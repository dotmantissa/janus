import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { fetchCommitted } from '../core.mjs';

const bytes = Buffer.from('Public source bytes');
const record = { url: 'https://raw.githubusercontent.com/nodejs/Release/commit/schedule.json', url_prefix: 'https://raw.githubusercontent.com/nodejs/Release/', byte_length: bytes.length, raw_sha256: createHash('sha256').update(bytes).digest('hex') };
const request = input => new Request('https://transport.example/api/fetch', { method: 'POST', body: JSON.stringify(input) });

test('returns exactly committed bytes without redirect following', async () => {
  let seen;
  const result = await fetchCommitted(request(record), async (url, options) => {
    seen = { url, options };
    return new Response(bytes);
  });
  assert.equal(seen.url, record.url);
  assert.equal(seen.options.redirect, 'manual');
  assert.equal(result.status, 200);
  assert.deepEqual(Buffer.from(await result.arrayBuffer()), bytes);
  assert.equal(result.headers.get('x-janus-source-url'), record.url);
});

for (const status of [301, 302, 303, 307, 308]) {
  test(`rejects ${status} even for same-prefix redirect`, async () => {
    let requests = 0;
    const result = await fetchCommitted(request(record), async () => {
      requests++;
      return new Response(null, { status, headers: { location: record.url_prefix+'another' } });
    });
    assert.equal(result.status, 409);
    assert.equal(await result.text(), 'REDIRECT_REJECTED');
    assert.equal(requests, 1);
  });
}

for (const url of [record.url_prefix+'..', record.url_prefix+'.', record.url_prefix+'x/../y', record.url_prefix+'%2e%2e', 'https://raw.githubusercontent.com/nodejs/Release-evil/record', 'https://raw.githubusercontent.com.evil/nodejs/Release/record', 'https://raw.githubusercontent.com/nodejs/Release/record?x=1', 'https://raw.githubusercontent.com:443/nodejs/Release/record', 'https://127.0.0.1/record']) {
  test(`rejects noncanonical or unconfined source ${url}`, async () => {
    const result = await fetchCommitted(request({ ...record, url }), () => assert.fail('rejected URL fetched'));
    assert.equal(result.status, 409);
  });
}

test('rejects a normalized final URL changed by the HTTP client', async () => {
  const result = await fetchCommitted(request(record), async () => {
    const response = new Response(bytes);
    Object.defineProperty(response, 'url', { value: 'https://outside.example/' });
    return response;
  });
  assert.equal(result.status, 409);
});

test('rejects byte substitution and oversized streaming bodies', async () => {
  for (const body of [Buffer.from('Altered'), Buffer.alloc(record.byte_length+1)]) {
    const result = await fetchCommitted(request(record), async () => new Response(body));
    assert.equal(result.status, 409);
    assert.equal(await result.text(), 'SOURCE_BYTES_CHANGED');
  }
});
