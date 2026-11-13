"""Shared course-digest scope for migration and read-only audits."""
import re

def include_component(path):
    text = str(path).casefold()
    return not any(term in text for term in (
        "supplemental", "turtle", "smartbook", "we want to hear from you",
    ))


def include_section(name):
    if not re.match(r"^\d+\s+-\s+", name):
        return False
    title = re.sub(r"^\d+\s+-\s+", "", name).casefold()
    return not any(term in title for term in (
        "practice test", "practice quiz", "course information",
        "course surveys", "extra credit", "onboarding exam",
    ))


def scoped_xml_files(source):
    # Traverse only course sections; never generated outputs, scripts, or the repo.
    for section in sorted(source.iterdir()):
        if section.is_dir() and include_section(section.name):
            yield from (path for path in sorted(section.rglob("*.xml")) if include_component(path.relative_to(source)))
