"""Bounded static observations of submitted Python. These are review signals, not AI detection."""
import ast
import hashlib
import json
import math

DEFAULT_POLICY = {
    'tau_seconds': 180, 'focus_reference': 10,
    'allowed_imports': ['math'],
    'features': ['lambda', 'async', 'match', 'assignment_expression', 'decorator', 'comprehension'],
    'calls': ['eval', 'exec', 'compile', '__import__', 'globals', 'locals', 'map', 'filter', 'reduce', 'casefold', 'removeprefix', 'removesuffix', 'bit_length', 'bit_count', 'translate', 'maketrans', 'format_map'],
}
FEATURES = {'lambda': ast.Lambda, 'async': (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith),
            'match': ast.Match, 'assignment_expression': ast.NamedExpr,
            'comprehension': (ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)}


def policy(course):
    stored = course.metadata.get('submission_review', {})
    if not isinstance(stored, dict): stored = {}
    result = {**DEFAULT_POLICY}
    for key in ('allowed_imports', 'features', 'calls'):
        value = stored.get(key)
        if isinstance(value, list) and len(value)<=100 and all(isinstance(v,str) and v.isidentifier() and len(v)<=80 for v in value): result[key] = value
    for key, high in [('tau_seconds',3600),('focus_reference',1000)]:
        value = stored.get(key)
        if type(value) in {int,float} and math.isfinite(value) and 1<=value<=high: result[key] = value
    return result


def observations(source):
    if not isinstance(source, str) or len(source.encode()) > 256000:
        return {'status': 'too_large', 'imports': [], 'features': [], 'calls': []}
    try:
        tree = ast.parse(source)
        nodes = list(ast.walk(tree))
        if len(nodes) > 30000:
            raise ValueError('Too many syntax nodes')
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return {'status': 'unparsed', 'imports': [], 'features': [], 'calls': []}
    imports = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            imports.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.module or '').split('.')[0] if not node.level else '(relative import)')
    features = {name for name, types in FEATURES.items() if any(isinstance(n, types) for n in nodes)}
    if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.decorator_list for n in nodes):
        features.add('decorator')
    calls = []
    for node in nodes:
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
            if name:
                calls.append({'name': name, 'line': node.lineno})
    return {'status': 'parsed', 'imports': sorted(imports), 'features': sorted(features), 'calls': calls}


def analyze(files, supplied, rules):
    """Ignore syntax/imports already supplied by course staff. Never execute source."""
    flags = []; imports = set(); features = set(); parsed = 0
    sources = {p: text for p, text in files.items() if p.endswith('.py') and not p.rsplit('/', 1)[-1].startswith('sample_answer')}
    # Course-supplied imports may live in a different provided module.
    defaults = [observations(text) for p, text in supplied.items() if p.endswith('.py') and not p.rsplit('/', 1)[-1].startswith('sample_answer')]
    allowed_imports = set(rules['allowed_imports']) | {name for d in defaults for name in d['imports']}
    for path, source in sources.items():
        found = observations(source); original = observations(supplied.get(path, ''))
        parsed += found['status'] == 'parsed'
        imports.update(found['imports']); features.update(found['features'])
        for name in sorted(set(found['imports']) - allowed_imports):
            flags.append({'kind': 'import', 'name': name, 'file': path})
        for name in sorted((set(found['features']) - set(original['features'])) & set(rules['features'])):
            flags.append({'kind': 'syntax', 'name': name, 'file': path})
        original_calls = {c['name'] for c in original['calls']}
        for call in found['calls']:
            if call['name'] in rules['calls'] and call['name'] not in original_calls:
                flags.append({'kind': 'call', **call, 'file': path})
    return {'version': 1, 'digest': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
            'policy_digest': hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest(),
            'files_parsed': parsed, 'files_total': len(sources), 'imports': sorted(imports), 'features': sorted(features),
            'flags': flags[:100], 'supplied_imports': sorted(allowed_imports - set(rules['allowed_imports']))}


def provided_python(revision):
    """Load only public Python baselines, not datasets, feedback files or private graders."""
    result = {}
    for file in revision.files.filter(visibility='student',path__endswith='.py'):
        if file.path.rsplit('/',1)[-1].startswith('sample_answer'):
            continue
        with file.blob.open('rb') as stream:
            result[file.path] = stream.read().decode('utf-8',errors='replace')
    return result
