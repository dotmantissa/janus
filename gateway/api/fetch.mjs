import { fetchCommitted } from '../core.mjs';

export async function POST(request) {
  return fetchCommitted(request);
}
