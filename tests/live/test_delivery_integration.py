"""Integration thật qua ConversationKernel + RuntimeConversationDeliveryAdapter.

Transport, parser và LLM là mock; không gọi mạng hoặc đốt token.
"""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from runtime.live.bridge import ErisLiveRuntime
from runtime.conversation.contracts import ConversationEvent, NextConversationMove, NoReply
from runtime.conversation.delivery import SurfaceEnvelope
from runtime.conversation.writer import RenderedConversationMove
from runtime.conversation.kernel import ConversationKernel
from runtime.conversation.delivery_adapter import RuntimeConversationDeliveryAdapter
from runtime.conversation.speech_outcome import note_public_delivery_outcome

class Root:
    def __init__(self, result=None):
        self.result=result
    def decide(self, **kwargs):
        return self.result or NoReply(reason='listen')

class Writer:
    def __init__(self, before=None, text='Xin chào mọi người!'):
        self.before=before
        self.text=text
    def realize(self, *, turn,event,recent_history,runtime_context):
        if self.before: self.before()
        return RenderedConversationMove(
            surface=SurfaceEnvelope(display_text=self.text,speech_text=self.text,language='vi'),
            metadata={'event_kind':event.kind, 'event_id':event.event_id,
                      'provider_payload':{'text':self.text,'speech_text':self.text},
                      'user_text':''},
        )

class FakeDecision:
    def __init__(self): self.performance_context={}

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.host=SimpleNamespace()
        self.host.chat_history=[{'role':'user','content':'PRIVATE_OWNER_HISTORY_CANARY'}]
        self.host.memory_state={'private':'PRIVATE_OWNER_MEMORY_CANARY'}
        self.host.last_text='PRIVATE_LAST_TEXT'
        self.host.last_chat_answer='PRIVATE_LAST_ANSWER'
        self.host.parser=SimpleNamespace(parse=lambda *a,**k:FakeDecision())
        self.sent=[]
        self.host._send_decision_to_body=lambda decision,**kwargs: (self.sent.append(decision.text) or True)
        self.host._append_chat_history=lambda *args,**kwargs: self.fail('owner history touched')
        self.host._journal_conversation_turn=lambda *args,**kwargs: self.fail('owner journal touched')
        self.live=ErisLiveRuntime(self.host,enabled=True)
        self.host.eris_live=self.live
        self.live.start('room',background=False)
        self.session=self.live.session
        self.patcher=patch('runtime.speech_contract.configured_speech_language',return_value='vi')
        self.patcher.start()
        self.root=Root(NextConversationMove(intent='greet',say='Xin chào mọi người!'))
        self.writer=Writer()
        self.kernel=ConversationKernel(self.root,writer=self.writer,
                                       delivery=RuntimeConversationDeliveryAdapter(self.host))
        self.host.conversation_kernel=self.kernel

    def tearDown(self):
        self.live.stop()
        self.patcher.stop()

    def fire(self, suffix):
        return self.kernel.handle_event(
            ConversationEvent(event_id='live-'+suffix,session_id=self.session.session_id,
                              kind='live_signal', metadata={'trust':'external_untrusted'}),
            recent_history=self.session.history(),
            runtime_context={'__audience_scope':'public_live',
                             '__live_guard':lambda:self.live.guard(room='room',epoch=self.session.epoch)},
        )

    def test_live_delivery_never_writes_private_history(self):
        result=self.fire('1')
        self.assertEqual(result.status,'delivering')
        self.assertEqual(self.sent,['Xin chào mọi người!'])
        self.assertEqual(self.host.chat_history,[{'role':'user','content':'PRIVATE_OWNER_HISTORY_CANARY'}])
        self.assertEqual(self.host.last_text,'PRIVATE_LAST_TEXT')
        self.assertFalse(self.session.history())  # chưa audio_done
        note_public_delivery_outcome(self.host,delivery_id=result.delivery_id,status='delivered')
        self.assertEqual(self.session.history()[-1]['content'],'Xin chào mọi người!')
        self.assertEqual(len(self.host.chat_history),1)

    def test_live_no_reply_never_sends(self):
        self.root.result=NoReply(reason='silent')
        result=self.fire('2')
        self.assertEqual(result.status,'no_reply')
        self.assertEqual(self.sent,[])

    def test_writer_secret_blocked_before_send(self):
        self.writer.text='password=verysecretpassword'
        result=self.fire('3')
        self.assertEqual(result.status,'delivery_failed')
        self.assertEqual(self.sent,[])

    def test_stopped_in_writer_does_not_send(self):
        self.writer.before=self.live.stop
        result=self.fire('4')
        self.assertNotEqual(result.status,'delivering')
        self.assertEqual(self.sent,[])

    def test_ja_setting_fail_closed(self):
        self.patcher.stop()
        with patch('runtime.speech_contract.configured_speech_language',return_value='ja'):
            result=self.fire('5')
        self.assertEqual(result.status,'delivery_failed')
        self.assertEqual(self.sent,[])
        self.patcher.start()

if __name__=='__main__':unittest.main()
