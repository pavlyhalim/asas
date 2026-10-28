# asas-cv-profile

A CV read into your own profile model, where every value cites the lines it came
from and code checks it against them. You describe the profile in one YAML file in
your own words; the package reads the CV into numbered lines, has an asas-agent
release fill your sections, and settles the rest in code.

- **Lines first, no model.** Azure Document Intelligence reads a PDF (layout,
  reading order, two columns, scans, Arabic); asas-cv reads Word and plain text.
  The text becomes `L001 ...` lines, the addresses every value cites. A reader that
  waits on a service runs off the event loop.
- **The model reads, code checks.** One call fills the profile, each entry citing
  line ranges. Every value is then checked against its lines: names and titles by
  fuzzy match after Arabic folding, dates in however the CV writes them (every
  Arabic region's month names, Hijri dates in numbers in any order), numbers by what they say,
  phones as numbers. A match must also keep the value's numbers ("Level 4" is not
  "Level 5") and marks ("C++" is not "C#"), and one short or one Latin word is found
  as a word ("R" is not in "reports", "Java" is not "JavaScript"). A value the lines
  do not hold is kept and flagged, never dropped.
- **Asked again only where needed.** A list with a heading that came back empty,
  a level no role was given, runs of lines no entry took, and parts that cited
  lines the text lacks each get one short call with only their own lines.
