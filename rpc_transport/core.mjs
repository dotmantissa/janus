import { timingSafeEqual } from 'node:crypto';
import { gzipSync } from 'node:zlib';

export const UPSTREAM = 'https://studio.genlayer.com/api';
export const MAX_REQUEST = 524288;
export const MAX_RESPONSE = 16777216;
const METHODS = new Set([
  'eth_chainId', 'eth_getBalance', 'eth_getTransactionCount', 'eth_gasPrice',
  'eth_estimateGas', 'eth_sendRawTransaction', 'eth_getTransactionByHash',
  'eth_getTransactionReceipt', 'eth_getBlockByNumber', 'eth_blockNumber',
  'eth_getLogs', 'eth_call', 'gen_call', 'gen_getContractCode',
  'gen_getContractSchema', 'sim_getConsensusContract',
]);

function error(message, status) {
  return Response.json({ jsonrpc: '2.0', id: null, error: { code: -32603, message } },
    { status, headers: { 'cache-control': 'no-store' } });
}

async function bounded(stream, limit) {
  if (!stream) throw new Error('Missing body');
  const reader = stream.getReader();
  const chunks = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel();
      throw new RangeError('Body limit');
    }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks, size);
}

export async function forwardRpc(request, token, fetcher = fetch) {
  if (!/^[0-9a-f]{64}$/.test(token || '')) return error('Transport unavailable', 503);
  const supplied = request.headers.get('authorization') || '';
  const expected = `Bearer ${token}`;
  if (!/^Bearer [0-9a-f]{64}$/.test(supplied) || !timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))) {
    return error('Authentication required', 401);
  }
  if (request.method !== 'POST') return error('POST required', 405);
  let body;
  try {
    body = await bounded(request.body, MAX_REQUEST);
    const input = JSON.parse(body.toString('utf8'));
    if (!input || Array.isArray(input) || input.jsonrpc !== '2.0' || !METHODS.has(input.method) || !Array.isArray(input.params)) {
      return error('Unsupported RPC request', 400);
    }
  } catch {
    return error('Invalid or oversized RPC request', 400);
  }
  try {
    // One caller request produces one upstream request. Retries belong to the
    // paced client; no transaction is regenerated or retried by this transport.
    const response = await fetcher(UPSTREAM, {
      method: 'POST', body, redirect: 'manual', signal: AbortSignal.timeout(60000),
      headers: { 'content-type': 'application/json', 'user-agent': 'genlayer-py' },
    });
    if (response.redirected || (response.status >= 300 && response.status < 400) || (response.url && response.url !== UPSTREAM)) {
      await response.body?.cancel();
      return error('Upstream redirect rejected', 502);
    }
    const bytes = await bounded(response.body, MAX_RESPONSE);
    const reply = JSON.parse(bytes.toString('utf8'));
    if (!reply || reply.jsonrpc !== '2.0' || (!('result' in reply) && !('error' in reply))) {
      return error('Invalid upstream RPC reply', 502);
    }
    // Compression preserves the original reply bytes and keeps large genuine
    // receipts below the platform response limit. No RPC fields are rewritten.
    return new Response(gzipSync(bytes), {
      status: response.status,
      headers: { 'content-type': 'application/json', 'content-encoding': 'gzip', 'cache-control': 'no-store' },
    });
  } catch (failure) {
    console.error('Janus RPC transport failure', failure.name);
    return error('Upstream RPC unavailable', 502);
  }
}
