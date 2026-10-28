"""The whole run on made-up CVs, the model scripted: what is asked, of which lines, and
what the answers become."""

from datetime import date

from conftest import Scripted, blank, docx, lines, run

from asas_cv_profile import ProfileBuilder, followups, review
from asas_cv_profile.calls import CallResult
from asas_cv_profile.model import one_group

AS_OF = date(2026, 10, 27)


def by_name(model, name):
    return next(s for s in model.sections if s.name == name)


def test_a_run_cites_checks_re_asks_bad_lines_and_flags(model):
    cv = docx("Sara Example", "Senior Data Analyst, Example Co, 2021-03 to present",
              "Built the monthly reporting pipeline for 12 departments", "BSc Statistics, United Arab Emirates University, 2020",
              "Tools: SQL, Python, Power BI, Tableau")

    def answer(call, s):
        if s.name == "Name":
            return {**blank(s), "full_name": "Sara Example", "lines": [[1, 1]]}
        if s.name == "Professional":
            return [{**blank(s), "job_title": "Senior Data Analyst", "company": "Example Co", "start_date": "2021-03",
                     "i_currently_work_here": True, "responsibilities": [[3, 3]], "lines": [[2, 3]]},
                    {**blank(s), "job_title": "Chief Wizard", "company": "Nowhere", "lines": [[2, 2]]},
                    {**blank(s), "job_title": "Ghost", "lines": [[99, 99]]},
                    {**blank(s), "job_title": "Data Analyst", "company": "Example Co", "lines": [[40, 41]]}]
        if s.name == "Degree":
            return [{**blank(s), "institution": "United Arab Emirates University", "graduation_date": "2020", "lines": [[4, 4]]}]
        if s.name == "Digital and AI":
            return [{"skill": "MS Power BI", "proficiency": None, "lines": [[5, 5]]}, {"skill": "Python", "proficiency": None, "lines": [[5, 5]]}]
        if s.name == "Level":
            return {"seniority": "Senior", "lines": [[2, 2]]}
        return None

    asked = []

    def fixes(message):
        """The re-ask: the ghost role has no true lines; the other slip is put right."""
        assert "L005 the last line" in message
        refs = [line.split(":")[0][2:] for line in message.splitlines() if line.startswith("- ProfileAll.")]
        asked.extend(refs)
        return [{"ref": r, "lines": [] if "[2]" in r else [[2, 2]]} for r in refs]

    model_ = Scripted(model, answer, fixes=fixes)
    built = run(ProfileBuilder(model, model_).build(cv, "cv.docx", as_of=AS_OF))
    assert asked == ["ProfileAll.work_experience_professional[2]", "ProfileAll.work_experience_professional[3]"]
    assert built["fixes"]["lines_fixed"] == 2 and built["release"] == "0" * 64
    roles = built["profile"]["Work experience"]["Professional"]
    assert roles[0]["fields"]["Job title"]["check"] == "verified"
    assert roles[0]["fields"]["Responsibilities"]["value"] == "Built the monthly reporting pipeline for 12 departments"
    assert roles[0]["fields"]["Start date"]["check"] == "verified"
    assert roles[0]["fields"]["Duration (months)"] == {"value": 68, "check": "computed", "kind": "computed"}
    assert roles[1]["fields"]["Job title"]["check"] == "unverified"
    assert roles[2]["fields"]["Job title"]["check"] == "bad_lines"  # still no lines after the re-ask: flagged, not dropped
    assert roles[3]["fields"]["Job title"]["check"] == "verified"  # re-cited to line 2
    tools = [e["fields"]["Skill"] for e in built["profile"]["Technical skills"]["Digital and AI"]]
    assert [t["value"] for t in tools] == ["Power BI", "Python", "SQL", "Tableau"]
    assert tools[0]["was"] == "MS Power BI" and tools[2]["restored"]
    assert built["profile"]["Work experience"]["Experience"]["fields"]["Total experience (months)"]["check"] == "computed"
    assert built["text"]["reader"] == "asas-cv" and built["profile_model"]["file"] == "profile.yaml"
    md = review(built)
    assert "Look at these first" in md and "Chief Wizard" in md


