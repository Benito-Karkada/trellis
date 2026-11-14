"""Check the deployed POC through its real HTTPS/session authentication flow.

Usage: python scripts/smoke-azure-preview.py --credentials var/azure-poc/login-details.json
Credentials are never printed. Only the instructor's own session is changed.
"""
import argparse
import json
from pathlib import Path
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--execution-enabled', action='store_true', help='Expect the Azure execution worker to be enabled')
    args = parser.parse_args()
    credentials = json.loads(args.credentials.read_text())
    base = credentials['url'].rstrip('/')
    session = requests.Session()

    def get(path):
        response = session.get(base + path, timeout=60)
        response.raise_for_status()
        return response.json()

    def post(path, body):
        response = session.post(base + path, json=body, headers={
            'X-CSRFToken': session.cookies.get('csrftoken', ''), 'Referer': base + '/',
        }, timeout=60)
        return response

    response = session.get(base + '/', timeout=60)
    assert response.status_code == 200 and '<html' in response.text.lower()
    state = get('/api/session/')
    assert not state['authenticated'] and not state['registration_open'] and not state['local_login']
    assert session.get(base + '/api/outline/', timeout=30).status_code == 403
    assert post('/api/auth/register/', {}).status_code == 403
    response = post('/api/auth/login/', {'email': credentials['email'], 'password': credentials['password']})
    assert response.status_code == 200, f'Login failed with status {response.status_code}'
    outline = get('/api/outline/')
    assert outline['role'] == 'instructor'
    activities = [a for lesson in outline['lessons'] for a in lesson['activities']]
    print(f"HTTPS login and instructor outline: OK ({len(outline['lessons'])} sections, {len(activities)} activities)")
    question = next(a for a in activities if a['metadata'].get('kind') == 'question')
    native = get(f"/api/studio/{question['id']}/?mode=config")
    responses = {}
    for qid, rule in native['grading'].get('questions', {}).items():
        if rule.get('accept_nonempty'):
            responses[qid] = 'Preview check'
        elif 'correct_choice_ids' in rule:
            responses[qid] = rule['correct_choice_ids'][0] if rule.get('selection') == 'one' else rule['correct_choice_ids']
        elif rule.get('answers'):
            responses[qid] = str(rule['answers'][0])
    if responses:
        result = post(f"/api/submit-native/{native['revision']}/", {'responses': responses, 'preview': True})
        assert result.status_code == 200 and result.json()['passed'] is True
        print('Native question grading in preview: OK')
    for coding in activities:
        if coding['metadata'].get('kind') != 'coding' or coding['metadata'].get('sandbox'):
            continue
        config = get(f"/api/studio/{coding['id']}/?mode=config")
        if any(f['visibility'] != 'student' for f in config['files']) and any(f['visibility'] == 'student' for f in config['files']):
            break
    else:
        raise AssertionError('No imported coding exercise has both workspace and grading files')
    preview = get(f"/api/studio/{coding['id']}/?mode=preview")
    assert 'grading' not in preview and all('visibility' not in f for f in preview['files'])
    # Intentionally omit files: enabled execution must validate the workspace,
    # while disabled execution must reject the request before queueing anything.
    expected_status = 400 if args.execution_enabled else 503
    assert post(f"/api/execute/{preview['revision']}/", {'operation': 'run', 'preview': True}).status_code == expected_status
    if preview['files']:
        assert 'text' in get(f"/api/files/{preview['files'][0]['id']}/?mode=preview")
    hidden = next((f for f in config['files'] if f['visibility'] != 'student'), None)
    assert hidden is not None, 'Select a coding exercise with grading files for this check'
    if hidden:
        assert 'text' in get(f"/api/files/{hidden['id']}/?mode=config")
    try:
        assert post('/api/student-view/', {'enabled': True}).status_code == 200
        assert get('/api/outline/')['role'] == 'student'
        assert session.get(base + f"/api/studio/{coding['id']}/?mode=config", timeout=60).status_code == 403
        if hidden:
            assert session.get(base + f"/api/files/{hidden['id']}/", timeout=60).status_code in (403, 404)
            assert session.get(base + f"/api/files/{hidden['id']}/?mode=config", timeout=60).status_code == 403
        print('Student preview and hidden-file access controls: OK')
    finally:
        assert post('/api/student-view/', {'enabled': False}).status_code == 200
        assert post('/api/auth/logout/', {}).status_code == 200


if __name__ == '__main__':
    main()
