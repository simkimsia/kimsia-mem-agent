import argparse
import yaml
import json
import os
from minisweagent.models.litellm_model import LitellmModel

from env import SshEnvironment
from agent import MemoryAgent

def _extract_submission(status, result):
    status_norm = str(status).strip().lower()
    patch_text = ''

    if isinstance(result, dict):
        patch_text = str(result.get('submission', '') or result.get('patch', ''))
        if not status_norm:
            status_norm = str(result.get('exit_status', '')).strip().lower()
    elif isinstance(result, str):
        patch_text = result

    is_submitted = status_norm in {'submitted', 'submit'}
    has_diff = isinstance(patch_text, str) and ('diff --git ' in patch_text)
    has_patch = isinstance(patch_text, str) and bool(patch_text.strip())

    return (is_submitted and has_patch) or has_diff, patch_text, status_norm

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--instance-path', required=True)
    parser.add_argument('--memory-path', required=True)
    parser.add_argument('--llm-base-url', required=True)
    parser.add_argument('--llm-api-key', required=True)
    parser.add_argument('--env-ssh', required=True)
    args = parser.parse_args()

    with open(f'{args.instance_path}/instance.json') as f:
        instance = json.load(f)
    with open('config.yaml') as f:
        config = yaml.safe_load(f)

    ssh_user_password, _, ssh_host = args.env_ssh.rpartition('@')
    ssh_user, _, ssh_password = ssh_user_password.partition(':')

    task = instance['problem_statement']
    if instance['requirements']:
        task += f'\n\nRequirements:\n{instance["requirements"]}'
    if instance['interface']:
        task += f'\n\nNew interfaces introduced:\n{instance["interface"]}'
    task += f'\n\nThe {instance["repo_language"]} project "{instance["repo"]}" has been cloned to {config["environment"]["cwd"]}'

    model_name = os.environ.get('MODEL_NAME', config['model']['model_name'])

    print('agent started! model=', model_name)

    agent = MemoryAgent(
        args.memory_path,
        LitellmModel(
            model_name=model_name,
            model_kwargs={
                'api_base': args.llm_base_url,
                'api_key': args.llm_api_key,
                **config['model'].get('model_kwargs', {}),
            },
            cost_tracking='ignore_errors',
        ),
        SshEnvironment(
            ssh_host=ssh_host,
            ssh_port=22,
            ssh_user=ssh_user,
            ssh_password=ssh_password,
            cwd=config['environment']['cwd'],
            env=config['environment']['env'],
            timeout=config['environment']['timeout'],
        ),
        system_template=config['agent']['system_template'],
        instance_template=config['agent']['instance_template'],
        timeout_template=config['agent']['timeout_template'],
        format_error_template=config['agent']['format_error_template'],
        action_observation_template=config['agent']['action_observation_template'],
        step_limit=config['agent']['step_limit'],
        cost_limit=config['agent']['cost_limit'],
    )
    status, result = agent.run(task)
    agent.save_memory()
    
    should_write_patch, patch_text, status_norm = _extract_submission(status, result)
    print('done! status:', status, 'status_norm=', status_norm, 'result_type=', type(result).__name__)

    if should_write_patch:
        with open(f'{args.instance_path}/patch.diff', 'w') as f:
            f.write(patch_text)
        print('patch written. size=', len(patch_text))
    else:
        print(result)

if __name__ == "__main__":
    # forward SIGTERM from `docker stop` to Python exception
    import signal
    import sys
    signal.signal(signal.SIGTERM, lambda sig, frame: sys.exit(-sig))

    main()
