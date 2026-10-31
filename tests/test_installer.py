"""Installer control flow without installing software or starting real containers."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

SOURCE=Path(__file__).resolve().parents[1]

@pytest.fixture
def installer(tmp_path):
    project=tmp_path/'project with spaces'
    (project/'scripts').mkdir(parents=True)
    shutil.copy(SOURCE/'scripts/install.sh',project/'scripts/install.sh')
    for name in ('docker-compose.yml','.env.example','nginx.conf','backend/Dockerfile','frontend/index.html'):
        path=project/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('LAB_PORT=8000\nOLLAMA_URL=\n' if name=='.env.example' else 'fixture\n')
    binaries=tmp_path/'bin';binaries.mkdir()
    log=tmp_path/'docker.jsonl'
    fake=binaries/'docker'
    fake.write_text('#!'+sys.executable+'\n'+'''import json,os,sys,time
args=sys.argv[1:]
with open(os.environ['DOCKER_TEST_LOG'],'a') as output: output.write(json.dumps(args)+'\\n')
if args[:2]==['compose','version']:print('Docker Compose version v2.40.0')
elif args[:1]==['info']:
    if os.environ.get('FAKE_DAEMON')=='down':raise SystemExit(1)
    if 'OSType' in args[-1]:print('linux')
    elif 'Runtimes' in args[-1]:print('{"nvidia":{}}' if os.environ.get('FAKE_NVIDIA')=='yes' else '{}')
    else:print('12884901888')
elif args[:2]==['compose','config'] and '--environment' in args:
    from pathlib import Path
    values=dict(line.split('=',1) for line in Path('.env').read_text().splitlines() if '=' in line) if Path('.env').exists() else {}
    for key in ('OLLAMA_URL','COMPOSE_FILE'):
        print(key+'='+os.environ.get(key,values.get(key,'')))
elif args[:1]==['run']:
    if os.environ.get('FAKE_PROBE')=='fail':print('GPU runtime unavailable');raise SystemExit(1)
    print('GPU 0: NVIDIA Test GPU (UUID: GPU-test)')
elif args[:2]==['compose','up']:
    if os.environ.get('FAKE_UP')=='fail':print('synthetic startup error');raise SystemExit(1)
    if os.environ.get('FAKE_UP')=='hang':time.sleep(30)
elif args[:2]==['compose','exec']:
    print('database: ok / rag: ok / model: '+('not_ready' if os.environ.get('FAKE_READY')=='no' else 'ok'))
    raise SystemExit(1 if os.environ.get('FAKE_READY')=='no' else 0)
elif args[:2]==['compose','port']:print('127.0.0.1:19080')
''')
    fake.chmod(0o755)
    uname=binaries/'uname'
    uname.write_text('#!'+sys.executable+'\nimport os,sys\nprint(os.environ.get("FAKE_OS","Linux") if sys.argv[1]=="-s" else os.environ.get("FAKE_RELEASE","6.1"))\n')
    uname.chmod(0o755)
    smi=binaries/'nvidia-smi'
    smi.write_text('#!'+sys.executable+'\nraise SystemExit(1)\n')
    smi.chmod(0o755)
    def run(*args,**values):
        env={**os.environ,'PATH':str(binaries)+os.pathsep+os.environ['PATH'],'DOCKER_TEST_LOG':str(log),**values}
        result=subprocess.run(['bash',str(project/'scripts/install.sh'),*args],cwd=tmp_path,env=env,
                              capture_output=True,text=True,timeout=15)
        calls=[json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result,calls
    return project,run


def test_installer_no_host_ollama_or_python_needed_and_prints_actual_port(installer):
    project,run=installer
    result,calls=run('--timeout','10')
    assert result.returncode==0,result.stdout+result.stderr
    assert (project/'.env').read_text()==(project/'.env.example').read_text()
    assert 'http://127.0.0.1:19080/setup' in result.stdout
    assert ['compose','up','--build','-d'] in calls
    assert ['compose','restart','edge'] in calls
    assert not any(call and call[0] in {'pull','down'} for call in calls)


def test_installer_preserves_existing_env_and_does_not_source_it(installer):
    project,run=installer
    marker=project/'must-not-exist'
    env='OLLAMA_URL=http://host.docker.internal:11434\nUNTRUSTED="$(touch '+str(marker)+')"\n'
    (project/'.env').write_text(env)
    result,_=run('--timeout','10')
    assert result.returncode==0,result.stdout+result.stderr
    assert (project/'.env').read_text()==env and not marker.exists()


def test_installer_check_is_read_only(installer):
    project,run=installer
    result,calls=run('--check')
    assert result.returncode==0 and not (project/'.env').exists()
    assert not any(call[:2] in [['compose','up'],['compose','restart'],['compose','exec']] for call in calls)


def test_installer_missing_daemon_is_actionable_and_does_not_start(installer):
    project,run=installer
    result,calls=run(FAKE_DAEMON='down')
    assert result.returncode!=0 and 'Docker is not running' in result.stderr
    assert not (project/'.env').exists() and ['compose','up','--build','-d'] not in calls


def test_installer_failed_start_keeps_configuration(installer):
    project,run=installer
    result,calls=run('--timeout','10',FAKE_UP='fail')
    assert result.returncode!=0 and 'Startup failed' in result.stderr
    assert (project/'.env').exists() and not any('down' in call for call in calls)


def test_installer_timeout_never_claims_success_or_removes_data(installer):
    project,run=installer
    result,calls=run('--timeout','1',FAKE_READY='no')
    assert result.returncode!=0 and 'Timed out' in result.stderr
    assert 'Open the lab:' not in result.stdout
    assert (project/'.env').exists() and not any('down' in call for call in calls)


def test_installer_rejects_invalid_options_before_any_action(installer):
    _,run=installer
    result,calls=run('--timeout','0')
    assert result.returncode==2 and calls==[]


def test_nvidia_selected_only_after_successful_container_probe(installer):
    project,run=installer
    result,calls=run('--timeout','10',FAKE_NVIDIA='yes')
    assert result.returncode==0,result.stdout+result.stderr
    override=(project/'docker-compose.override.yml').read_text()
    assert 'driver: nvidia' in override and 'capabilities: [gpu]' in override
    assert 'app:' not in override and 'model-init:' not in override
    probe=next(call for call in calls if call[0]=='run')
    assert '--gpus' in probe and '--network' in probe and 'none' in probe
    assert not any(arg in probe for arg in ('-v','--volume','--privileged','-p'))


def test_failed_nvidia_probe_falls_back_and_clears_stale_gpu_configuration(installer):
    project,run=installer
    first,_=run('--timeout','10',FAKE_NVIDIA='yes')
    assert first.returncode==0
    result,calls=run('--timeout','10',FAKE_NVIDIA='yes',FAKE_PROBE='fail')
    assert result.returncode==0 and 'using CPU' in result.stdout
    assert 'driver: nvidia' not in (project/'docker-compose.override.yml').read_text()
    assert ['compose','up','--build','-d'] in calls


@pytest.mark.parametrize('values',[
    {'FAKE_OS':'Darwin','FAKE_NVIDIA':'yes'},
    {'FAKE_NVIDIA':'no'},
])
def test_cpu_platforms_do_not_probe_or_reserve_gpu(installer,values):
    project,run=installer
    result,calls=run('--timeout','10',**values)
    assert result.returncode==0,result.stdout+result.stderr
    assert not any(call[0]=='run' for call in calls)
    assert 'services: {}' in (project/'docker-compose.override.yml').read_text()


def test_wsl_selects_verified_nvidia_and_cpu_override_skips_probe(installer):
    project,run=installer
    result,_=run('--timeout','10',FAKE_RELEASE='6.6-microsoft-standard-WSL2',FAKE_NVIDIA='yes')
    assert result.returncode==0 and 'Windows/WSL2 detected' in result.stdout
    result,_=run('--gpu','cpu','--timeout','10',FAKE_NVIDIA='yes')
    assert result.returncode==0 and 'driver: nvidia' not in (project/'docker-compose.override.yml').read_text()


def test_required_gpu_fails_before_start_on_probe_failure(installer):
    project,run=installer
    result,calls=run('--gpu','nvidia','--timeout','10',FAKE_PROBE='fail')
    assert result.returncode!=0 and 'NVIDIA GPU was required' in result.stderr
    assert ['compose','up','--build','-d'] not in calls
    assert not (project/'docker-compose.override.yml').exists()


def test_host_ollama_skips_probe_and_keeps_preference(installer):
    project,run=installer
    (project/'.env').write_text('OLLAMA_URL=http://host.docker.internal:11434\n')
    result,calls=run('--timeout','10',FAKE_NVIDIA='yes')
    assert result.returncode==0 and 'Host/external Ollama selected' in result.stdout
    assert not any(call[0]=='run' for call in calls)
    assert not (project/'docker-compose.override.yml').exists()


def test_custom_override_is_never_overwritten(installer):
    project,run=installer
    override=project/'docker-compose.override.yml'
    override.write_text('services: {custom: {image: custom}}\n')
    result,calls=run('--timeout','10',FAKE_NVIDIA='yes')
    assert result.returncode==0 and 'user-managed' in result.stdout
    assert override.read_text()=='services: {custom: {image: custom}}\n'
    assert not any(call[0]=='run' for call in calls)


def test_check_never_probes_or_creates_override_even_with_nvidia(installer):
    project,run=installer
    result,calls=run('--check',FAKE_NVIDIA='yes')
    assert result.returncode==0
    assert not any(call[0]=='run' for call in calls)
    assert not (project/'docker-compose.override.yml').exists()