def test_a_section_left_empty_is_asked_again_with_its_own_lines(model):
    text = ["Sara Example", "EXPERIENCE", "Lecturer, Example University, 2019-2023", "PUBLICATIONS",
            "Example A. A study of things. Sci Rep 12 (2022).", "Example A. Another study. Folia Microbiol (2021).", "LANGUAGES", "Arabic"]

    def answer(call, s):
        if s.name == "Publication" and call != "ProfileAll":
            return [{**blank(s), "title": "A study of things", "publisher_or_venue": "Sci Rep", "lines": [[5, 5]]},
                    {**blank(s), "title": "Another study", "publisher_or_venue": "Folia Microbiol", "lines": [[6, 6]]}]
        if s.name == "Professional":
            return [{**blank(s), "job_title": "Lecturer", "lines": [[3, 3]]}]
        if s.name == "Languages":
            return [{"language": None, "lines": [[8, 8]]}]
        return None

    scripted = Scripted(model, answer)
    built = run(ProfileBuilder(model, scripted).build(b"", "cv.txt", as_of=AS_OF, text=lines(*text)))
    assert built["fixes"]["sections_asked_again"] == ["Publication", "Level"]  # roles but no level: the level asked too
    assert built["fixes"]["sections_found_again"] == ["Publication"]
    name, message = scripted.sent[1]
    assert name == "AgainPublication" and "\nL004 PUBLICATIONS" in message and "L007" not in message
    level = dict(scripted.sent)["AgainLevel"]
    assert "L003 Lecturer" in level and "L005" not in level  # the roles' lines only
    pubs = built["profile"]["Work experience"]["Publication"]
    assert [p["fields"]["Publisher or venue"]["check"] for p in pubs] == ["verified", "verified"]


def test_a_long_cv_sends_long_lists_to_calls_of_their_own(model, monkeypatch):
    monkeypatch.setattr(followups, "LONG_CV", 5)
    monkeypatch.setattr(followups, "OWN_LINES", 3)
    text = (["Sara Example", "PUBLICATIONS"] + [f"Example A. Study number {chr(65 + i)} of things. Sci Rep (2022)." for i in range(4)]
            + ["EXPERIENCE", "Lecturer, Example University", "Research assistant, Example Lab", "LANGUAGES", "Arabic"])
    scripted = Scripted(model)
    built = run(ProfileBuilder(model, scripted).build(b"", "cv.txt", as_of=AS_OF, text=lines(*text)))
    assert built["fixes"]["sections_own_call"] == ["Publication"]
    first = sorted((name, message.split("---\n")[0].split("\n\n")[1][:5]) for name, message in scripted.sent[:2])
    assert first == [("OwnPublication", "L002 "), ("ProfileAll", "L001 ")]  # roles stay in the main call
    assert sorted(built["fixes"]["sections_asked_again"]) == ["Languages", "Professional"]  # the main call left them empty


def test_lines_no_entry_took_get_a_second_look_with_the_list_sections(model):
    """Items under a heading that names the wrong section (projects under "papers") are
    left uncited by the first answer; the second look places them, and only those lines go."""
    text = ["Sara Example", "EXPERIENCE", "Lecturer, Example University, 2019-2023", "SELECTED PAPERS"] + [
        f"Funded study of road sensors in district {chr(65 + n)}, Example Fund" for n in range(10)]

    def answer(call, s):
        if s.name == "Professional" and call == "ProfileAll":
            return [{**blank(s), "job_title": "Lecturer", "lines": [[3, 3]]}]
        if s.name == "Project" and call.startswith("Place"):
            return [{**blank(s), "name": f"Funded study of road sensors in district {chr(65 + n)}", "lines": [[5 + n, 5 + n]]} for n in range(10)]
        return None

    scripted = Scripted(model, answer)
    built = run(ProfileBuilder(model, scripted).build(b"", "cv.txt", as_of=AS_OF, text=lines(*text)))
    assert built["fixes"]["second_look_calls"] >= 1 and built["fixes"]["second_look_found"] == 10
    projects = built["profile"]["Work experience"]["Project"]
    assert len(projects) == 10 and all(p["fields"]["Name"]["check"] == "verified" for p in projects)
    place = next(message for name, message in scripted.sent if name.startswith("Place"))
    assert "L003" not in place and "L005" in place  # a cited line is not sent again
    other = {n for e in built["profile"].get("Identity", {}).get("Other information", []) for n in e["lines"]}
    assert not other & set(range(5, 15))  # the projects no longer fall into other information


