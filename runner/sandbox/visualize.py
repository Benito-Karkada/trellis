"""Bounded execution snapshots inside the disposable, untrusted container.

No repr(), properties, or student-defined serialization hooks are invoked while
inspecting values. This is a teaching trace, never a grading/security verdict.
"""
import json
import math
import sys
import types


class TraceLimit(BaseException):
    pass


class Recorder:
    def __init__(self, output):
        self.output = output
        self.steps = []
        self.identities = {}
        self.retained = []
        self.frames = []
        self.size = 0
        self.limited = False

    def value(self, value, heap, depth=0):
        kind = type(value)
        if kind in (str, int, float, bool, type(None)):
            if kind is str:
                return {"type": "str", "value": value[:200], "truncated": len(value) > 200}
            if kind is int and value.bit_length() > 256:
                return {"type": "int", "value": "large integer"}
            if kind is float and not math.isfinite(value):
                return {"type": "float", "value": "non-finite"}
            return {"type": kind.__name__, "value": value}
        if kind in (types.ModuleType, types.FunctionType, types.BuiltinFunctionType, type, types.MethodType):
            return {"type": "definition", "value": "module / function / class"}
        identity = id(value)
        if identity not in self.identities:
            self.identities[identity] = len(self.identities) + 1
            self.retained.append(value)
        reference = str(self.identities[identity])
        if reference in heap or depth > 3 or len(heap) >= 24:
            return {"ref": reference}
        item = {"type": type.__getattribute__(kind, "__name__")[:60], "items": []}
        heap[reference] = item  # Register first so cycles remain references.
        if kind in (list, tuple, set, frozenset):
            from itertools import islice
            item["items"] = [[str(index), self.value(child, heap, depth+1)]
                             for index, child in enumerate(islice(value, 20))]
            item["truncated"] = len(value) > 20
        elif kind is dict:
            from itertools import islice
            item["items"] = [[self.value(key, heap, depth+1), self.value(child, heap, depth+1)]
                             for key, child in islice(value.items(), 20)]
            item["truncated"] = len(value) > 20
        else:
            # Only Python's built-in instance-dictionary descriptor is safe to
            # invoke. An object may define a property named __dict__.
            attributes = {}
            for base in type.__getattribute__(kind, "__mro__"):
                descriptor = type.__getattribute__(base, "__dict__").get("__dict__")
                if descriptor is not None:
                    if type(descriptor) is types.GetSetDescriptorType:
                        try:
                            attributes = descriptor.__get__(value, kind)
                        except (AttributeError, TypeError):
                            pass
                    break
            if type(attributes) is dict:
                from itertools import islice
                item["items"] = [[key[:80], self.value(child, heap, depth+1)]
                                 for key, child in islice(attributes.items(), 20) if type(key) is str]
                item["truncated"] = len(attributes) > 20
        return {"ref": reference}

    def capture(self, frame, event, arg=None):
        heap = {}
        frames = []
        for current in self.frames[-8:]:
            variables = {}
            for name, value in list(current.f_locals.items())[:60]:
                if name.startswith("__") or type(value) in (types.ModuleType, types.FunctionType, type):
                    continue
                if len(variables) == 16:
                    break
                variables[name] = self.value(value, heap)
            frames.append({"name": current.f_code.co_name, "line": current.f_lineno, "locals": variables})
        row = {"line": frame.f_lineno, "event": event, "frames": frames, "heap": heap,
               "stdout": self.output.getvalue()[:3000]}
        if event == "return":
            row["returned"] = self.value(arg, heap)
        if event == "exception":
            row["exception"] = type.__getattribute__(arg[0], "__name__")
        size = len(json.dumps(row, ensure_ascii=True))
        if len(self.steps) >= 220 or self.size + size > 48000:
            self.limited = True
            raise TraceLimit()
        self.size += size
        self.steps.append(row)

    def trace(self, frame, event, arg):
        if frame.f_code.co_filename != "student.py":
            return None
        if event == "call":
            self.frames.append(frame)
        if event in {"line", "return", "exception"}:
            self.capture(frame, event, arg)
        if event == "return" and self.frames and self.frames[-1] is frame:
            self.frames.pop()
        return self.trace

    def run(self, source, namespace):
        try:
            code = compile(source, "student.py", "exec")
            sys.settrace(self.trace)
            exec(code, namespace)
        except TraceLimit:
            pass
        finally:
            sys.settrace(None)
            self.frames.clear()

    def result(self, status):
        return {"steps": self.steps, "truncated": self.limited, "status": status,
                "stdout": self.output.getvalue()[:4000]}
