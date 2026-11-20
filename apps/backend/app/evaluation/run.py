"""Command line for the experiments (PRD §15.2). It talks to the running backend, which holds
the provider keys, the sandbox and the crew service:

    python -m app.evaluation.run list
    python -m app.evaluation.run --experiment E4 --repeats 3        # runs a sweep and waits
    python -m app.evaluation.run --experiment E5 --variants terse,strict --repeats 3
    python -m app.evaluation.run status
    python -m app.evaluation.run report                              # writes the dated report

Running it again continues where a stopped sweep left off: trials with a stored result are
skipped. The API token is read from the environment and is never printed.
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings


def client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        base_url=f"http://{settings.host}:{settings.port}/api/experiments",
        headers={"Authorization": f"Bearer {settings.api_token}"},
        timeout=60,
    )


def _check(response: httpx.Response) -> Any:
    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise SystemExit(f"{response.status_code}: {detail}")
    return response.json() if "json" in response.headers.get("content-type", "") else response.text


def show_list(http: httpx.Client) -> None:
    data = _check(http.get(""))
    apps = ", ".join(a["id"] for a in data["apps"])
    print(f"mission benchmark {data['benchmark_version']}: {apps}")
    for e in data["experiments"]:
        state = f"BLOCKED: {e['blocked']}" if e["blocked"] else "ready"
        conditions = ", ".join(c["id"] for c in e["conditions"]) or "-"
        print(f"{e['id']} {e['title']}: {state}\n    conditions: {conditions}")


def show_status(http: httpx.Client) -> list[dict[str, Any]]:
    sweeps = _check(http.get("/sweeps"))
    for s in sweeps:
        print(
            f"sweep {s['id']} {s['experiment']} {s['state']}: {s['done']}/{s['total']} trials "
            f"({s['skipped']} already stored)" + (f", now {s['current']}" if s["current"] else "")
        )
    if not sweeps:
        print("no sweeps in this backend session")
    return sweeps  # type: ignore[no-any-return]


def run_sweep(http: httpx.Client, args: argparse.Namespace) -> None:
    body: dict[str, Any] = {
        "repeats": args.repeats,
        "variants": [v for v in args.variants.split(",") if v],
    }
    if args.apps:
        body["apps"] = args.apps.split(",")
    if args.budget:
        body["budget_usd"] = args.budget
    sweep = _check(http.post(f"/{args.experiment}/run", json=body))
    print(f"sweep {sweep['id']}: {sweep['total']} trials to run, {sweep['skipped']} already stored")
    if args.no_wait:
        return
    last = ""
    try:
        while True:
            time.sleep(15)
            now = next((s for s in _check(http.get("/sweeps")) if s["id"] == sweep["id"]), None)
            if now is None or now["state"] != "running":
                break
            line = f"{now['done']}/{now['total']} {now['current'] or ''}"
            if line != last:
                print(line, flush=True)
                last = line
    except KeyboardInterrupt:
        print("\nleaving the sweep running; `status` shows it, or stop it from the app")
        return
    print(f"sweep {now['state'] if now else 'unknown'}")


def write_report(http: httpx.Client, out: Path | None) -> None:
    report = _check(http.get("/report"))
    text = report["markdown"]
    path = out or Path("docs") / "results" / f"experiments-{report['date']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"written to {path}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation.run")
    parser.add_argument(
        "command", nargs="?", choices=["run", "list", "status", "report"], default="run"
    )
    parser.add_argument("--experiment", help="E1 to E6")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--apps", default="", help="comma-separated mission app ids (default: all)")
    parser.add_argument("--variants", default="", help="E5: comma-separated variant ids")
    parser.add_argument("--budget", type=float, default=0, help="USD cap per trial")
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--out", type=Path, help="report file (default docs/results/...)")
    args = parser.parse_args(argv)
    try:
        with client() as http:
            if args.command == "list":
                show_list(http)
            elif args.command == "status":
                show_status(http)
            elif args.command == "report":
                write_report(http, args.out)
            else:
                if not args.experiment:
                    raise SystemExit("--experiment is required (see `list`)")
                args.experiment = args.experiment.upper()
                run_sweep(http, args)
    except httpx.ConnectError:
        raise SystemExit("the backend is not running; run `npm run dev:backend`") from None


if __name__ == "__main__":
    sys.exit(main())
