"""Student-facing comparisons; verdicts come from the trusted grading engine."""
from .spec import valid_value


def value_and_type(value):
    if not valid_value(value):
        return "unsupported or oversized value"
    return f"{type(value).__name__} {repr(value)}"


def comparison(case, observation, passed):
    prefix = ""
    if case.arguments:
        prefix = "We tested your code with arguments " + repr(case.arguments) + ". "
    if case.variables:
        prefix += "We tested your code with " + repr(case.variables) + ". "
    if case.stdin:
        prefix += f"We tested your code with input {case.stdin!r}. "
    if case.files:
        prefix += 'Test file contents:\n'+'\n\n'.join(path+':\n'+text for path,text in case.files.items())+'\n\n'
    expected = value_and_type(case.expected)
    actual = value_and_type(observation.value)
    if observation.status == "timeout":
        return prefix + "Your program exceeded the time limit and was stopped safely. Check that your loops reach their stopping condition, then try again."
    if observation.status == "output_limit":
        return prefix + "Your program produced too much output."
    if observation.status == "missing_target":
        kind = "variable" if case.action == "variable_type" else case.action
        return prefix + f"We expected to find a {kind} called {case.target}, but we did not."
    if observation.status == "runtime_error":
        expectation = (f"We expected {case.target} to return the {expected}. " if case.action == "function"
                       else f"We expected the file {case.target} to contain this:\n{case.expected}\n\n" if case.action == "file"
                       else f"We expected your code to print this:\n\n{case.expected}\n\n" if case.action in {"stdout","function_stdout"}
                       else f"We expected the value of {case.target} to be the {expected}. ")
        return prefix + expectation + "However, your code encountered the following error:\n\n" + observation.stdout
    if case.action=='module_outcome':
        expected=case.expected;actual=observation.value if isinstance(observation.value,dict) else {}
        if expected.get('exception'):
            return prefix+f"We expected your code to raise {expected['exception']}: {expected['message']}. "+('It did.' if passed else f"Instead, it produced {actual!r}.")
        return prefix+f"We expected your code to print:\n\n{expected.get('stdout','')}\n\n"+('It did.' if passed else f"Instead, it produced {actual!r}.")
    if case.action=='recursion':
        return prefix+f'We expected {case.target} to make recursive calls, '+('and it did.' if passed else 'but it did not.')
    if case.action=='trace':
        from .engine import equivalent
        lines=[];index=0
        for step in case.steps:
            if not step.get('record',step['op'] in {'read','call','exists','exists_class','callable','file','exception'}):continue
            wanted=case.expected[index] if index<len(case.expected) else None
            received=observation.value[index] if isinstance(observation.value,list) and index<len(observation.value) else None
            correct=equivalent(received,wanted,case.tolerance);target=step['target']
            if step['op'] in {'exists','exists_class','callable'}:
                kind='class' if step['op']=='exists_class' else 'method' if step['op']=='callable' else 'variable'
                lines.append(f'We expected to find a {kind} called {target}, '+('and we did.' if correct else 'but we did not.'))
            else:
                subject=f"{target}({', '.join(map(repr,step.get('arguments',[])))}) to return" if step['op']=='call' else f'the value of {target} to be'
                lines.append(f'We expected {subject} the {value_and_type(wanted)}'+(', and it was.' if correct else f', but instead it was the {value_and_type(received)}.'))
            index+=1
        return prefix+'\n\n'.join(lines)
    if case.action == "variable_type":
        found = f"We expected to find a variable called {case.target}, and we did.\n"
        return prefix + found + f"We expected the value of the variable {case.target} to be of type {case.expected}" + (
            ", and it was." if passed else f", but it was of type {observation.value}.")
    if case.action in {"stdout", "function_stdout", "file", "function_file"}:
        expected_text = str(case.expected)
        student_text = observation.stdout if case.action in {"stdout","function_stdout"} else str(observation.value)
        subject = "your code to print" if case.action in {"stdout","function_stdout"} else f"the file {case.target} to contain"
        if passed:
            return prefix + (f"We expected {subject} this, and it did:\n\n{expected_text}" if expected_text
                             else f"We expected {subject} nothing, and it did.")
        ending = (f"However, it {'printed' if case.action in {'stdout','function_stdout'} else 'contained'} this:\n\n{student_text}"
                  if student_text else "However, it printed nothing." if case.action in {"stdout","function_stdout"} else "However, the file was empty.")
        return prefix + f"We expected {subject} this:\n\n{expected_text}\n\n" + ending
    if case.action == "function":
        return prefix + f"We expected {case.target} to return the {expected}" + (
            ", and it did." if passed else f". However, it returned the {actual}.")
    found = f"We expected to find a variable called {case.target}, and we did.\n"
    return prefix + found + f"We expected the value of the variable {case.target} to be the {expected}" + (
        ", and it was." if passed else f", but instead it was the {actual}.")
