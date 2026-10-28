"""``asas-cv-profile``: CVs read into a profile model from the command line.

    asas-cv-profile schema  --profile-model profile.yaml       the calls the model packs into
    asas-cv-profile one     CV --profile-model ... --out DIR    one CV
    asas-cv-profile run     CVS_DIR --profile-model ... --out DIR   every PDF, .docx, .txt and .md in a folder
    asas-cv-profile recheck --profile-model ... --out DIR       saved results checked again, no model call
    asas-cv-profile other   PROFILE_JSON... --profile-model ... other information again, one call each
    asas-cv-profile serve   --profile-model ... --out DIR       the upload page on 127.0.0.1

The model is reached as asas-agent's evals reach a gateway: ``OPENAI_API_KEY``,
``OPENAI_MODEL`` and ``OPENAI_BASE_URL`` (always set it: unset means api.openai.com);
``--chat-completions`` for a gateway that serves chat completions only. PDFs are read
by Document Intelligence: ``AZURE_DI_ENDPOINT`` and ``AZURE_DI_KEY``. Keys are never
printed.

A CV is personal data: the output folder holds the person's name and text, is made
readable by its owner only, and is kept like the CVs themselves.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import os
import re
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from . import __version__
from .build import ProfileBuilder
from .calls import AGENTS, Asker, default_release
from .lines import LayoutReader, Refused
from .model import BUDGET, ModelError, load_model, one_group, pack
from .report import summary, write_outputs

SUFFIXES = (".pdf", ".docx", ".txt", ".md")


def _hook(reference: str):
    module, _, name = reference.partition(":")
    if not module or not name:
        raise argparse.ArgumentTypeError(f"expected module:function, got {reference!r}")
    return getattr(importlib.import_module(module), name)


def _out(path: Path) -> Path:
    out = path.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    return out


def _stem(path: Path) -> str:
    return re.sub(r"[^\w.-]+", "_", path.stem)[:80] or "cv"


def _builder(args, *, one_call: bool | None = None) -> ProfileBuilder:
    from asas_agent import (  # the settings asas-agent reads a gateway from
        GATEWAY_KEYS,
        gateway_provider,
    )

    key, model, url = (os.environ.get(k) for k in GATEWAY_KEYS)
    if not (key and model and url):
        raise SystemExit(f"asas-cv-profile: set {', '.join(GATEWAY_KEYS)}")
    provider = gateway_provider(api_key=key, base_url=url, timeout=args.timeout, max_retries=args.retries,
                                use_responses=not args.chat_completions)
    asker = Asker(default_release(model, args.agents), provider=provider, parallel=args.parallel,
                  tokens_per_minute=args.tokens_per_minute)
    endpoint, di_key = os.environ.get("AZURE_DI_ENDPOINT"), os.environ.get("AZURE_DI_KEY")
    pdf = LayoutReader(endpoint, di_key) if endpoint and di_key else None
    return ProfileBuilder(args.model, asker, pdf=pdf, finish=args.finish,
                          one_call=not args.split if one_call is None else one_call)


async def _one(builder: ProfileBuilder, path: Path, out: Path, as_of: date | None) -> Mapping[str, Any]:
    folder = out / _stem(path)
    try:
        built = await builder.build(path.read_bytes(), path.name, as_of=as_of)
    except Refused as exc:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "refused.txt").write_text(f"{exc.code}: {exc}\n", encoding="utf-8")
        return {"file": path.name, "refused": exc.code}
    write_outputs(built, folder)
    return built


def cmd_schema(args) -> int:
    groups = [one_group(args.model.asked)] if not args.split else pack(args.model.asked)
    for g in groups:
        flag = "" if g.properties <= BUDGET else f"  (over {BUDGET})"
        print(f"{g.name}: {g.properties} properties{flag}; " + "; ".join(s.name for s in g.subs))
    return 0


def cmd_one(args) -> int:
    out = _out(args.out)
    built = asyncio.run(_one(_builder(args), args.file, out, args.as_of))
    if "refused" in built:
        print(f"asas-cv-profile: refused: {built['refused']}", file=sys.stderr)
        return 1
    print(f"{out / _stem(args.file)}: checks {built['checks']}")
    return 0


def cmd_run(args) -> int:
    out = _out(args.out)
    files = sorted(p for p in args.cvs.expanduser().iterdir() if p.suffix.lower() in SUFFIXES)
    builder = _builder(args)

    async def every() -> list[Mapping[str, Any]]:  # one event loop for the run: the model client belongs to the loop it was made in
        rows: list[Mapping[str, Any]] = []
        for i, path in enumerate(files, 1):
            done, refused = out / _stem(path) / "profile.json", out / _stem(path) / "refused.txt"
            failed = done.exists() and any(c.get("error") for c in json.loads(done.read_text()).get("calls", []))
            if refused.exists() and refused.read_text().startswith("reader_unavailable"):
                refused.unlink()  # the reader was down last time, not the file at fault
            built: Mapping[str, Any]
            if refused.exists() and not args.force:
                built = {"file": path.name, "refused": refused.read_text().split(":")[0]}
                print(f"[{i}/{len(files)}] {path.name}: refused before ({built['refused']}), kept")
            elif done.exists() and not args.force and not failed:
                built = json.loads(done.read_text())
                print(f"[{i}/{len(files)}] {path.name}: done before, kept")
            else:
                print(f"[{i}/{len(files)}] {path.name} ...", flush=True)
                built = await _one(builder, path, out, args.as_of)
                print(f"  refused: {built['refused']}" if "refused" in built
                      else f"  {built['text']['reader']}, {len(built['text']['lines'])} lines, checks {built['checks']}", flush=True)
            rows.append(built)
        return rows

    rows = asyncio.run(every())
    (out / "summary.md").write_text(summary(rows), encoding="utf-8")
    print(f"\nSummary: {out / 'summary.md'}")
    return 0


def cmd_recheck(args) -> int:
    out = _out(args.out)
    builder = ProfileBuilder(args.model, None, finish=args.finish)  # no model call
    rows: list[Mapping[str, Any]] = []
    for done in sorted(out.glob("*/profile.json")):
        built = json.loads(done.read_text())
        before = dict(built.get("checks", {}))
        built = builder.recheck(built)
        write_outputs(built, done.parent)
        print(f"{done.parent.name}: {before} -> {built['checks']}")
        rows.append(built)
    rows += [{"file": r.parent.name, "refused": r.read_text().split(":")[0]} for r in sorted(out.glob("*/refused.txt"))]
    (out / "summary.md").write_text(summary(rows), encoding="utf-8")
    print(f"\nSummary: {out / 'summary.md'}")
    return 0


def cmd_other(args) -> int:
    builder = _builder(args)

    async def each() -> None:  # one event loop for every call: the model client is bound to the loop it first ran in
        for done in args.profiles:
            built = json.loads(done.read_text())
            before = built.get("other_information")
            built = await builder.other_again(built)
            write_outputs(built, done.parent)
            print(f"{done.parent.name}: {before} -> {built['other_information']}, repeats left out {len(built['fixes']['other_repeats'])}")

    asyncio.run(each())
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .web import local_app, upload_router

    out = _out(args.out)
    app = local_app(upload_router(_builder(args, one_call=True), out, packed=_builder(args, one_call=False)))
    print(f"Upload page: http://127.0.0.1:{args.port}  (output in {out})")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="asas-cv-profile", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"asas-cv-profile {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile-model", dest="model_path", type=Path, required=True, help="the profile model (YAML)")
    common.add_argument("--finish", type=_hook, help="module:function, the host's last step (fills computed: host fields)")
    calls = argparse.ArgumentParser(add_help=False)
    calls.add_argument("--agents", type=Path, default=AGENTS, help="the agents directory (default: the package's profile-builder)")
    calls.add_argument("--chat-completions", action="store_true", help="the gateway serves chat completions only, not the Responses API")
    calls.add_argument("--timeout", type=float, default=240, help="seconds per model call")
    calls.add_argument("--retries", type=int, default=5, help="client retries of a throttled or failed call")
    calls.add_argument("--parallel", type=int, default=3, help="model calls at once across a CV")
    calls.add_argument("--tokens-per-minute", type=int, default=0, help="the key's limit; 0 for none")
    calls.add_argument("--split", action="store_true", help=f"calls under {BUDGET} properties each instead of one")
    calls.add_argument("--as-of", type=date.fromisoformat, help="the day 'present' counts to (YYYY-MM-DD); default today")
    commands = parser.add_subparsers(dest="command", required=True)
    schema = commands.add_parser("schema", parents=[common], help="the calls the profile model packs into")
    schema.add_argument("--split", action="store_true")
    schema.set_defaults(handler=cmd_schema)
    one = commands.add_parser("one", parents=[common, calls], help="one CV")
    one.add_argument("file", type=Path)
    one.add_argument("--out", type=Path, required=True)
    one.set_defaults(handler=cmd_one)
    run = commands.add_parser("run", parents=[common, calls], help="every CV in a folder; what is done is kept")
    run.add_argument("cvs", type=Path)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--force", action="store_true", help="read every CV again")
    run.set_defaults(handler=cmd_run)
    recheck = commands.add_parser("recheck", parents=[common], help="saved results checked again with the current rules, no model call")
    recheck.add_argument("--out", type=Path, required=True)
    recheck.set_defaults(handler=cmd_recheck)
    other = commands.add_parser("other", parents=[common, calls], help="other information made again for saved profiles")
    other.add_argument("profiles", type=Path, nargs="+")
    other.set_defaults(handler=cmd_other)
    serve = commands.add_parser("serve", parents=[common, calls], help="the upload page on 127.0.0.1")
    serve.add_argument("--out", type=Path, required=True)
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(handler=cmd_serve)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="  %(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stderr)
    for noisy in ("httpx", "httpx2", "openai", "azure", "agents"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        args.model = load_model(args.model_path)
        return args.handler(args)
    except (ModelError, FileNotFoundError) as error:
        print(f"asas-cv-profile: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
