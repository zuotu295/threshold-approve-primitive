# Threshold Approve — M-of-N Threshold Approval Primitive

多签阈值批准原语 / M-of-N threshold approval primitive for GenLayer Stable Studionet.

A proposal executes only after exactly M distinct designated approvers have
approved it. One fewer approval, and execution fails. Pure deterministic
counting — no language model is involved: leader and validators run the same
code, so the approval vector (who approved, how many, threshold, proposal
content) must match exactly, with zero tolerance, for a state transition.

一个提案只有在恰好 M 个指定批准人批准后才能执行，少一个都不行。纯确定性
计数，不使用语言模型：leader 与 validator 运行同一份代码，批准向量（谁批
准、批了几个、阈值、提案内容）必须逐项精确相等、零容差，状态才会转移。

## Live deployment / 线上部署

- Network: Stable Studionet, Chain ID 61999
- Contract: `0xb0eB6Ef019387eB73Bf0F8058d3e6D194B47fD05`
- Explorer: https://explorer-studio.genlayer.com/address/0xb0eB6Ef019387eB73Bf0F8058d3e6D194B47fD05
- Source SHA-256: `708f1be39c652010fe347446a16bdf2ae21a88299b0a812154ba82197fac7a4f`
- See `deployment.json` and `evidence.json`.

## States / 状态

```
PENDING → APPROVED → EXECUTED
PENDING → REJECTED   (creator cancels a PENDING proposal; cancellation is final)
```

- `PENDING`: created, fewer than M approvals.
- `APPROVED`: M distinct designated approvers have approved.
- `EXECUTED`: executed after reaching the threshold.
- `REJECTED`: cancelled by the creator while still PENDING.

## Methods / 调用方法

| Method | Who | Rule |
|---|---|---|
| `create_proposal(slug, action, amount, recipient, approvers_json, threshold_m)` | anyone | `1 <= M <= N`, `1 <= N <= 9`, approvers unique valid addresses, otherwise creation fails |
| `approve(proposal_id)` | designated approver only | caller must be on the approver list (sender-bound via `gl.message.sender_address`); one approval per approver; non-approver or duplicate approval fails |
| `execute(proposal_id)` | anyone, after threshold | requires state `APPROVED` and `approval_count >= M` with the approval set and proposal content exactly matching; executing below M fails |
| `cancel(proposal_id)` | creator only, while PENDING | moves the proposal to `REJECTED` |
| `get_proposal(proposal_id)` | view | returns the proposal JSON, or empty when missing |
| `get_protocol()` | view | protocol rules and limits |

Approval counting is exact: `approval_count` must equal the size of the
distinct approval set, and `execute` re-checks the content hash over
(action, amount, recipient, approvers, threshold) before changing state.

## Evidence / 证据

Proposal `release-1`: 3 approvers, threshold M = 2, amount 5, action
"Release 5 GEN to contributor for milestone delivery". All transactions
FINALIZED with MAJORITY_AGREE under full consensus (`leader_only: false`,
`execution_mode: NORMAL`).

| Step | Result | Transaction |
|---|---|---|
| Deploy | `return` | `0x48a6df3b78e58bb037cae49a0167a953eb015e15c3d1f7d25be84d0292437fef` |
| Create proposal | `return` | `0xb6a8190a9ab4cc92c14d0cecdd86e8f35b0eb987fe337eefa3dd435c3bb02796` |
| Execute before threshold (bad) | `contract_error`, leader + validator agree | `0x1b89c96c948071ef02376482d23ddd0f24abcd09fbf5ab5bb047edf6a2692b04` |
| Approve by non-approver (bad) | `contract_error`, leader + validator agree | `0x0d83cc995bbb68be5d657ea92181e4c698c6b1425ed26d6ef851318447311941` |
| Approve by approver A (1/2) | `return`, stays PENDING | `0x290ba321846e1029d9eb395606007c68537679a53ae1bcd4235d40e6119acabb` |
| Approve by approver B (2/2) | `return`, becomes APPROVED | `0xfbed8811f8026b698a30a019765cbcbf5792b701b24980edc97864977939804b` |
| Execute after threshold | `return`, becomes EXECUTED | `0xd3ca077b42902b17c06fe64563d5fec3695ac83034c1a91124b7db50b05e087b` |

Final read-back (latest-final): state `EXECUTED`, revision 3,
`approval_count` 2, approvals exactly `[A, B]`. The two failed calls changed
no state — the revision count proves it (create 0 → A 1 → B 2 → execute 3).
Full receipts in `evidence/`; summary in `evidence.json`.

GEN moved: 0. `amount` is a recorded number; execution is a state
transition, not a token transfer. No GEN was spent or received anywhere in
this flow.

## Tests / 测试

Local mock tests (scripted sender address; not network consensus):

```bash
python3 -m unittest discover -s tests -v   # 9 tests
```

Live re-verification (read-only, no signer, no submission):

```bash
npm install
node tools/verify-live.mjs
```

It checks chain ID, deployed code equals `contracts/threshold_approve.py`,
source SHA-256, every receipt FINALIZED / MAJORITY_AGREE under full
consensus, good calls returning and bad calls failing with `contract_error`
on both leader and validator, and the final EXECUTED read-back.

## Known limits / 已知限制

- `amount` is recorded, not transferred: the contract does not move GEN.
  A treasury integration should call this primitive for the approval decision
  and perform the transfer only after `EXECUTED`.
- No expiry: a PENDING proposal stays pending until approved or cancelled.
- At most 9 approvers and 16 proposals per creator.

## License

MIT — see `LICENSE`.