def test_a_second_look_folds_in_what_the_first_answer_already_holds(model):
    text = ["Sara Example", "PhD in Civil Engineering, Example University", "EDUCATION",
            "PhD in Civil Engineering", "Example University", "2010 - 2014"] + [f"Thesis chapter {chr(65 + n)} on road sensors and traffic" for n in range(6)]

    def answer(call, s):
        if s.name == "Degree":
            at = [[2, 2]] if call == "ProfileAll" else [[4, 6]]
            return [{**blank(s), "degree_title": "PhD in Civil Engineering", "institution": "Example University", "lines": at}]
        return None

    built = run(ProfileBuilder(model, Scripted(model, answer)).build(b"", "cv.txt", as_of=AS_OF, text=lines(*text)))
    assert built["fixes"]["second_look_found"] >= 1
    degrees = built["profile"]["Education"]["Degree"]
    assert len(degrees) == 1 and {4, 5, 6} <= set(degrees[0]["lines"])


def test_roles_with_no_level_ask_for_the_level_with_the_roles_lines(model):
    text = lines("Sara Example", "EXPERIENCE", "Lecturer, Example University, 2019-2023", "Analyst, Example Bank, 2015-2019")
    group = one_group(model.asked)
    prof = by_name(model, "Professional")
    data = {s.slug: [] if s.repeating else None for s in group.subs}
    data[prof.slug] = [{**blank(prof), "job_title": "Lecturer", "lines": [[3, 3]]}, {**blank(prof), "job_title": "Analyst", "lines": [[4, 4]]}]
    res = [CallResult(group.name, output=group.model.model_validate(data))]
    g, nums = followups.missing_level(res, [group], text)
    assert [s.name for s in g.subs] == ["Level"] and nums == [3, 4]


def test_a_failed_call_asks_nothing_more_and_is_recorded(model):
    async def failing(name, text, output_type, what):
        return CallResult(name, error="RateLimitError: gave up")

    failing.release = {}  # the seam's release, empty for a stand-in
    built = run(ProfileBuilder(model, failing).build(b"", "cv.txt", as_of=AS_OF, text=lines("Sara Example", "EXPERIENCE", "Lecturer")))
    assert [c["group"] for c in built["calls"]] == ["ProfileAll"] and built["calls"][0]["error"].startswith("RateLimitError")


def test_text_fields_leave_out_personal_lines(model):
    def answer(call, s):
        if s.name == "Headline":
            return {"about": [[1, 3]], "lines": [[1, 3]]}
        return None

    text = lines("Summary", "Marital status: married", "Led a team of 12")
    built = run(ProfileBuilder(model, Scripted(model, answer)).build(b"", "cv.txt", as_of=AS_OF, text=text))
    assert built["profile"]["Work experience"]["Headline"]["fields"]["About"]["value"] == "Summary\nLed a team of 12"
    assert any("personal facts" in w for w in built["text"]["warnings"])


def test_the_host_finish_fills_its_own_fields(model):
    def answer(call, s):
        if s.name == "Professional":
            return [{**blank(s), "job_title": "Clerk", "start_date": "2019-01", "end_date": "2020-06", "lines": [[2, 2]]}]
        return None

    seen = []

    def finish(profile, model_, today):
        seen.append(today)
        profile["Work experience"]["Experience"]["fields"]["Government experience (months)"] = {"value": 18, "check": "computed", "kind": "computed"}
        return ["host note"]

    text = lines("Sam Example", "Clerk, Example Authority, Jan 2019 - Jun 2020")
    built = run(ProfileBuilder(model, Scripted(model, answer), finish=finish).build(b"", "cv.txt", as_of=AS_OF, text=text))
    exp = built["profile"]["Work experience"]["Experience"]["fields"]
    assert exp["Total experience (months)"]["value"] == 18 and exp["Government experience (months)"]["value"] == 18
    assert seen == [AS_OF] and "host note" in built["text"]["warnings"]
