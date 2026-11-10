// Read-only live verification: no signer, deployment, or transaction submission.
import { createClient } from 'genlayer-js';
import { studionet } from 'genlayer-js/chains';
import { TransactionHashVariant } from 'genlayer-js/types';
import fs from 'node:fs';
import crypto from 'node:crypto';

const root = new URL('../', import.meta.url);
const file = (p) => JSON.parse(fs.readFileSync(new URL(p, root), 'utf8'));
const need = (ok, message) => { if (!ok) throw Error(message); };
const m = file('deployment.json');
const ev = file('evidence.json');
const c = createClient({ chain: studionet });

need(await c.getChainId() === 61999, 'CHAIN_MISMATCH');
const source = await c.getContractCode(m.address);
need(source === fs.readFileSync(new URL('contracts/threshold_approve.py', root), 'utf8'), 'DEPLOYED_SOURCE_MISMATCH');
need(crypto.createHash('sha256').update(source).digest('hex') === m.source_sha256, 'SOURCE_HASH_MISMATCH');
console.log('Source: deployed code == contracts/threshold_approve.py, sha256 =', m.source_sha256);

const expectReturn = ['deploy', 'create', 'approve_a', 'approve_b', 'execute'];
const expectError = ['bad_execute_early', 'bad_outsider_approve'];
for (const [step, hash] of Object.entries(m.transactions)) {
  const tx = await c.getTransaction({ hash });
  need(tx.statusName === 'FINALIZED', step + ':NOT_FINALIZED');
  need(tx.result_name === 'MAJORITY_AGREE', step + ':NO_CONSENSUS');
  need(tx.leader_only === false && tx.execution_mode === 'NORMAL', step + ':NOT_FULL_CONSENSUS');
  need(tx.to_address.toLowerCase() === m.address.toLowerCase(), step + ':CONTRACT_MISMATCH');
  const leader = tx.consensus_data?.leader_receipt?.find((r) => r.mode === 'leader');
  const validator = tx.consensus_data?.leader_receipt?.find((r) => r.mode === 'validator');
  if (expectReturn.includes(step)) {
    need(leader?.result?.status === 'return', step + ':LEADER_NOT_RETURN');
    need(validator?.result?.status === 'return', step + ':VALIDATOR_NOT_RETURN');
  } else if (expectError.includes(step)) {
    need(leader?.result?.status === 'contract_error', step + ':LEADER_NOT_ERROR');
    need(validator?.result?.status === 'contract_error', step + ':VALIDATOR_NOT_ERROR');
  }
  console.log(step + ': FINALIZED / MAJORITY_AGREE / ' + (leader?.result?.status ?? '?'));
}

const raw = await c.readContract({
  address: m.address, functionName: 'get_proposal', args: [m.proposal_id],
  transactionHashVariant: TransactionHashVariant.LATEST_FINAL,
});
const r = JSON.parse(raw);
need(r.state === 'EXECUTED', 'FINAL_STATE_NOT_EXECUTED');
need(r.revision === 3, 'REVISION_MISMATCH');
need(r.approval_count === 2 && r.threshold_m === 2, 'COUNT_MISMATCH');
need(JSON.stringify(r.approvals) === JSON.stringify(ev.final_proposal.approvals), 'APPROVAL_SET_MISMATCH');
need(r.amount === 5 && r.action === 'Release 5 GEN to contributor for milestone delivery', 'CONTENT_MISMATCH');
need(r.approvers.length === 3, 'APPROVER_COUNT_MISMATCH');
console.log('Final state: EXECUTED, 2/2 approvals, revision 3, content intact.');
console.log('Verified source, all receipts, full consensus, and final read-back.');
process.exit(0);
