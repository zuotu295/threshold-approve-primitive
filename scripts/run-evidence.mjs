// ThresholdApprove evidence run on Stable Studionet only (chain 61999).
// All accounts are ephemeral, generated in memory for this run only.
// No private key is written to disk, to deployment.json, or to evidence.
// Usage: node scripts/run-evidence.mjs
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createClient, createAccount, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { TransactionStatus, TransactionHashVariant } from "genlayer-js/types";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const code = readFileSync(path.join(root, "contracts", "threshold_approve.py"), "utf-8");
const codeSha = createHash("sha256").update(code).digest("hex");

const mkAccount = () => createAccount(generatePrivateKey());
const creator = mkAccount();
const approverA = mkAccount();
const approverB = mkAccount();
const approverC = mkAccount();
const outsider = mkAccount();
console.log("Creator:", creator.address);
console.log("Approvers:", approverA.address, approverB.address, approverC.address);
console.log("Outsider:", outsider.address);
console.log("Network: Stable Studionet, chain 61999, https://studio.genlayer.com/api");

const clientFor = (account) => createClient({ chain: studionet, account });
const reader = createClient({ chain: studionet });
const results = {};

async function waitFinal(hash, label) {
  const receipt = await reader.waitForTransactionReceipt({
    hash, status: TransactionStatus.FINALIZED, retries: 240, interval: 5000,
  });
  console.log(`${label}: hash=${hash} status=${receipt.statusName ?? receipt.status}`);
  return receipt;
}

function receiptSummary(r) {
  return {
    status: r.status, statusName: r.statusName ?? null,
    result_name: r.result_name ?? null,
    leader_only: r.leader_only ?? null,
    execution_mode: r.execution_mode ?? null,
    from_address: r.from_address ?? null,
    to_address: r.to_address ?? null,
    data: r.data ?? null,
    consensus_data: r.consensus_data ?? null,
  };
}

// 1. Deploy (creator account).
const deployer = clientFor(creator);
const deployHash = await deployer.deployContract({ code, args: [], leaderOnly: false });
console.log("Deploy tx:", deployHash);
const deployReceipt = await waitFinal(deployHash, "deploy");
const address =
  deployReceipt?.data?.contract_address ??
  deployReceipt?.txDataDecoded?.contractAddress ??
  deployReceipt?.contractAddress ?? null;
if (!address) throw new Error("contract address not found in deploy receipt: " + JSON.stringify(deployReceipt).slice(0, 2000));
console.log("Contract address:", address);
results.deploy = { hash: deployHash, receipt: receiptSummary(deployReceipt) };

// 2. Create proposal: 3 approvers, threshold M=2, amount 5, recipient = outsider.
const proposalId = creator.address.toLowerCase() + ":release-1";
const createHashTx = await deployer.writeContract({
  address, functionName: "create_proposal",
  args: ["release-1", "Release 5 GEN to contributor for milestone delivery",
         5, outsider.address, JSON.stringify([approverA.address, approverB.address, approverC.address]), 2],
  value: 0n, leaderOnly: false,
});
console.log("Create tx:", createHashTx);
results.create = { hash: createHashTx, receipt: receiptSummary(await waitFinal(createHashTx, "create")) };

// Helper: run a call that is EXPECTED to fail on-chain; record whatever comes back.
async function expectFail(account, label, functionName, args) {
  const client = clientFor(account);
  try {
    const hash = await client.writeContract({ address, functionName, args, value: 0n, leaderOnly: false });
    console.log(`${label}: submitted hash=${hash}`);
    const receipt = await waitFinal(hash, label);
    const summary = receiptSummary(receipt);
    console.log(`${label}: receipt result_name=${summary.result_name} status=${summary.statusName ?? summary.status}`);
    return { hash, receipt: summary, client_error: null };
  } catch (err) {
    const msg = String(err?.message ?? err);
    const m = msg.match(/0x[0-9a-fA-F]{64}/);
    console.log(`${label}: client threw: ${msg.slice(0, 400)}`);
    if (m) {
      try {
        const receipt = await waitFinal(m[0], label);
        return { hash: m[0], receipt: receiptSummary(receipt), client_error: msg.slice(0, 500) };
      } catch { /* fall through */ }
    }
    return { hash: null, receipt: null, client_error: msg.slice(0, 500) };
  }
}

