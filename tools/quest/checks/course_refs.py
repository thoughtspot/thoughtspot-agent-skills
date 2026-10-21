"""Plugin: keep AgentQL Quest's lesson and Module numbers in step with the course
(references/learning-path.md).

The game's text names lessons and modules by number, and the course renumbers them. Every
"lesson X.Y" / "Module N" (or "Modules N and M") in the content must still exist; each lesson the
text names must still be the lesson about what `lesson_titles` says; and each encounter's `lesson`
must be one whose **Guarded by** line lists the encounter's case, so "In lesson 3.4's live run"
points at the lesson that actually teaches this SQL.

See build.py's "Plugins" section for the hooks.
"""
from __future__ import annotations

import re

NAME = "course_refs"
SOURCES = {"learning_path"}
KEYS = {"top": {"lesson_titles"}, "realm": {"module"}, "encounter": {"lesson"}}
REFS = {
    "realm": {"module": {"description": "The course module the realm teaches.", "type": "integer"}},
    "encounter": {"lesson": {"description": "The learning-path.md lesson number, e.g. \"2.3\".", "type": "string"}},
}


def parse_learning_path(text: str) -> tuple[set[str], dict[str, set[str]], dict[str, str]]:
    """Module numbers; per lesson number ("3.4") the case ids its **Guarded by** line names; and
    per lesson number its heading title."""
    modules = set(re.findall(r"^## Module (\d+)\b", text, re.M))
    lessons: dict[str, set[str]] = {}
    titles: dict[str, str] = {}
    for m in re.finditer(r"^### (\d+\.\d+)\b([^\n]*)(.*?)(?=^##)", text + "\n##", re.S | re.M):
        guarded = re.findall(r"\*\*Guarded by:?\*\*:?([^\n]*)", m.group(3))
        lessons[m.group(1)] = {cid for line in guarded for cid in re.findall(r"`([^`]+)`", line)}
        titles[m.group(1)] = m.group(2).strip()
    return modules, lessons, titles


def check_course_refs(content_text: str, doc: dict, modules: set[str], lessons: dict[str, set[str]],
                      titles: dict[str, str] | None = None) -> list[str]:
    errors = []
    expect = doc.get("lesson_titles") or {}
    named = set(re.findall(r"\blessons? (\d+\.\d+)\b", content_text, re.I))
    named |= {str(e.get("lesson")) for e in doc.get("encounters") or [] if e.get("lesson")}
    for ref in sorted(named):
        if ref not in lessons:
            errors.append(f"content.yaml or strings.yaml names lesson {ref}, which learning-path.md no longer has")
        elif titles is not None:
            # A renumbered or retitled course can leave a number pointing at a different lesson.
            want = expect.get(ref)
            if not want:
                errors.append(f"lesson {ref} is named but has no entry in lesson_titles")
            elif want.lower() not in titles.get(ref, "").lower():
                errors.append(f"lesson {ref} is now {titles.get(ref)!r}, not the lesson about {want!r}")
    for a, b in re.findall(r"\bModules? (\d+)(?: and (\d+))?\b", content_text):
        for ref in filter(None, (a, b)):
            if ref not in modules:
                errors.append(f"content.yaml or strings.yaml names Module {ref}, which learning-path.md no longer has")
    realm_of = {eid: r for r in doc.get("realms") or [] for eid in r.get("encounters") or []}
    for r in doc.get("realms") or []:
        if str(r.get("module")) not in modules:
            errors.append(f"realm {r.get('id')}: Module {r.get('module')} is not in learning-path.md")
    for e in doc.get("encounters") or []:
        cid, lesson = e.get("case"), str(e.get("lesson") or "")
        realm = realm_of.get(e.get("id"))
        if realm and lesson and lesson.split(".")[0] != str(realm.get("module")):
            errors.append(f"{cid}: lesson {lesson} is not in Module {realm.get('module')}, its realm's module")
        if not lesson:
            errors.append(f"{cid}: missing lesson (the learning-path.md lesson it comes from)")
        elif lesson not in lessons:
            errors.append(f"{cid}: lesson {lesson} is not in learning-path.md")
        elif cid not in lessons[lesson]:
            errors.append(f"{cid}: lesson {lesson}'s Guarded by line does not list {cid}")
    return errors


def load(pack, errors: list[str]):
    return parse_learning_path(pack.source("learning_path").read_text(encoding="utf-8"))


def realm(course, r: dict, where: str, errors: list[str]) -> dict:
    module = r.get("module")
    if not isinstance(module, int) or isinstance(module, bool):  # never 4.0: strict decoders reject a float
        errors.append(f"{where}: module must be a whole number")
    return {"module": module if isinstance(module, int) else 0}


def encounter(course, e: dict, panes: dict, where: str, errors: list[str]) -> dict:
    return {"lesson": str(e.get("lesson") or "")}


def finish(course, pack, data: dict, errors: list[str]) -> None:
    # strings.yaml is scanned too: wording that names a lesson must stay in step as well.
    errors.extend(check_course_refs(pack.content_text + "\n" + pack.strings_text, pack.doc, *course))
