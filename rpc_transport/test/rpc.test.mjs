import test from 'node:test';
import assert from 'node:assert/strict';
import { gunzipSync } from 'node:zlib';
import { forwardRpc, UPSTREAM, MAX_REQUEST, MAX_RESPONSE } from '../core.mjs';

const token = 'a'.repeat(64); // Offline fixture, never a deployed credential.
const body = '{ "jsonrpc":"2.0", "id":1, "method":"eth_getBalance", "params":[] }';
function request(text = body, authorization = `Bearer ${token}`) {
  return new Request('https://transport.example/api/rpc', { method: 'POST', headers: { authorization }, body: text });
}
const forbidden = () => { throw new Error('Upstream must not be called'); };

test('authentication and absent configuration fail closed', async () => {
  assert.equal((await forwardRpc(request(), '', forbidden)).status, 503);
  assert.equal((await forwardRpc(request(body, ''), token, forbidden)).status, 401);
  assert.equal((await forwardRpc(request(body, `Bearer ${'b'.repeat(64)}`), token, forbidden)).status, 401);
  assert.equal((await forwardRpc(request(body, `Bearer ${'é'.repeat(64)}`), token, forbidden)).status, 401);
});
test('administrative methods, batches and invalid JSON are rejected', async () => {
  for (const text of ['[{}]', 'bad', body.replace('eth_getBalance', 'sim_reset')]) {
    assert.equal((await forwardRpc(request(text), token, forbidden)).status, 400);
  }
});
test('request bytes and reply bytes are preserved; authentication stays at relay', async () => {
  const reply = '{ "jsonrpc":"2.0", "id":1, "result":"0x123" }\n';
  let calls = 0;
  const result = await forwardRpc(request(), token, async (url, options) => {
    calls++;
    assert.equal(url, UPSTREAM);
    assert.equal(options.body.toString(), body);
    assert.equal(options.redirect, 'manual');
    assert.equal(options.headers.authorization, undefined);
    return new Response(reply);
  });
  assert.equal(calls, 1);
  assert.equal(result.headers.get('content-encoding'), 'gzip');
  assert.equal(gunzipSync(Buffer.from(await result.arrayBuffer())).toString(), reply);
});
test('genuine quota response is passed through without a retry', async () => {
  const reply = JSON.stringify({ jsonrpc: '2.0', id: null, error: { code: -32029, message: 'quota', data: { retry_after_seconds: 60 } } });
  let calls = 0;
  const result = await forwardRpc(request(), token, async () => { calls++; return new Response(reply); });
  assert.equal(calls, 1);
  assert.equal(gunzipSync(Buffer.from(await result.arrayBuffer())).toString(), reply);
});
test('redirects and changed final URLs are rejected', async () => {
  for (const status of [301, 302, 307, 308]) {
    assert.equal((await forwardRpc(request(), token, async () => new Response('', { status }))).status, 502);
  }
  const changed = new Response('{}');
  Object.defineProperty(changed, 'url', { value: 'https://other.example/api' });
  assert.equal((await forwardRpc(request(), token, async () => changed)).status, 502);
});
test('request and streamed response sizes are bounded', async () => {
  assert.equal((await forwardRpc(request('x'.repeat(MAX_REQUEST + 1)), token, forbidden)).status, 400);
  assert.equal((await forwardRpc(request(), token, async () => new Response('x'.repeat(MAX_RESPONSE + 1)))).status, 502);
});
test('non-RPC replies and network failures cannot become successful receipts', async () => {
  for (const reply of ['<html>error</html>', '{}']) {
    assert.equal((await forwardRpc(request(), token, async () => new Response(reply))).status, 502);
  }
  let calls = 0;
  assert.equal((await forwardRpc(request(), token, async () => { calls++; throw new Error('offline fault'); })).status, 502);
  assert.equal(calls, 1);
});
test('large genuine reply remains exact after compression', async () => {
  const reply = JSON.stringify({ jsonrpc: '2.0', id: 1, result: 'x'.repeat(5 * 1024 * 1024) });
  const result = await forwardRpc(request(), token, async () => new Response(reply));
  const compressed = Buffer.from(await result.arrayBuffer());
  assert.ok(compressed.length < 4500000);
  assert.equal(gunzipSync(compressed).toString(), reply);
});