- **Nothing the CV says is lost.** Lines no field took are kept as other
  information under the heading they sit under, each block named by kind; a block
  that only repeats what the profile holds (a bilingual CV's second copy) is left
  out, and the claim is checked in code first.

Table-less variant of the Asas host contract: no session, no `migrate`, no
`seed`, no `configure`; the package reads no settings, the command line does. The
upload page is an optional router. `import asas_cv_profile` loads neither the
Agents SDK nor the matching libraries.

## Five minutes

```
asas-cv-profile[docintel] @ git+https://github.com/wlootah-a11y/asas.git@asas-cv-profile/v0.1.0#subdirectory=packages/asas-cv-profile
```

`asas-agent` and `asas-cv` are required by name, as asas-audit requires
asas-tenancy: pin them beside it.

```python
from pathlib import Path
import asas_agent, asas_cv_profile

model = asas_cv_profile.load_model(Path("profile.yaml"))
asker = asas_cv_profile.Asker(
    asas_cv_profile.default_release("gpt-5.1"),          # the package's profile-builder agent
    provider=asas_agent.gateway_provider(api_key=key, base_url=url, timeout=240, max_retries=5),
    tokens_per_minute=100_000,                           # the key's limit; 0 for none
)
builder = asas_cv_profile.ProfileBuilder(model, asker, pdf=asas_cv_profile.LayoutReader(endpoint, di_key))

try:
    built = await builder.build(raw, "cv.pdf")
except asas_cv_profile.Refused as refused:
    refused.code  # document_too_little_text | document_not_a_cv | reader_unavailable | ...

built["profile"]["Work experience"]["Roles"][0]["fields"]["Job title"]
# {"value": "Senior Data Analyst", "kind": "copied", "check": "verified"}
```

A host that keeps its agents in a store reads the release with
`asas_agent.fetch_release` instead of `default_release`, and one that screens every
model call passes `run_model=asas_agent.GuardedModel(...)` instead of a provider.

## The profile model

```yaml
name: Candidate profile
sections:
  - name: Roles                    # your name for it; unique
    group: Work experience         # where the profile nests it (optional)
    kind: work                     # what the code knows it as (optional)
    list: true                     # one entry per item
    headings: [career]             # heading words beside the built-in ones (needs a kind)
    fields:
      - {name: Job title, type: string}
      - {name: Employer, type: string, role: employer}
      - {name: Start date, type: date, role: start}
      - {name: End date, type: date, role: end}
      - {name: Current, type: boolean, role: current}
      - {name: What they did, type: text}
      - {name: Seniority, type: enum, values: [Junior, Senior], infer: true}
      - {name: Months, type: number, computed: duration_months}
```

- **Types**: `string`, `url`, `phone`, `text` (cited as lines, copied from them by
  code), `date`, `year`, `number`, `boolean`, `enum` and `multi_enum` (`values`,
  or the CV's own words without them). `note` is shown to the model; `infer: true`
  lets a value be worked out rather than copied; `copied: false` marks a string
  chosen from a list you keep.
- **Kinds** (`asas_cv_profile.KINDS`): `work`, `work_level`, `education`,
  `scholarships`, `courses`, `certifications`, `licences`, `career_breaks`,
  `projects`, `publications`, `patents`, `talks`, `awards`, `memberships`,
  `volunteering`, `student_activities`, `skills`, `languages`,
  `other_information`. A kind brings its heading words, whether its entries carry
  date ranges, whether a long list of it gets calls of its own, whether a second
  look may put lines in it, and whether a bilingual CV's twins are folded.
- **Roles** (`ROLES`): a work section's `start`, `end`, `current`, `employer`,
  `skills_used`; education's `institution`, `level`, `graduation`; skills' `name`;
  other information's `topic`, `details`, `kind`.
- **Computed** (`COMPUTED`): `duration_months` and `date_precision` on a role,
  `total_months` and `gap_months` anywhere (overlapping roles counted once),
  `months_used` and `last_used` on a skill. `computed: host` is yours to fill in
  `finish(profile, model, as_of) -> warnings`.

`load_model` refuses an unknown type, kind, role or computed name, and a name used
twice, and says where.

## Command line

```bash
export OPENAI_API_KEY=... OPENAI_MODEL=gpt-5.1 OPENAI_BASE_URL=https://...   # as asas-agent's evals read a gateway
export AZURE_DI_ENDPOINT=... AZURE_DI_KEY=...                                 # Document Intelligence, for PDFs

asas-cv-profile schema  --profile-model profile.yaml                 # the calls it packs into
asas-cv-profile one     cv.pdf --profile-model profile.yaml --out runs/a
asas-cv-profile run     cvs/   --profile-model profile.yaml --out runs/a   # what is done is kept
asas-cv-profile recheck --profile-model profile.yaml --out runs/a          # current rules, no model call
asas-cv-profile other   runs/a/*/profile.json --profile-model profile.yaml # other information again
asas-cv-profile serve   --profile-model profile.yaml --out runs/a          # upload page, 127.0.0.1:8765
```

Options: `--finish module:function`, `--agents DIR` (your own profile-builder
folder), `--chat-completions` (a gateway without the Responses API),
`--tokens-per-minute`, `--parallel`, `--retries`, `--timeout`, `--split` (calls
under 90 properties each, Azure's strict-schema cap being 100), `--as-of`
(the day "present" counts to), `--force`. Each CV leaves `text.txt`,
`profile.json` (everything, the raw answers included) and `review.md` (what needs
a look first, then every field with its value, check and lines). The output folder
holds personal data and is made readable by its owner only.

## What it gets right, so you do not have to

- **Line ranges, not quotes.** The model cites `[first, last]` (SmartResume's
  index pointers): a ten-line description is two numbers, text fields are copied
  from the lines by code, and a citation can be checked.
- **A bad range does not sink an entry.** A range past the end is dropped and the
  rest checked; only the parts with no real line are asked again, in one call.
- **One call over a long list stops partway.** On a CV over 250 lines, long lists
  at the back get calls of their own, cut where items start.
- **A month the CV does not give** is cut to the year, and **a Hijri year copied as
  the date** ("1436" for 12-28-1436) becomes the Gregorian month the lines' Hijri date
  falls in, by hijridate, when only one reading fits (`was` keeps the model's).
- **Skills stay in the CV's words.** A reworded skill is set back to the list item
  it came from, and items the model left out of a skills list are added
  (Resume-Matcher's splitter, Apache-2.0); each skill records whether it came from
  a skills list or elsewhere.
- **A bilingual CV states everything twice.** Twins are found by record-linkage
  blocking: an Arabic and a Latin entry that keep the same years (and level), one
  to one in CV order, or two entries with the same names and dates. The Latin one
  is kept, with the Arabic names beside it.
- **Two posts at once are not two careers.** Totals, and each skill's months, are the
  union of the roles' months; asas-cv's own total sums them.
- **A bilingual CV's second skills list is not read twice.** An Arabic list splits as
  an English one does (on ، and ؛), but a skills line in a script the model read none of
  the skills in is the other copy and is left to other information.
- **Personal facts stay out.** Lines stating marital status, birth date, religion
  and the like are left out of every copied text and of other information.
- **Rate and concurrency are two limits.** A semaphore caps calls at once; a leaky
  bucket (aiolimiter) keeps tokens a minute under the key's limit, prompts counted
  with tiktoken; the OpenAI client retries throttled and failed calls. Both limits
  belong to the event loop they run in, and a host's second loop gets its own.
  tiktoken fetches its vocabulary once: a host with no way out seeds
  `TIKTOKEN_CACHE_DIR` in its image, or tokens are estimated from the text's length.
- **The same input gives the same output.** Headings are taken in the table's order,
  never a set's, and a recheck of a build changes nothing.

A date written `7/6/2011` counts as both 7 June and 6 July: the order differs from
country to country, and the lines alone cannot say. A phone number with no country
code is read as a UAE number.

## Surface

`load_model`, `parse_model`, `ProfileModel`, `Section`, `Spec`, `ModelError`,
`KINDS`, `ROLES`, `COMPUTED`, `TYPES`, `BUDGET`; `read_cv`, `Lines`,
`LayoutReader`, `Refused`, `CODES` (asas-cv's codes, then this package's);
`Asker`, `default_release`; `ProfileBuilder` (`build`, `recheck`, `other_again`;
`one_call=False` packs the sections into calls under `BUDGET`); the seams `Ask`
(with its `release`), `CallResult`, `PdfReader`, `Finish`; the output shapes `Built`,
`Entry`, `Cell`; `write_outputs`, `review`, `summary`; `upload_router` (the `serve`
extra; a refusal is a 422 whose `detail` holds its `code` and `message`).

## Not in scope

Mapping values to the host's lists (skills to a taxonomy, a company to a sector),
scoring or ranking, storing the CV, and the headshot (asas-cv has it).

## Developing

`pip install -e ../asas-agent -e ../asas-cv -e '.[dev]'` (what CI runs; add
`docintel` and `serve` to use them), then `pytest -q`. No network, no model, no real
CV: made-up documents, a made-up profile model and a scripted model.
