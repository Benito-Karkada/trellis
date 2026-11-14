"""Untrusted execution side: sees only student source and public test inputs.

This file provides observations, never verdicts. Its entire process and output
are untrusted; all comparisons and solution release decisions happen elsewhere.
"""
import contextlib
import io
import json
import random
import sys
import os
from pathlib import Path, PurePosixPath
import traceback
import ast
import signal


class ExecutionTimeout(BaseException):
    pass


def time_expired(signum, frame):
    raise ExecutionTimeout()


class OutputLimit(BaseException):
    pass


class Output(io.StringIO):
    exceeded = False
    def write(self, text):
        if self.tell() + len(text) > 32768:
            self.exceeded = True
            raise OutputLimit()
        return super().write(text)


def main():
    request = json.loads(sys.stdin.read(16_000_000))
    work=Path("/tmp/work")
    work.mkdir(exist_ok=True)
    for name,text in request.get("files",{}).items():
        path=PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:raise ValueError("Invalid path")
        destination_file=work/name
        destination_file.parent.mkdir(parents=True,exist_ok=True)
        destination_file.write_text(text)
    os.chdir(work)
    sys.path.insert(0,str(work))
    output = Output()
    destination = sys.stdout
    serialize = json.dumps
    random.seed(request["seed"])
    sys.stdin = io.StringIO(request["stdin"])
    if request.get('clock'):
        import datetime
        fixed=datetime.datetime.fromisoformat(request['clock'])
        original_date=datetime.date;original_datetime=datetime.datetime
        class FrozenDate(original_date):
            @classmethod
            def today(cls):return cls(fixed.year,fixed.month,fixed.day)
        class FrozenDatetime(original_datetime):
            @classmethod
            def now(cls,tz=None):
                instant=fixed if tz is None else fixed.replace(tzinfo=datetime.timezone.utc).astimezone(tz)
                return cls(instant.year,instant.month,instant.day,instant.hour,instant.minute,instant.second,tzinfo=instant.tzinfo)
            @classmethod
            def today(cls):return cls.now()
        FrozenDate.__name__=FrozenDate.__qualname__='date';FrozenDate.__module__='datetime'
        FrozenDatetime.__name__=FrozenDatetime.__qualname__='datetime';FrozenDatetime.__module__='datetime'
        datetime.date=FrozenDate;datetime.datetime=FrozenDatetime
    variables = request.get("variables", {})
    if not isinstance(variables, dict) or any(not isinstance(k, str) or not k.isidentifier() for k in variables):
        raise ValueError("Invalid test variables")
    namespace = {"__name__": "__main__"}
    objects={}
    def decode(value):
        import datetime
        if isinstance(value,list):return [decode(v) for v in value]
        if isinstance(value,dict):
            if set(value)=={'$fixture'}:
                import types
                descriptor=value['$fixture'];attributes=decode(descriptor.get('attributes',{}))
                instance=types.SimpleNamespace(**attributes)
                for method,field in descriptor.get('getters',{}).items():
                    if not method.isidentifier() or not field.isidentifier():raise ValueError('Invalid public fixture getter')
                    setattr(instance,method,types.MethodType(lambda self,field=field:getattr(self,field),instance))
                return instance
            if set(value)=={'$date'}:return datetime.date(*value['$date'])
            if set(value)=={'$time'}:return datetime.time(*value['$time'])
            if set(value)=={'$dict'}:return {decode(k):decode(v) for k,v in value['$dict']}
            if set(value)=={'$tuple'}:return tuple(decode(v) for v in value['$tuple'])
            if set(value)=={'$set'}:return set(decode(v) for v in value['$set'])
            if set(value)=={'$graph','$value'}:
                definitions={row['id']:row for row in value['$graph']};initialized=set();initializing=set()
                for identifier,row in definitions.items():objects[identifier]=namespace[row['class']].__new__(namespace[row['class']])
                def initialize(identifier):
                    if identifier in initialized or identifier in initializing:return
                    initializing.add(identifier);row=definitions[identifier]
                    def dependencies(item):
                        if isinstance(item,dict):
                            if set(item)=={'$object_ref'}:initialize(item['$object_ref'])
                            else:
                                for child in item.values():dependencies(child)
                        elif isinstance(item,list):
                            for child in item:dependencies(child)
                    dependencies(row['arguments'])
                    namespace[row['class']].__init__(objects[identifier],*decode(row['arguments']))
                    initialized.add(identifier);initializing.remove(identifier)
                for identifier in definitions:initialize(identifier)
                for identifier,row in definitions.items():
                    for key,child in row.get('attributes',{}).items():setattr(objects[identifier],key,decode(child))
                return decode(value['$value'])
            if set(value)=={'$object_ref'}:return objects[value['$object_ref']]
            if '$class' in value:
                cls=namespace[value['$class']]
                instance=cls.__new__(cls)
                if '$id' in value:objects[value['$id']]=instance
                cls.__init__(instance,*decode(value.get('arguments',[])))
                for k,v in value.get('attributes',{}).items():setattr(instance,k,decode(v))
                return instance
            if set(value)=={'$ref'}:return resolve(value['$ref'])
            return {k:decode(v) for k,v in value.items()}
        return value
    def resolve(target):
        pieces=target.split('.');value=namespace[pieces[0]]
        for part in pieces[1:]:value=getattr(value,part)
        return value
    namespace.update({k:decode(v) for k,v in variables.items()})
    status, value = "ok", None
    recorder = None
    # Start the student-code clock after container startup and fixture setup.
    # The controller still enforces an independent hard deadline and removal.
    signal.signal(signal.SIGALRM, time_expired)
    signal.setitimer(signal.ITIMER_REAL, request.get("timeout_seconds", 2.0))
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            source=request["source"]
            if variables:
                tree=ast.parse(source,"student.py")
                remaining=set(variables)
                body=[]
                for statement in tree.body:
                    names=set()
                    if isinstance(statement,(ast.Assign,ast.AnnAssign)):
                        targets=statement.targets if isinstance(statement,ast.Assign) else [statement.target]
                        names={target.id for target in targets if isinstance(target,ast.Name)}
                    # The exported quiz declares replaceable input variables at
                    # module scope. Remove only each variable's first declaration.
                    replaced=names & remaining
                    if replaced:
                        remaining-=replaced
                        if names-replaced:
                            body.append(statement)
                    else: body.append(statement)
                tree.body=body;ast.fix_missing_locations(tree);source=tree
            if request["action"] == "visualize":
                from importlib.util import spec_from_file_location, module_from_spec
                spec = spec_from_file_location("trellis_visualize", Path(__file__).with_name("visualize.py"))
                tracing = module_from_spec(spec)
                spec.loader.exec_module(tracing)
                recorder = tracing.Recorder(output)
                recorder.run(source, namespace)
            else:
                exec(compile(source, "student.py", "exec"), namespace)
            if request['action']=='module_outcome':value={'exception':None,'message':None,'stdout':output.getvalue().strip()}
            if request["action"] in {"function","function_stdout"}:
                if request["target"] not in namespace: status = "missing_target"
                else:
                    arguments=decode(request['arguments'])
                    for index,class_name in request.get('argument_constructors',{}).items():
                        rows=arguments[int(index)]
                        if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise ValueError('Object input needs records.')
                        arguments[int(index)]=[namespace[class_name](**row) for row in rows]
                    if request['action']=='function_stdout':output.seek(0);output.truncate(0)
                    value = namespace[request["target"]](*arguments)
            elif request["action"] == "recursion":
                original=namespace[request['target']];count=[0]
                def tracked(*args,**kwargs):
                    count[0]+=1
                    return original(*args,**kwargs)
                namespace[request['target']]=tracked
                tracked(*decode(request['arguments']));value=count[0]>1
            elif request["action"] == "function_file":
                arguments=decode(request['arguments'])
                namespace[request['target']](*arguments)
                target=(work/arguments[0]).resolve()
                if not target.is_relative_to(work):raise ValueError('Invalid output path')
                value=target.read_text()[:32768]
            elif request["action"] == "trace":
                value=[]
                for step in request['steps']:
                    op=step['op'];target=step['target'];observed=None
                    if op=='construct':namespace[step['name']]=resolve(target)(*decode(step.get('arguments',[])))
                    elif op=='exception':
                        try:resolve(target)(*decode(step.get('arguments',[])))
                        except Exception as error:observed=type(error).__name__
                    elif op=='file':
                        path=(work/target).resolve()
                        if not path.is_relative_to(work):raise ValueError('Invalid output file')
                        observed=path.read_text()[:32768].strip()
                    elif op=='read':observed=resolve(target)
                    elif op=='call':observed=resolve(target)(*decode(step.get('arguments',[])))
                    elif op=='set':
                        parent,attribute=target.rsplit('.',1);setattr(resolve(parent),attribute,decode(step['value']))
                    elif op=='exists_class':
                        try:observed=isinstance(resolve(target),type)
                        except (KeyError,AttributeError):observed=False
                    elif op=='exists':
                        try:resolve(target);observed=True
                        except (KeyError,AttributeError):observed=False
                    elif op=='callable':
                        try:observed=callable(resolve(target))
                        except (KeyError,AttributeError):observed=False
                    if step.get('record',op in {'read','call','exists','exists_class','callable','file','exception'}):value.append(observed)
            elif request["action"] == "variable":
                if request["target"] not in namespace: status = "missing_target"
                else: value = namespace[request["target"]]
            elif request["action"] == "variable_type":
                if request["target"] not in namespace: status = "missing_target"
                else:
                    # Exact built-ins: bool must not count as int, nor may a
                    # student's class named 'int' impersonate the built-in.
                    types = {int: "int", float: "float", str: "str", bool: "bool",
                             list: "list", dict: "dict", tuple: "tuple", set: "set",
                             type(None): "NoneType"}
                    value = types.get(type(namespace[request["target"]]), "unsupported")
            elif request["action"] == "file":
                target = (work / request["target"]).resolve()
                if not target.is_relative_to(work): raise ValueError("Invalid output file")
                with target.open() as file: value = file.read(32768)
            elif request["action"] == "scenario":
                if request["target"] not in namespace: status = "missing_target"
                else:
                    instance = namespace[request["target"]](*request["arguments"])
                    value = []
                    for step in request.get("steps", []):
                        member = getattr(instance, step["name"])
                        value.append(member(*step.get("arguments", [])) if step["op"] == "call" else member)
    except ExecutionTimeout:
        status = "timeout"
    except OutputLimit:
        status = "output_limit"
    except BaseException as error:
        if request['action']=='module_outcome' and isinstance(error,Exception):
            value={'exception':type(error).__name__,'message':str(error),'stdout':output.getvalue().strip()}
        else:
            status = "runtime_error"
            try:output.write(traceback.format_exc(limit=5))
            except OutputLimit:pass
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    if recorder is not None:
        value = recorder.result(status)
    if output.exceeded:
        status = "output_limit"
    try:
        payload = serialize({"status": status, "value": value, "stdout": output.getvalue()[:4000] if recorder else output.getvalue()}, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        payload = serialize({"status": "runtime_error", "value": None, "stdout": ""})
    destination.write(payload)


if __name__ == "__main__":
    main()
