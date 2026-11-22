"""L-05/L-06/L-14: Root public không lấy root session hoặc tool."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from runtime.conversation.agent import RuntimeModelRootAgent
from runtime.conversation.contracts import ConversationEvent, NoReply, NextConversationMove, ConversationAfter

class FakeRouter:
    def __init__(self, response):
        self.executive_client=object()
        self.response=response
        self.calls=[]
    def invoke_structured_worker(self, *args, **kwargs):
        self.calls.append(kwargs)
        return self.response

class ScopeRootTests(unittest.TestCase):
    def decide(self, response, **context):
        router=FakeRouter(response)
        root=RuntimeModelRootAgent(router)
        # Nếu gọi _prime / ask thì đang lộ Self; bắt buộc phải one-shot.
        root._root_session.ask=lambda **kw: (_ for _ in ()).throw(AssertionError('private_self_loaded'))
        event=ConversationEvent(event_id='liveevt',session_id='public_live:hashed:4',
                               kind='live_signal',metadata={'public_live':{'comments':[{'text':'hi'}]}})
        raw={'__audience_scope':'public_live','discourse_context':'viewer said hi'}
        raw.update(context)
        result=root.decide(event=event,recent_history=(),note='SECRET PRIVATE NOTE',runtime_context=raw)
        return router,result

    def test_public_no_reply_and_one_shot_no_self(self):
        router,result=self.decide({'kind':'no_reply','reason':'listen'})
        self.assertIsInstance(result,NoReply)
        self.assertEqual(len(router.calls),1)
        self.assertNotIn('SECRET PRIVATE NOTE',str(router.calls[0]))

    def test_public_move_no_continuation(self):
        router,result=self.decide({'kind':'move','intent':'greet','say':'Xin chào',
                                   'delivery':'gentle','after':'may_continue'})
        self.assertIsInstance(result,NextConversationMove)
        self.assertEqual(result.after,ConversationAfter.WAIT_USER)
        self.assertEqual(result.document_source,'')
        self.assertFalse(result.tool_artifact_bundles)

    def test_public_tool_call_forbidden(self):
        router,result=self.decide({'kind':'use_capability','capability':'action','arguments':{'path':'.env'}})
        self.assertIsInstance(result,NoReply)
        self.assertEqual(result.reason,'live_disallowed_root_action')
        self.assertEqual(len(router.calls),1)

    def test_public_memory_recall_forbidden(self):
        router,result=self.decide({'kind':'recall_memory','query':'owner password'})
        self.assertIsInstance(result,NoReply)
        self.assertEqual(result.reason,'live_disallowed_root_action')

    def test_public_provider_unavailable_fails_closed(self):
        root=RuntimeModelRootAgent(SimpleNamespace())
        result=root.decide(event=ConversationEvent(event_id='1',session_id='public_live:x:1',kind='live_signal'),
                           recent_history=(),note='',runtime_context={'__audience_scope':'public_live'})
        self.assertIsInstance(result,NoReply)

if __name__=='__main__': unittest.main()
