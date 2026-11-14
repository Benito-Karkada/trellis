#!/usr/bin/env python3
"""Rewrite comment-era directions in coding prompts, with a reviewable content-only plan.

Read snapshots from var/instruction-language/current. Dry run builds plan.json;
--apply publishes through the staff REST API with revision guards and verifies
that grading definitions and every attached file remain unchanged.
"""
import argparse
import copy
import json
import os
import re
from pathlib import Path
from upload_native_graders import API, private_json, ROOT


def rewrite(text):
    exact = {
        "Now, copy and paste the same lines from above into the lines below.": "In the code editor, copy and paste the same lines into the next designated area.",
        "As before, our core function below hasn't changed.": "As before, our core function in the code editor hasn't changed.",
        "We've written some code below that prints out": "The provided code in the editor prints out",
        "With the values initially supplied here,": "With the initial values provided in the code editor,",
        "For a and b above,": "For a and b in the code editor,",
        "numbers above.": "numbers in the code editor.",
        "mystery_int above.": "mystery_int in the code editor.",
        "variable curve above.": "variable curve in the code editor.",
        "exam scores for your class of 10 students above.": "exam scores for your class of 10 students in the code editor.",
        "amount shown above.": "amount provided in the code editor.",
        "list declared above,": "list declared in the code editor,",
        "Below the function definition, we're calling the function.": "The code editor includes a call after the function definition.",
        "Here is the function:": "The function is provided in the code editor.",
        "One more line is needed here; add it!": "Add the missing line in the code editor!",
        "You should only need to modify the section marked 'Write your code here!'": "You should only need to modify the solution area in the code editor.",
    }
    for before, after in exact.items():
        text = text.replace(before, after)
    rules = [
        (r'\bYou may modify the (lines?)(?: of code)? above, but (don\'t|do not) move (them|it)', r'You may modify the provided \1 in the code editor, but \2 move \3'),
        (r'\b(?:Do not|Don\'t) (modify|change|edit|touch) (?:any of )?the (code|line(?: of code)?) (above|below)', r'Do not \1 the provided \2 in the code editor'),
        (r'\bDon\'t modify anything above this line!', 'Do not modify the provided code before the solution area in the code editor!'),
        (r'\bBelow are (some )?lines of code that (will )?test your (\w+)', r'The local test code in the editor will test your \3'),
        (r'\b(The (?:lines? of code|function call|code|lines?|loop|function|classes|variables)) (above|below)\b', r'\1 in the code editor'),
        (r'\b(the (?:existing code|core function|two lists|two lines|line of code|lines?)) (above|below)\b', r'\1 in the code editor'),
        (r'\b(the (?:\w+ )?(?:variables|variable|string|list of tuples|list of strings|class definitions|classes|class)) (above|below)\b', r'\1 in the code editor'),
        (r'\b(values?|inputs|data)(?: of the variables)? (?:initially supplied )?(?:from )?above\b', r'\1 provided in the code editor'),
        (r'\b(variables (?:ones, tens, and hundreds|defined)) above\b', r'\1 in the code editor'),
        (r'\bAbove (we(?:\'ve| have) created)\b', r'In the code editor, \1'),
        (r'\bAbove are given two variables', 'Two variables are provided in the code editor'),
        (r'\bAbove (are|is)\b', r'Provided in the code editor \1'),
        (r'\bBelow,? (we(?:\'ve| have) (?:gone ahead and written|given|written|started))\b', r'In the code editor, \1'),
        (r'\bBelow (we have given you)\b', r'In the code editor, \1'),
        (r'\bBelow (is|are)\b', r'Provided in the code editor \1'),
        (r'\bBelow you\'ll find some code', "You’ll find some code in the code editor"),
        (r'\bAbove, we\'ve moved\b', "In the code editor, we've moved"),
        (r'\bBelow, (write|add)\b', r'In the code editor, \1'),
        (r'\b((?:Add|Write) (?:some |a line of |some lines of |your |the |a )?code) (below|above|here)\b', r'\1 in the code editor'),
        (r'\b((?:Add|Write) your (?:lines of code|(?:\w+ )?function(?: calls?|s)?|(?:\w+ )?class|two functions|two function calls)) (here|below)\b', r'\1 in the code editor'),
        (r'\b((?:Write|Create|Call) (?:your (?:new function|variables|dictionary|two functions)|a loop)) (here|below)\b', r'\1 in the code editor'),
        (r'\b(Write a loop) here\b', r'\1 in the code editor'),
        (r'\b(Feel free to add code) below\b', r'\1 in the code editor'),
        (r'\b(Feel free to add code to test your code) below\b', r'\1 in the code editor'),
        (r'\b(Complete (?:this |the )?(?:program|code)|Fix the code|Add to the code|Modify the code|Modify (?:one or more of )?the classes) below\b', r'\1 in the code editor'),
        (r'\b(Complete the line) below\b', r'\1 in the code editor'),
        (r'\b(Fill in the function) below\b', r'\1 in the code editor'),
        (r'\b(Implement insertion sort) below\b', r'\1 in the code editor'),
        (r'\b(In the designated areas) below\b', r'\1 in the code editor'),
        (r'\b(in the space) below\b', 'in the code editor'),
        (r'\b(three functions completely written) below\b', r'\1 in the code editor'),
        (r'\b(recursive function) below\b', r'\1 in the code editor'),
        (r"(We've written (?:the|a) function(?:, [\w]+,| [\w]+\(\))?) below\b", r'\1 in the code editor'),
        (r"(We've defined a list of tuples) below\b", r'\1 in the code editor'),
        (r'\b(defined|created|given|supplied) above\b', r'\1 in the code editor'),
        (r'\b(If your code) above\b', r'\1'),
        (r'\b(You can use the lines) below\b', r'\1 in the code editor'),
        (r'\b(Test your function|calling your function) below\b', r'\1 in the code editor'),
        (r'\b(as they appear) below\b', r'\1 in the code editor'),
        (r'\b(the line|the loop) here\b', r'\1 in the code editor'),
        (r'\b(Add some code) here\b', r'\1 in the code editor'),
        (r'\b(Write your code|Add and modify your code|Make any changes or additions|Print their types) here\b', r'\1 in the code editor'),
        (r'\bCopy that class below:', 'Copy that class into the code editor:'),
        (r'\b(paste your previous code) here\b', r'\1 into the code editor'),
        (r'\b(copy/paste your previous code) here\b', r'\1 into the code editor'),
        (r'\bprovided you the class here\b', 'provided you the class in the code editor'),
        (r'\bAdd your code to (read through the string and count the t\'s and T\'s|create the variable need_jacket with the appropriate value) here', r'Add your code in the code editor to \1'),
        (r'\bBelow that funtion,', 'After that function in the code editor,'),
        (r'\bNow, copy and paste the same lines from above into the lines below\.', 'In the code editor, copy and paste the same lines into the next designated area.'),
        (r'\bSee below!', 'See the code editor!'),
    ]
    for pattern, replacement in rules:
        text = re.sub(pattern, replacement, text, flags=re.I)
    # Remaining named functions/classes are prose references, not code literals.
    text = re.sub(r"(We've written the function, [\w]+,) below", r'\1 in the code editor', text, flags=re.I)
    return text


