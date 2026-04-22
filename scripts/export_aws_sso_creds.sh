#!/usr/bin/env bash
# Export temporary AWS credentials from an active SSO session.
# Usage: eval "$(bash scripts/export_aws_sso_creds.sh)"
set -euo pipefail

python3 -c "
import json, subprocess, configparser, os, glob

config = configparser.ConfigParser()
config.read(os.path.expanduser('~/.aws/config'))
profile = 'profile ' + os.environ.get('AWS_PROFILE', 'default')
if profile == 'profile default':
    profile = 'default'
sso_role = config.get(profile, 'sso_role_name')
sso_account = config.get(profile, 'sso_account_id')

cache_dir = os.path.expanduser('~/.aws/sso/cache')
tokens = sorted(glob.glob(f'{cache_dir}/*.json'), key=os.path.getmtime, reverse=True)
access_token = None
for t in tokens:
    data = json.load(open(t))
    if 'accessToken' in data:
        access_token = data['accessToken']
        break

if not access_token:
    raise SystemExit('No valid SSO token found. Run: aws sso login')

creds = json.loads(subprocess.check_output([
    'aws', 'sso', 'get-role-credentials',
    '--role-name', sso_role,
    '--account-id', sso_account,
    '--access-token', access_token,
    '--output', 'json',
]))['roleCredentials']
print(f'export AWS_ACCESS_KEY_ID={creds[\"accessKeyId\"]}')
print(f'export AWS_SECRET_ACCESS_KEY={creds[\"secretAccessKey\"]}')
print(f'export AWS_SESSION_TOKEN={creds[\"sessionToken\"]}')
"
