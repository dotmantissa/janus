import { forwardRpc } from '../core.mjs';

export async function POST(request) {
  return forwardRpc(request, process.env.JANUS_RPC_TOKEN);
}
