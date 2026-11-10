"""Offline protocol checks with a scripted sender address; not network consensus."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest


class TreeMap:
    def __class_getitem__(cls, item):
        return dict


fake = types.ModuleType('genlayer')
fake.TreeMap = TreeMap
fake.u32 = int
fake.gl = types.SimpleNamespace(
    Contract=object,
    public=types.SimpleNamespace(view=lambda f: f, write=lambda f: f),
    message=types.SimpleNamespace(sender_address='0x1111111111111111111111111111111111111111'),
    nondet=types.SimpleNamespace(exec_prompt=lambda *a, **k: (_ for _ in ()).throw(Exception('NO_LLM'))),
    vm=types.SimpleNamespace(Return=object, run_nondet_unsafe=lambda *a, **k: (_ for _ in ()).throw(Exception('NO_LLM'))))
sys.modules['genlayer'] = fake
spec = importlib.util.spec_from_file_location(
    'threshold_approve', Path(__file__).parents[1] / 'contracts/threshold_approve.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

CREATOR = '0x1111111111111111111111111111111111111111'
A = '0x2222222222222222222222222222222222222222'
B = '0x3333333333333333333333333333333333333333'
C = '0x4444444444444444444444444444444444444444'
OUTSIDER = '0x5555555555555555555555555555555555555555'
RECIPIENT = '0x6666666666666666666666666666666666666666'


def set_sender(addr):
    fake.gl.message.sender_address = addr


class Protocol(unittest.TestCase):
    def setUp(self):
        set_sender(CREATOR)
        self.c = m.ThresholdApprove()
        self.c.proposals = {}
        self.c.counts = {}
        self.pid = self.c.create_proposal(
            'release-1', 'Release 5 GEN to contributor for milestone delivery',
            5, RECIPIENT, json.dumps([A, B, C]), 2)

    def proposal(self):
        return json.loads(self.c.get_proposal(self.pid))

    def test_good_flow_two_of_three_executes(self):
        set_sender(A)
        r = json.loads(self.c.approve(self.pid))
        self.assertEqual((r['state'], r['approval_count']), ('PENDING', 1))
        set_sender(B)
        r = json.loads(self.c.approve(self.pid))
        self.assertEqual((r['state'], r['approval_count']), ('APPROVED', 2))
        self.assertEqual(r['approvals'], [A.lower(), B.lower()])
        set_sender(CREATOR)
        r = json.loads(self.c.execute(self.pid))
        self.assertEqual((r['state'], r['revision']), ('EXECUTED', 3))

    def test_execute_before_threshold_fails(self):
        set_sender(A)
        self.c.approve(self.pid)
        set_sender(CREATOR)
        with self.assertRaisesRegex(Exception, 'THRESHOLD_NOT_MET'):
            self.c.execute(self.pid)
        self.assertEqual(self.proposal()['state'], 'PENDING')

    def test_non_approver_cannot_approve(self):
        set_sender(OUTSIDER)
        with self.assertRaisesRegex(Exception, 'NOT_APPROVER'):
            self.c.approve(self.pid)
        self.assertEqual(self.proposal()['approval_count'], 0)

    def test_duplicate_approval_fails(self):
        set_sender(A)
        self.c.approve(self.pid)
        with self.assertRaisesRegex(Exception, 'ALREADY_APPROVED'):
            self.c.approve(self.pid)
        self.assertEqual(self.proposal()['approval_count'], 1)

    def test_threshold_bounds(self):
        with self.assertRaisesRegex(Exception, 'THRESHOLD_RANGE'):
            self.c.create_proposal('bad-m0', 'Release 1 GEN', 1, RECIPIENT,
                                   json.dumps([A, B]), 0)
        with self.assertRaisesRegex(Exception, 'THRESHOLD_RANGE'):
            self.c.create_proposal('bad-m3', 'Release 1 GEN', 1, RECIPIENT,
                                   json.dumps([A, B]), 3)

    def test_duplicate_approver_and_bad_address_rejected(self):
        with self.assertRaisesRegex(Exception, 'DUPLICATE_APPROVER'):
            self.c.create_proposal('bad-dup', 'Release 1 GEN', 1, RECIPIENT,
                                   json.dumps([A, A]), 1)
        with self.assertRaisesRegex(Exception, 'APPROVER_ADDRESS'):
            self.c.create_proposal('bad-addr', 'Release 1 GEN', 1, RECIPIENT,
                                   json.dumps(['not-an-address']), 1)

    def test_cancel_rules(self):
        set_sender(A)
        with self.assertRaisesRegex(Exception, 'CREATOR_ONLY'):
            self.c.cancel(self.pid)
        set_sender(CREATOR)
        r = json.loads(self.c.cancel(self.pid))
        self.assertEqual(r['state'], 'REJECTED')
        set_sender(A)
        with self.assertRaisesRegex(Exception, 'NOT_PENDING'):
            self.c.approve(self.pid)

    def test_content_hash_matches_proposal(self):
        p = self.proposal()
        expect = m.hash_value({"protocol": "threshold-approve-1", "action": p["action"],
                               "amount": p["amount"], "recipient": p["recipient"],
                               "approvers": p["approvers"], "threshold_m": p["threshold_m"]})
        self.assertEqual(p['content_hash'], expect)

    def test_unknown_proposal(self):
        with self.assertRaisesRegex(Exception, 'NOT_FOUND'):
            self.c.approve('0x0000000000000000000000000000000000000000:nope')
        self.assertEqual(self.c.get_proposal('missing'), '')


if __name__ == '__main__':
    unittest.main()
