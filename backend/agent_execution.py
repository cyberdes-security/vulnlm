"""Per-chat-turn execution receipts and sequential planning for model tool calls.

Receipts are local to one run_chat invocation, not a cross-request idempotency
mechanism. Direct API/MCP requests and the transaction-replay exercise keep their
own semantics. A replay returns the original result, including errors: an error
may follow a committed side effect, so retrying it automatically is unsafe.
"""
from decimal import Decimal, localcontext
import json
from fastapi.encoders import jsonable_encoder
import tools


def _argument_value(value):
    """Normalize JSON key order and numeric spelling without conflating booleans."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return [type(value).__name__, value]
    if isinstance(value, (int, float)):
        number = Decimal(str(value))
        with localcontext() as context:
            context.prec = max(28, len(number.as_tuple().digits))
            normalized = str(number.normalize()) if number else '0'
        return ['number', normalized]
    if isinstance(value, dict):
        return ['object', sorted((str(key), _argument_value(item)) for key,item in value.items())]
    if isinstance(value, (list, tuple)):
        return ['array', [_argument_value(item) for item in value]]
    return ['invalid', type(value).__name__, repr(value)]


def call_key(call):
    # IDs are transport references; models can emit a new ID for the same action.
    return json.dumps([call['name'], _argument_value(call['arguments'])], sort_keys=True)


class TurnToolExecutor:
    def __init__(self):
        self.receipts = {}

    async def batch(self, calls, db, actor, *, image=False):
        """Dispatch at most one new action; resolve repeats without executing them.

        The remaining calls are marked deferred in the evidence trace and omitted
        from model history so it replans after seeing the actual result. Merely running a planned batch serially
        would still execute arguments guessed before earlier results existed.
        """
        attempted = False
        trace = []
        for call in calls:
            key = call_key(call)
            previous = self.receipts.get(key)
            if previous is not None:
                trace.append({**call, 'result':previous['result'], 'error':previous['error'],
                              'executed':False, 'reused':True, 'deferred':False,
                              'duplicate_of':previous['id']})
                continue
            if attempted:
                trace.append({**call, 'result':{'deferred':True,
                    'reason':'Not executed. Inspect the preceding tool result, then decide the next action and its actual arguments.'},
                    'error':True, 'executed':False, 'reused':False, 'deferred':True})
                continue
            attempted = True
            try:
                result = await tools.execute(call['name'], call['arguments'], db, actor,
                                             from_agent=True, image=image)
                error = False
            except Exception as exc:
                await db.rollback()
                result = {'error':str(exc)}
                error = True
            receipt = {'id':call['id'], 'result':jsonable_encoder(result), 'error':error}
            self.receipts[key] = receipt
            trace.append({**call, **receipt, 'executed':True, 'reused':False, 'deferred':False})
        return trace