def update_nodes(nodes, changes):
    for node in nodes:
        if node.get('tag') in {'pre', 'code', 'kbd', 'samp', 'script', 'style'}:
            continue
        if node.get('type') == 'text':
            before = node.get('text', '')
            after = rewrite(before)
            if after != before:
                node['text'] = after
                changes.append({'before': before, 'after': after})
        elif 'children' in node:
            update_nodes(node['children'], changes)


def prepare(part):
    content = copy.deepcopy(part['content'])
    changes = []
    for block in content['blocks']:
        if block['type'] == 'coding':
            update_nodes(block.get('prompt', []), changes)
    return {'part_id': part['id'], 'title': part['title'], 'assignment_id': part['assignment_id'],
            'base_revision': part['revision_id'], 'content': content, 'changes': changes,
            'files': [], 'source_hashes': {},
            'status': 'review' if part['revision_id'] != part['published_revision_id'] else 'ready' if changes else 'unchanged',
            'reason': 'An unpublished draft exists; preserved.' if part['revision_id'] != part['published_revision_id'] else ''}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT/'var/instruction-language')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        rows = [prepare(json.loads(p.read_text())) for p in sorted((args.root/'current').glob('part-*.json'))]
        private_json(args.root/'plan.json', {'version': 1, 'parts': rows})
        print({s: sum(r['status'] == s for r in rows) for s in ('ready', 'unchanged', 'review')})
        return
    # Existing uploader provides resumable idempotency keys and publishes only
    # when the revision still matches the reviewed snapshot.
    import subprocess, sys
    subprocess.run([sys.executable, str(ROOT/'scripts/clean_coding_instructions.py'), '--root', str(args.root), '--apply'], check=True)
    api = API(os.environ['TRELLIS_URL'], os.environ['TRELLIS_API_TOKEN'])
    verified = []
    try:
        plans = json.loads((args.root/'plan.json').read_text())['parts']
        state = json.loads((args.root/'upload-state.json').read_text())
        for row in plans:
            if row['status'] != 'ready' or state.get(str(row['part_id']), {}).get('phase') != 'published':
                continue
            after = api.request('GET', f"/parts/{row['part_id']}/")
            before = json.loads((args.root/'current'/f"part-{row['part_id']}.json").read_text())
            assert after['content'] == row['content'], f"Content verification failed: {row['part_id']}"
            assert after['revision_id'] == after['published_revision_id']
            for key in ('grading', 'files', 'metadata', 'title', 'position'):
                assert (sorted(after[key], key=lambda f: f['path']) == sorted(before[key], key=lambda f: f['path']) if key == 'files' else after[key] == before[key]), f"Unexpected {key} change: {row['part_id']}"
            verified.append(row['part_id'])
            if len(verified) % 50 == 0: print('Verified', len(verified), flush=True)
        private_json(args.root/'verified.json', {'verified': verified})
        print('Verified content-only updates:', len(verified), flush=True)
    finally:
        api.session.close()


