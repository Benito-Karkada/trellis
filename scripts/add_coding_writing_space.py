#!/usr/bin/env python3
"""Plan comment/whitespace-only writing areas in published coding defaults.

Read API snapshots from var/coding-writing-space/current. Publish the resulting
plan with clean_coding_instructions.py --root var/coding-writing-space --apply.
That uploader checks revision IDs and source hashes and never edits learner work.
Sandboxes, sample answers, grader files and unpublished drafts are excluded.
"""
import argparse
import ast
import hashlib
import io
import json
import re
import tokenize
from pathlib import Path
from repair_coding_content import code_signature as _code_signature
from upload_native_graders import ROOT, private_json
from core.coding_content import local_test_lines

MARKER = '# Add your code here.'
CUE = re.compile(r'^\s*#\s*(?:add|write|insert)\s+your\s+(?:code|solution)\s+(?:here|below)[.!:]?\s*$', re.I)


def code_signature(source):
    # Tokenize reports an empty final NEWLINE for broken code without a trailing
    # newline. Normalize only that file terminator when comparing signatures.
    return _code_signature(source if source.endswith('\n') else source+'\n')


def protected_lines(source):
    """Never place a writing cue inside a string or continued expression."""
    protected = set()
    brackets = []
    last = len(source.splitlines())
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.STRING:
                protected.update(range(token.start[0]-1, token.end[0]))
            if token.type == tokenize.OP:
                if token.string in '([{':
                    brackets.append(token.start[0]-1)
                elif token.string in ')]}' and brackets:
                    start = brackets.pop()
                    protected.update(range(start, token.end[0]))
    except tokenize.TokenError as exc:
        if 'multi-line string' in str(exc):
            raise ValueError('Unclosed multiline string needs a manual writing position.') from exc
        # Deliberately broken expressions must stay broken.
    except IndentationError:
        pass
    if brackets:
        protected.update(range(min(brackets), last))
    # Explicit backslash continuations are also unsuitable insertion sites.
    for i, line in enumerate(source.splitlines()):
        if line.rstrip().endswith('\\'):
            protected.update((i, i+1))
    return protected


def original_anchors(source, original):
    """Recover the original author-selected insertion points from archived comments."""
    def tokens(text):
        result = []
        try:
            for t in tokenize.generate_tokens(io.StringIO(text).readline):
                if t.type in {tokenize.NAME, tokenize.NUMBER, tokenize.STRING, tokenize.OP, tokenize.ERRORTOKEN}:
                    result.append(t)
        except (tokenize.TokenError, IndentationError):
            pass
        return result
    before, current = tokens(original), tokens(source)
    if [(t.type, t.string) for t in before] != [(t.type, t.string) for t in current]:
        return []
    occupied = protected_lines(original)
    cues = re.compile(r'^([ \t]*)#\s*(?:add|write|put|insert|modify)\b.*\b(?:code|function|solution|lines)\b.*\b(?:here|below)\b', re.I)
    anchors = {}
    for i, line in enumerate(original.splitlines()):
        match = cues.search(line)
        if not match or i in occupied:
            continue
        count = sum(t.end[0] <= i for t in before)
        start = current[count-1].end[0] if count else 0
        anchors.setdefault(start, match.group(1))
    return sorted(anchors.items())


