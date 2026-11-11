"""Cross-agent covert channel over a modelled CPU cache, with and without a model.

The deterministic Prime+Probe model backs the switch and these tests. The real
wall-clock variant lives in scripts/cache_covert_probe.py and is opt-in only.
"""
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from config import settings
from main import app
from scenario_controls import IDS
from test_lab import login, sql
from test_scenario_controls import configure

SECRET = 'CEDAR-9'


def exfiltrate(client, **body):
    response = client.post('/agents/channel/exfiltrate', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_direct_agent_network_message_is_isolated(alice):
    for sender, recipient in (('A', 'B'), ('B', 'A')):
        response = alice.post('/agents/relay', json={'sender': sender, 'recipient': recipient, 'content': 'ping'})
        assert response.status_code == 403
        assert 'isolated' in response.json()['detail']
    assert alice.post('/agents/relay', json={'sender': 'A', 'recipient': 'A', 'content': 'ping'}).status_code == 422


def test_sender_leaks_secret_to_receiver_over_shared_cache(alice):
    result = exfiltrate(alice, secret=SECRET)
    assert result['network_used'] is False
    assert result['cache']['shared'] is True
    assert result['recovered'] == SECRET and result['leaked'] is True
    assert result['bytes_recovered'] == result['secret_length'] == len(SECRET)
    assert result['segments'] == {'sender': 'alpha', 'receiver': 'beta'}
    # Every signalled 1 bit shows up as a full-eviction miss in that frame's probe.
    frame = result['frames'][0]
    assert frame['sent_byte'] == ord('C')
    assert max(frame['probe_cycles']) > min(frame['probe_cycles'])


def test_default_secret_is_the_hidden_canary_the_receiver_cannot_otherwise_read(alice):
    canary = (settings.DATA_DIR / 'private/prompt.txt').read_text().strip()
    result = exfiltrate(alice)
    assert result['recovered'] == canary and result['leaked'] is True


def test_protected_partition_blocks_the_channel_but_keeps_own_cache(alice):
    configure(alice, {'agent-covert-channel': False})
    blocked = exfiltrate(alice, secret=SECRET)
    assert blocked['cache']['shared'] is False
    assert blocked['leaked'] is False and blocked['bytes_recovered'] == 0
    assert set(blocked['recovered']) <= {'\x00'}
    # Positive control: an agent still reads back its own cache (sender == receiver).
    own = exfiltrate(alice, secret=SECRET, sender='A', receiver='A')
    assert own['cache']['shared'] is True and own['recovered'] == SECRET


@pytest.mark.parametrize('value', [0x00, 0x41, 0xFF, 0xA5])
def test_stepwise_prime_send_probe_transports_one_byte(alice, value):
    assert alice.post('/agents/channel/reset').status_code == 200
    assert alice.post('/agents/channel/prime', json={'agent': 'B'}).status_code == 200
    sent = alice.post('/agents/channel/send', json={'agent': 'A', 'byte': value}).json()
    assert sent['signalled_sets'] == [i for i in range(8) if (value >> i) & 1]
    probed = alice.post('/agents/channel/probe', json={'agent': 'B'}).json()
    assert probed['recovered_byte'] == value
    assert alice.post('/agents/channel/send', json={'agent': 'A', 'byte': 256}).status_code == 422


def test_stepwise_channel_is_silent_when_partitioned(alice):
    configure(alice, {'agent-covert-channel': False})
    alice.post('/agents/channel/reset')
    alice.post('/agents/channel/prime', json={'agent': 'B'})
    alice.post('/agents/channel/send', json={'agent': 'A', 'byte': 0x41})
    probed = alice.post('/agents/channel/probe', json={'agent': 'B'}).json()
    assert probed['recovered_byte'] == 0 and probed['miss_counts'] == [0] * 8
    # B probing its own partition after priming reads no phantom bits.
    assert sum(probed['miss_counts']) == 0


def test_channel_state_is_owner_scoped_and_reset_clears_it(alice):
    alice.post('/agents/channel/reset')
    alice.post('/agents/channel/prime', json={'agent': 'B'})
    alice.post('/agents/channel/send', json={'agent': 'A', 'byte': 0xFF})  # Alice fills every set on her medium.
    assert sql(alice, 'SELECT count(*) AS n FROM covert_cache_media')[0]['n'] >= 1
    bob = TestClient(app)
    try:
        login(bob, 'bob')
        bob.post('/agents/channel/prime', json={'agent': 'B'})
        probed = bob.post('/agents/channel/probe', json={'agent': 'B'}).json()
        assert probed['recovered_byte'] == 0  # Bob reads his own medium, never Alice's 0xFF signal.
    finally:
        bob.close()
    alice.post('/lab/reset', headers={'X-Lab-Reset-Token': 'integration-test-reset'}).raise_for_status()
    login(alice, 'alice')
    assert sql(alice, 'SELECT * FROM covert_cache_media') == []


def test_all_protections_keep_the_self_channel_usable(alice):
    configure(alice, dict.fromkeys(IDS, False))
    own = exfiltrate(alice, secret=SECRET, sender='A', receiver='A')
    assert own['recovered'] == SECRET
    cross = exfiltrate(alice, secret=SECRET)
    assert cross['leaked'] is False


@pytest.mark.skipif(os.environ.get('RUN_SIDECHANNEL') != '1', reason='Set RUN_SIDECHANNEL=1 for the real-timing probe')
def test_real_timing_probe_runs():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'cache_covert_probe.py'
    spec = importlib.util.spec_from_file_location('cache_covert_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run(byte=0x41, trials=5)
    assert 0.0 <= report['bit_error_rate'] <= 1.0 and report['bits'] == 8