// 3. BAD 1: execute before the threshold is met (only 0 approvals).
results.bad_execute_early = await expectFail(creator, "bad_execute_early", "execute", [proposalId]);
// 4. BAD 2: approve by a non-designated address.
results.bad_outsider_approve = await expectFail(outsider, "bad_outsider_approve", "approve", [proposalId]);

// 5. GOOD: approve by A (1/2, stays PENDING), then approve by B (2/2, APPROVED).
async function expectOk(account, label, functionName, args) {
  const client = clientFor(account);
  const hash = await client.writeContract({ address, functionName, args, value: 0n, leaderOnly: false });
  console.log(`${label}: hash=${hash}`);
  const receipt = await waitFinal(hash, label);
  return { hash, receipt: receiptSummary(receipt) };
}
results.approve_a = await expectOk(approverA, "approve_a", "approve", [proposalId]);
results.approve_b = await expectOk(approverB, "approve_b", "approve", [proposalId]);

// 6. GOOD: execute after threshold.
results.execute = await expectOk(creator, "execute", "execute", [proposalId]);

// 7. Read back final state (latest-final).
const raw = await reader.readContract({
  address, functionName: "get_proposal", args: [proposalId],
  transactionHashVariant: TransactionHashVariant.LATEST_FINAL,
});
const finalProposal = JSON.parse(raw);
console.log("Final proposal:", JSON.stringify(finalProposal, null, 2));
results.final_proposal = finalProposal;

// 8. Source check: deployed code must equal local file.
const deployedCode = await reader.getContractCode(address);
if (deployedCode !== code) throw new Error("DEPLOYED_SOURCE_MISMATCH");
console.log("Source check: deployed code == contracts/threshold_approve.py, sha256 =", codeSha);

// 9. Write outputs (no keys anywhere).
mkdirSync(path.join(root, "evidence"), { recursive: true });
for (const [key, entry] of Object.entries(results)) {
  if (entry && entry.receipt) {
    writeFileSync(path.join(root, "evidence", `receipt-${key}.json`), JSON.stringify(entry, null, 2) + "\n");
  }
}
const evidence = {
  protocol: "threshold-approve-1",
  network: "Stable Studionet", chain_id: 61999,
  rpc: "https://studio.genlayer.com/api",
  address, proposal_id: proposalId,
  source_sha256: codeSha,
  creator: creator.address,
  approvers: [approverA.address, approverB.address, approverC.address],
  outsider: outsider.address,
  explorer: `https://explorer-studio.genlayer.com/address/${address}`,
  transactions: Object.fromEntries(
    Object.entries(results).filter(([, v]) => v && v.hash).map(([k, v]) => [k, v.hash])),
  final_proposal: finalProposal,
  gen_moved: 0,
  notes: "No GEN moved: amount is a recorded number, execution is a state transition. Bad calls are expected to fail on-chain; see their receipts / client errors.",
};
writeFileSync(path.join(root, "evidence.json"), JSON.stringify(evidence, null, 2) + "\n");
writeFileSync(path.join(root, "deployment.json"), JSON.stringify({
  protocol: "threshold-approve-1", network: "Stable Studionet", chain_id: 61999,
  rpc: "https://studio.genlayer.com/api", address, sender: creator.address,
  source_sha256: codeSha, proposal_id: proposalId,
  explorer: `https://explorer-studio.genlayer.com/address/${address}`,
  transactions: evidence.transactions,
}, null, 2) + "\n");
console.log("Wrote evidence.json and deployment.json");

// 10. Assertions: good path must be exactly as expected.
const fp = finalProposal;
if (fp.state !== "EXECUTED") throw new Error("FINAL_STATE_NOT_EXECUTED: " + fp.state);
if (fp.approval_count !== 2) throw new Error("APPROVAL_COUNT_MISMATCH");
if (JSON.stringify(fp.approvals) !== JSON.stringify([approverA.address.toLowerCase(), approverB.address.toLowerCase()])) {
  throw new Error("APPROVAL_SET_MISMATCH");
}
if (fp.threshold_m !== 2 || fp.amount !== 5) throw new Error("CONTENT_MISMATCH");
console.log("All final-state assertions passed.");
