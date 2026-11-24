#!/usr/bin/env python3
"""Evaluate every Prometheus panel query of a PMM dashboard against a live PMM and report empty panels.

Usage: PMM_URL=https://<pmm> PMM_PASS=<admin password> panelcheck.py <dashboard uid> [var=value ...]
Variables given on the command line are forced, like var-x= in a URL; the rest are resolved
from the dashboard's own variable queries, in order, the way Grafana does.
Each panel is reported OK, PARTIAL (some targets empty), EMPTY or ERROR. VERBOSE=1 prints the empty targets.
"""
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ["PMM_URL"].rstrip("/")
AUTH = "Basic " + base64.b64encode(f"admin:{os.environ['PMM_PASS']}".encode()).decode()
CTX = ssl._create_unverified_context()
RANGE_S = int(os.environ.get("RANGE_S", "900"))
STEP = os.environ.get("STEP", "30")
BUILTIN = {"__interval": "1m", "__rate_interval": "2m", "interval": "1m", "__range": f"{RANGE_S}s",
           "__range_s": str(RANGE_S), "__interval_ms": "60000", "__auto_interval_interval": "1m"}
SKIP_TYPES = {"row", "text", "news", "dashlist", "welcome", "pmm-qan-app-panel", "pmm-update-panel"}


def get(path, params=None):
    if params:
        path += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(URL + path, headers={"Authorization": AUTH})
    with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
        return json.load(r)


def prom(path, params):
    try:
        d = get("/prometheus/api/v1/" + path, params)
    except urllib.error.HTTPError as e:
        return None, e.read().decode()[:300]
    if d.get("status") != "success":
        return None, d.get("error", "?")
    return d["data"]["result"], None


def interp(expr, vals):
    def fmt(name):
        v = vals.get(name, BUILTIN.get(name))
        if v is None:
            return None
        if isinstance(v, list):
            return "(" + "|".join(v) + ")" if len(v) > 1 else v[0]
        return v
    expr = re.sub(r"\$\{(\w+)(?::\w+)?\}", lambda m: fmt(m[1]) or m[0], expr)
    expr = re.sub(r"\[\[(\w+)\]\]", lambda m: fmt(m[1]) or m[0], expr)
    return re.sub(r"\$(\w+)", lambda m: fmt(m[1]) or m[0], expr)


def var_values(v, vals, now):
    q = v.get("query")
    if isinstance(q, dict):
        q = q.get("query", "")
    q = interp(q or "", vals)
    out = []
    m = re.match(r"^\s*label_values\((.*),\s*(\w+)\s*\)\s*$", q, re.S)
    m2 = re.match(r"^\s*label_values\(\s*(\w+)\s*\)\s*$", q)
    m3 = re.match(r"^\s*query_result\((.*)\)\s*$", q, re.S)
    if m:
        res, _ = prom("query", {"query": f"group by ({m[2]}) (last_over_time(({m[1]})[1h]))", "time": now})
        out = sorted({r["metric"].get(m[2], "") for r in res or []} - {""})
    elif m2:
        res, _ = prom("query", {"query": f"group by ({m2[1]}) ({{{m2[1]}!=\"\"}})", "time": now})
        out = sorted({r["metric"].get(m2[1], "") for r in res or []} - {""})
    elif m3:
        res, _ = prom("query", {"query": m3[1], "time": now})
        for r in res or []:
            lab = ",".join(f'{k}="{val}"' for k, val in r["metric"].items() if k != "__name__")
            out.append(f'{r["metric"].get("__name__", "")}{{{lab}}} {r["value"][1]} {int(float(r["value"][0]) * 1000)}')
    rx = v.get("regex")
    if rx and out:
        rx = rx.strip("/")
        out = [mm.group(1) if mm.groups() else s for s in out if (mm := re.search(rx, s))]
    return out


def resolve(dash, forced, now):
    vals = {}
    for v in dash.get("templating", {}).get("list", []):
        n, t = v["name"], v.get("type")
        if n in forced:
            vals[n] = forced[n]
        elif t == "interval":
            vals[n] = "1m"
        elif t in ("constant", "textbox"):
            vals[n] = str(v.get("query", ""))
        elif t == "custom":
            cur = (v.get("current") or {}).get("value")
            vals[n] = cur if cur not in (None, "$__all") else ".*"
        elif t == "query":
            opts = var_values(v, vals, now)
            if v.get("includeAll") and (not opts or (v.get("current") or {}).get("value") in ("$__all", ["$__all"])):
                vals[n] = v.get("allValue") or (opts if opts else ".*")
            elif opts:
                vals[n] = opts[:1] if v.get("multi") else opts[0]
            else:
                vals[n] = ""
    return vals


def panels(ps):
    for p in ps:
        yield p
        yield from panels(p.get("panels", []))


def is_prom(ds):
    if ds is None:
        return True
    if isinstance(ds, str):
        return "clickhouse" not in ds.lower() and "-- " not in ds
    return ds.get("type") in (None, "prometheus") or ds.get("uid") in ("PA58DA793C7250F1B", "Metrics")


def check(uid, forced):
    dash = get(f"/graph/api/dashboards/uid/{uid}")["dashboard"]
    now = time.time()
    vals = resolve(dash, forced, now)
    rows = []
    for p in panels(dash.get("panels", [])):
        if p.get("type") in SKIP_TYPES or not p.get("targets"):
            continue
        if not is_prom(p.get("datasource")):
            rows.append((p.get("id"), p.get("type"), p.get("title"), "SKIP(non-prom)", []))
            continue
        empty, errs, nonempty = [], [], 0
        for t in p["targets"]:
            if t.get("hide") or not t.get("expr") or not is_prom(t.get("datasource", p.get("datasource"))):
                continue
            e = interp(t["expr"], vals)
            if t.get("instant") and not t.get("range"):
                res, err = prom("query", {"query": e, "time": now})
            else:
                res, err = prom("query_range", {"query": e, "start": now - RANGE_S, "end": now, "step": STEP})
            if err:
                errs.append((t.get("refId"), err))
            elif res:
                nonempty += 1
            else:
                empty.append((t.get("refId"), e))
        if not (empty or errs or nonempty):
            continue
        if nonempty and not empty and not errs:
            state = "OK"
        else:
            state = "PARTIAL" if nonempty else ("ERROR" if errs else "EMPTY")
        rows.append((p.get("id"), p.get("type"), p.get("title"), state, empty + errs))
    return dash.get("title"), rows


def main():
    uid, forced = sys.argv[1], dict(a.split("=", 1) for a in sys.argv[2:])
    title, rows = check(uid, forced)
    cnt = {}
    for r in rows:
        cnt[r[3]] = cnt.get(r[3], 0) + 1
    print(f"## {title} ({uid}) {forced} -> " + ", ".join(f"{k}={v}" for k, v in sorted(cnt.items())))
    for pid, typ, ttl, st, det in rows:
        if st != "OK":
            print(f"  [{st}] #{pid} {typ}: {ttl}")
            if os.environ.get("VERBOSE"):
                for d in det:
                    print(f"        {d[0]}: {d[1][:220]}")
    sys.exit(1 if any(r[3] in ("EMPTY", "PARTIAL", "ERROR") for r in rows) else 0)


if __name__ == "__main__":
    main()
