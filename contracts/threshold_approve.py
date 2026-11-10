# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json
import hashlib

PROTOCOL = "threshold-approve-1"

# Deterministic M-of-N threshold approval. No language model is involved:
# every decision is exact integer counting over an explicit approver list.
# Leader and validators run the same deterministic code, so the approval
# vector (who approved, how many, threshold, proposal content) must match
# exactly, with zero tolerance, for a state transition to happen.


def require(condition, message):
    if not condition:
        raise Exception(message)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def no_duplicates(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, "DUPLICATE_JSON_KEY")
        result[k] = v
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=no_duplicates) if type(raw) is str else raw


def hash_value(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def is_address(value):
    return (type(value) is str and len(value) == 42 and value.startswith("0x")
            and all(c in "0123456789abcdefABCDEF" for c in value[2:]))


def valid_slug(slug):
    return (type(slug) is str and 3 <= len(slug) <= 32
            and all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in slug))


class ThresholdApprove(gl.Contract):
    proposals: TreeMap[str, str]
    counts: TreeMap[str, u32]

    def __init__(self):
        pass

    @gl.public.view
    def get_protocol(self) -> str:
        return encode({"protocol": PROTOCOL, "max_approvers": 9,
                       "amount_max": 1000000000000,
                       "states": ["PENDING", "APPROVED", "EXECUTED", "REJECTED"],
                       "rules": "M-of-N threshold approval. A proposal executes only after "
                                "exactly M distinct designated approvers have approved it. "
                                "Approvals are sender-bound: the caller must be on the "
                                "designated approver list, and each approver may approve once. "
                                "Execution before the threshold, approval by a non-approver, "
                                "and duplicate approval all fail. The creator may cancel a "
                                "PENDING proposal; cancellation is final."})

    @gl.public.view
    def get_proposal(self, proposal_id: str) -> str:
        return self.proposals.get(proposal_id, "")

    def _load(self, proposal_id):
        raw = self.proposals.get(proposal_id, "")
        require(bool(raw), "NOT_FOUND")
        return decode(raw)

    @gl.public.write
    def create_proposal(self, slug: str, action: str, amount: int, recipient: str,
                        approvers_json: str, threshold_m: int) -> str:
        require(valid_slug(slug), "SLUG")
        require(type(action) is str and 3 <= len(action) <= 200 and action == action.strip(),
                "ACTION_BOUND")
        require(type(amount) is int and 0 <= amount <= 1000000000000, "AMOUNT_BOUND")
        require(is_address(recipient), "RECIPIENT_ADDRESS")
        approvers = decode(approvers_json)
        require(type(approvers) is list and 1 <= len(approvers) <= 9, "APPROVER_COUNT")
        require(all(is_address(a) for a in approvers), "APPROVER_ADDRESS")
        lowered = [a.lower() for a in approvers]
        require(len(set(lowered)) == len(lowered), "DUPLICATE_APPROVER")
        require(type(threshold_m) is int and 1 <= threshold_m <= len(lowered),
                "THRESHOLD_RANGE")
        creator = str(gl.message.sender_address).lower()
        proposal_id = creator + ":" + slug
        require(not self.proposals.get(proposal_id, ""), "ALREADY_EXISTS")
        count = self.counts.get(creator, 0)
        require(count < 16, "PROPOSAL_LIMIT")
        proposal = {"id": proposal_id, "creator": creator, "action": action,
                    "amount": amount, "recipient": recipient.lower(),
                    "approvers": lowered, "threshold_m": threshold_m,
                    "approvals": [], "approval_count": 0,
                    "state": "PENDING", "revision": 0,
                    "content_hash": hash_value({"protocol": PROTOCOL, "action": action,
                                                "amount": amount,
                                                "recipient": recipient.lower(),
                                                "approvers": lowered,
                                                "threshold_m": threshold_m})}
        self.proposals[proposal_id] = encode(proposal)
        self.counts[creator] = u32(count + 1)
        return proposal_id

    @gl.public.write
    def approve(self, proposal_id: str) -> str:
        proposal = self._load(proposal_id)
        require(proposal["state"] == "PENDING", "NOT_PENDING")
        sender = str(gl.message.sender_address).lower()
        require(sender in proposal["approvers"], "NOT_APPROVER")
        require(sender not in proposal["approvals"], "ALREADY_APPROVED")
        proposal["approvals"].append(sender)
        proposal["approval_count"] = len(proposal["approvals"])
        require(proposal["approval_count"] == len(set(proposal["approvals"])),
                "APPROVAL_SET_MISMATCH")
        if proposal["approval_count"] >= proposal["threshold_m"]:
            proposal["state"] = "APPROVED"
        proposal["revision"] += 1
        self.proposals[proposal_id] = encode(proposal)
        return encode(proposal)

    @gl.public.write
    def execute(self, proposal_id: str) -> str:
        proposal = self._load(proposal_id)
        require(proposal["state"] == "APPROVED", "THRESHOLD_NOT_MET")
        require(proposal["approval_count"] >= proposal["threshold_m"],
                "THRESHOLD_NOT_MET")
        require(proposal["approval_count"] == len(set(proposal["approvals"])),
                "APPROVAL_SET_MISMATCH")
        require(proposal["content_hash"] == hash_value(
            {"protocol": PROTOCOL, "action": proposal["action"],
             "amount": proposal["amount"], "recipient": proposal["recipient"],
             "approvers": proposal["approvers"],
             "threshold_m": proposal["threshold_m"]}), "CONTENT_MISMATCH")
        proposal["state"] = "EXECUTED"
        proposal["revision"] += 1
        self.proposals[proposal_id] = encode(proposal)
        return encode(proposal)

    @gl.public.write
    def cancel(self, proposal_id: str) -> str:
        proposal = self._load(proposal_id)
        require(proposal["state"] == "PENDING", "NOT_PENDING")
        sender = str(gl.message.sender_address).lower()
        require(sender == proposal["creator"], "CREATOR_ONLY")
        proposal["state"] = "REJECTED"
        proposal["revision"] += 1
        self.proposals[proposal_id] = encode(proposal)
        return encode(proposal)
