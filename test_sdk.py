import sys
sys.path.insert(0, '/root/skv-core/src/app')
from skv_guardian_sdk import SKVGuardianSDK

class MockClient:
    class chat:
        class completions:
            @staticmethod
            def create(model, messages, temperature):
                class Msg:
                    content = '{"protocol":{"second_look":{"verified_01":true,"verified_02":true,"verified_03":true},"seal":"SKV | #1"},"actions":{"experience":[],"feedback":[]},"response":"OK"}'
                class Choice:
                    message = Msg()
                class Resp:
                    choices = [Choice()]
                return Resp()

client = MockClient()
sdk = SKVGuardianSDK(llm_client=client, model='test', skv_api_url='http://localhost:8000')
resp = sdk.chat('test', 'u1', 'hello')
print('Response:', resp)
print('Step:', sdk.step_counter.get('test'))
print('OK')