def writing_space(source, original=None):
    lines = source.splitlines(keepends=True)
    protected = protected_lines(source)
    newline = '\r\n' if '\r\n' in source else '\n'
    comments = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                comments.add(token.start[0]-1)
    except (tokenize.TokenError, IndentationError):
        pass
    existing = next((i for i, line in enumerate(lines) if i in comments and CUE.fullmatch(line.rstrip('\r\n'))), None)
    if existing is None and original:
        anchors = original_anchors(source, original)
        if anchors:
            result = source
            for start, indent in reversed(anchors):
                edited = result.splitlines(keepends=True)
                end = start
                while end < len(edited) and not edited[end].strip():
                    end += 1
                prefix = ''.join(edited[:start])
                if prefix and not prefix.endswith(('\n', '\r')):
                    prefix += newline
                if prefix and prefix.splitlines()[-1].strip():
                    prefix += newline
                result = prefix + indent + MARKER + newline*5 + ''.join(edited[end:])
            if code_signature(result) != code_signature(source):
                raise ValueError('Executable Python changed; requires manual review.')
            return result
    if existing is not None:
        start = existing
        indent = re.match(r'\s*', lines[start]).group().replace('\n', '').replace('\r', '')
        end = start + 1
        while end < len(lines) and not lines[end].strip():
            end += 1
    else:
        # Existing large gaps usually mark the original insertion point. Preserve
        # its position, including gaps inside a provided function or class.
        start = end = None
        i = 0
        while i < len(lines):
            if lines[i].strip() or i in protected:
                i += 1
                continue
            j = i
            while j < len(lines) and not lines[j].strip() and j not in protected:
                j += 1
            if j-i >= 3:
                start, end = i, j
                break
            i = max(i+1, j)
        from_gap = start is not None
        if start is None:
            tests = local_test_lines(source)
            start = min(tests) if tests else len(lines)
            if not tests:
                try:
                    tree = ast.parse(source)
                    calls = [n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
                    if calls:
                        start = calls[0].lineno-1
                        # Keep test-input declarations with the calls they support.
                        while start and (not lines[start-1].strip() or lines[start-1].lstrip().startswith(('#', 'test_'))):
                            start -= 1
                except (SyntaxError, ValueError):
                    pass
            if start in protected:
                start = len(lines)
            end = start
        prior = next((line for line in reversed(lines[:start]) if line.strip()), '')
        indent = re.match(r'[ \t]*', prior).group() if from_gap else ''
        if from_gap and prior.rstrip().endswith(':'):
            indent += '\t' if '\t' in indent else '    '
    while end < len(lines) and not lines[end].strip():
        end += 1
    prefix = ''.join(lines[:start])
    if prefix and not prefix.endswith(('\n', '\r')):
        prefix += newline
    if prefix and prefix.splitlines()[-1].strip():
        prefix += newline
    result = prefix + indent + MARKER + newline*5 + ''.join(lines[end:])
    if code_signature(result) != code_signature(source):
        raise ValueError('Executable Python changed; requires manual review.')
    return result


def prepare(snapshot):
    p = snapshot['part']
    base = {'part_id': p['id'], 'assignment_id': p['assignment_id'], 'title': p['title'], 'base_revision': p['revision_id']}
    if p['kind'] != 'coding' or p['metadata'].get('sandbox'):
        return {**base, 'status': 'excluded', 'reason': 'Not a graded coding workspace.'}
    if p['revision_id'] != p['published_revision_id']:
        return {**base, 'status': 'review', 'reason': 'An unpublished draft exists; preserved.'}
    entry = p['grading'].get('entrypoint')
    source = snapshot['files'].get(entry)
    if source is None or not entry.endswith('.py'):
        return {**base, 'status': 'review', 'reason': 'No editable Python entrypoint; preserved.'}
    archive = ROOT/'var/workspace-instruction-cleanup'/f"part-{p['id']}.json"
    original = json.loads(archive.read_text())['files'].get(entry) if archive.exists() else None
    fixed = writing_space(source, original)
    return {**base, 'status': 'ready' if fixed != source else 'unchanged',
            'content': p['content'], 'content_changed': False,
            'files': [{'path': entry, 'text': fixed, 'visibility': 'student'}] if fixed != source else [],
            'source_hashes': {path: hashlib.sha256(text.encode()).hexdigest() for path, text in snapshot['files'].items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT/'var/coding-writing-space')
    args = parser.parse_args()
    rows = []
    for path in sorted((args.root/'current').glob('part-*.json')):
        snapshot = json.loads(path.read_text())
        try:
            rows.append(prepare(snapshot))
        except ValueError as exc:
            p = snapshot['part']
            rows.append({'part_id': p['id'], 'title': p['title'], 'status': 'review', 'reason': str(exc)})
    private_json(args.root/'plan.json', {'version': 1, 'parts': rows})
    print({status: sum(row['status'] == status for row in rows) for status in ('ready', 'unchanged', 'excluded', 'review')})
    for row in rows:
        if row['status'] == 'review':
            print('Review:', row['part_id'], row['reason'])

if __name__ == '__main__':
    main()
