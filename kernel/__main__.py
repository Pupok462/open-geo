from __future__ import annotations

import argparse
import json
import sys

from kernel import collect, store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kernel", description="Iterative SEO semantic kernel.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Open the visual board")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8099)
    p_serve.add_argument("--open", action="store_true")

    p_start = sub.add_parser("start", help="Create a kernel from a URL")
    p_start.add_argument("--url", required=True)
    p_start.add_argument("--brand", default="")
    p_start.add_argument("--geo", default="ru")
    p_start.add_argument("--lang", default="ru")
    p_start.add_argument("--gate", choices=("human", "auto"), default="human")

    p_round = sub.add_parser("round", help="Collect the next batch")
    p_round.add_argument("--slug", required=True)
    p_round.add_argument("--n", type=int, default=12)

    p_show = sub.add_parser("show", help="Print the kernel JSON")
    p_show.add_argument("--slug", required=True)

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        from kernel.serve import run

        run(host=args.host, port=args.port, open_browser=args.open)
        return 0

    if args.cmd == "start":
        kernel = collect.start(args.url, brand=args.brand or None, geo=args.geo, language=args.lang, gate=args.gate)
        kernel = collect.round(kernel, n=12)
        print(json.dumps(_summary(kernel), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "round":
        kernel = store.load(args.slug)
        kernel = collect.round(kernel, n=args.n)
        print(json.dumps(_summary(kernel), ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "show":
        kernel = store.load(args.slug)
        sys.stdout.write(kernel.model_dump_json(indent=2))
        sys.stdout.write("\n")
        return 0

    return 1


def _summary(kernel) -> dict:
    return {
        "slug": kernel.slug,
        "brand": kernel.brand,
        "round": kernel.round,
        "gate": kernel.gate,
        "volume_available": kernel.volume_available,
        "inbox": len(kernel.by_status("inbox")),
        "accepted": len(kernel.by_status("accepted")),
        "rejected": len(kernel.by_status("rejected")),
        "deferred": len(kernel.by_status("deferred")),
        "board": f"http://127.0.0.1:8099/?slug={kernel.slug}",
    }


if __name__ == "__main__":
    raise SystemExit(main())