def refresh_preserving_draft(api, snapshot, root):
    """Publish prose from the live revision while retaining an existing file draft.

    Stage the restored draft *before* publishing the separate live candidate, so
    no unpublished file edits are accidentally released to students. All steps
    use saved idempotency keys and revision preconditions for safe resumption.
    """
    from urllib.parse import quote
    import uuid
    pid = snapshot['id']
    directory = root/f'preserved-draft-{pid}'
    statepath = directory/'state.json'
    state = json.loads(statepath.read_text()) if statepath.exists() else {}
    if not state:
        current = api.request('GET', f'/parts/{pid}/')
        if current['revision_id'] != snapshot['revision_id'] or current['published_revision_id'] != snapshot['published_revision_id']:
            raise RuntimeError('Draft changed since review; preserved without modification.')
        published = api.request('GET', f"/parts/{pid}/revisions/{current['published_revision_id']}/")
        if current['grading'] != published['grading']:
            raise RuntimeError('Draft has grading changes; manual review needed.')
        live_files = {f['path']: f for f in published['files']}
        draft_files = {f['path']: f for f in current['files']}
        if live_files.keys() != draft_files.keys():
            raise RuntimeError('Draft adds or removes files; manual review needed.')
        changed_paths = [p for p in live_files if live_files[p] != draft_files[p]]
        payloads = {'live': [], 'draft': []}
        for name, revision, expected in [('live', published['revision_id'], live_files), ('draft', current['revision_id'], draft_files)]:
            for path in changed_paths:
                f = api.request('GET', f"/parts/{pid}/files/{quote(path,safe='/')}?revision_id={revision}")
                assert f['sha256'] == expected[path]['sha256']
                payloads[name].append({k: f[k] for k in ('path','visibility','text','content_base64') if k in f})
        state = {'before': current, 'published_before': published, 'payloads': payloads,
                 'live_content': prepare(published)['content'], 'draft_content': prepare(current)['content'],
                 'keys': {step: str(uuid.uuid4()) for step in ('draft','candidate','restored','publish')}}
        private_json(statepath, state)
    previous = state['before']['revision_id']
    stages = [
        ('draft', {'content': state['draft_content']}),
        ('candidate', {'content': state['live_content'], 'files': state['payloads']['live']}),
        ('restored', {'content': state['draft_content'], 'files': state['payloads']['draft']}),
    ]
    for step, body in stages:
        if step not in state:
            result = api.request('PATCH', f'/parts/{pid}/', body, previous, state['keys'][step])
            state[step] = result['revision_id']; private_json(statepath, state)
        previous = state[step]
    restored = api.request('GET', f'/parts/{pid}/')
    assert restored['revision_id'] == state['restored'], 'Another author changed this draft; publication stopped.'
    assert restored['content'] == state['draft_content']
    assert restored['files'] == state['before']['files']
    assert restored['grading'] == state['before']['grading']
    candidate = api.request('GET', f"/parts/{pid}/revisions/{state['candidate']}/")
    assert candidate['content'] == state['live_content']
    assert candidate['files'] == state['published_before']['files']
    assert candidate['grading'] == state['published_before']['grading']
    api.request('POST', f'/parts/{pid}/publish/', {'revision_id': state['candidate']}, state['restored'], state['keys']['publish'])
    final = api.request('GET', f'/parts/{pid}/')
    assert final['revision_id'] == state['restored'] and final['published_revision_id'] == state['candidate']
    assert final['files'] == state['before']['files']
    state['verified'] = True; private_json(statepath, state)
    print('Updated live and draft instructions; unpublished file edits preserved:', pid, flush=True)


if __name__ == '__main__':
    main()
