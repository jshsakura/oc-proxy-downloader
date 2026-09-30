"""Explicit, single-attempt live checks; no production DB or queue mutations.

Run with an isolated CONFIG_PATH and a JSON export of collected links. Reports
never include source URLs, cookies or signed file URLs. Logs stay in the private
output tree. A parse result and a partial transfer are never called complete.
"""

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from core.hoster_parsers import parse_special_hoster_sync
from core.error_messages import classify_error


TREE_LIMIT = 4 * 1024**3
FILE_LIMIT = 1024**3


class TreeBudget:
    def __init__(self, root, reserved_bytes=0):
        self.lock = threading.Lock()
        usage = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
        self.remaining = TREE_LIMIT - usage - reserved_bytes

    def claim(self, amount):
        with self.lock:
            if amount > self.remaining:
                raise ValueError('Aggregate validation tree reached its 4 GiB limit')
            self.remaining -= amount


def verify(row, output, prepared=None, gate=None, budget=None):
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    identifier = str(int(row["id"]))
    result = {
        "source_id": row["id"], "host": urlparse(row["download_url"]).hostname,
        "collected_at": row["created_at"], "checked_at": datetime.now(timezone.utc).isoformat(),
        "stage": "parse", "outcome": "failed", "bytes": 0, "file_requests": 0,
        "automatic_retries": 0,
    }
    part = output / f"{identifier}.part"
    if part.exists() or (output / f"{identifier}.bin").exists():
        raise ValueError("This source already has a validation file; do not silently re-request it")
    start = time.monotonic()
    with (output / f"{identifier}.log").open("x") as log:
        with (contextlib.redirect_stdout(log) if prepared is None else contextlib.nullcontext()), (contextlib.redirect_stderr(log) if prepared is None else contextlib.nullcontext()):
            try:
                parsed = prepared or parse_special_hoster_sync(row["download_url"])
                private = output / f"{identifier}-session-private.json"
                private.write_text(json.dumps(parsed, ensure_ascii=False, indent=2))
                private.chmod(0o600)
                result["parse_succeeded"] = bool(parsed.get("download_link"))
                if not result["parse_succeeded"]:
                    raise ValueError("Parser returned no file URL")
                result["stage"] = "transfer"
                with requests.Session() as session:
                    session.max_redirects = 5
                    session.cookies.update(parsed.get("cookies") or {})
                    headers = {
                        "User-Agent": parsed.get("user_agent") or "Mozilla/5.0",
                        "Referer": parsed.get("referer") or row["download_url"],
                        "Accept-Encoding": "identity",
                    }
                    result["file_requests"] = 1
                    if gate:
                        gate.wait(timeout=30)
                    result["transfer_started_at"] = datetime.now(timezone.utc).isoformat()
                    with session.get(parsed["download_link"], headers=headers,
                                     stream=True, timeout=(60, 120)) as response:
                        result["http_status"] = response.status_code
                        result["content_type"] = response.headers.get("Content-Type", "")
                        result["redirects"] = len(response.history)
                        if response.status_code != 200:
                            # Do not publish the raw body; it may contain signed URLs.
                            preview = response.raw.read(2048)
                            result["storage_unavailable"] = b"the link is not available at this time" in preview.lower()
                            raise ValueError(f"File response HTTP {response.status_code}")
                        if "text/html" in result["content_type"].lower() or "application/json" in result["content_type"].lower():
                            raise ValueError("File endpoint returned a page or API response")
                        expected = int(response.headers.get("Content-Length") or 0)
                        result["expected_bytes"] = expected
                        usage = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
                        remaining = min(FILE_LIMIT, TREE_LIMIT - usage)
                        if remaining <= 0 or expected > remaining:
                            result["outcome"] = "size_budget_exceeded"
                            raise ValueError("Validation file exceeds the remaining byte budget")
                        digest = hashlib.sha256()
                        head = b""
                        with part.open("xb") as file:
                            for chunk in response.iter_content(65536):
                                if not chunk:
                                    continue
                                if result["bytes"] + len(chunk) > remaining:
                                    result["outcome"] = "partial_budget_exceeded"
                                    raise ValueError("Transfer stopped at its byte budget")
                                if not head:
                                    head = chunk[:256]
                                    clean = head.lstrip(b"\xef\xbb\xbf\x00\t\r\n ").lower()
                                    if clean.startswith((b"<!doctype", b"<html", b"<?xml", b"<head", b"<script", b'{"error"')):
                                        raise ValueError("Body is an HTML/XML/API page despite its content type")
                                if budget:
                                    budget.claim(len(chunk))
                                file.write(chunk)
                                digest.update(chunk)
                                result["bytes"] += len(chunk)
                        if not result["bytes"] or (expected and expected != result["bytes"]):
                            raise ValueError("File length is empty or does not match Content-Length")
                        result["head_hex"] = head[:8].hex()
                        result["sha256"] = digest.hexdigest()
                        result["outcome"] = "complete_file" if expected else "stream_finished_size_unconfirmed"
                        if expected:
                            part.rename(output / f"{identifier}.bin")
            except Exception as exc:
                # Error text from a parser may contain tokens; keep it in the
                # private log and expose only the class/stage in the report.
                print(type(exc).__name__, str(exc), file=log)
                result["error_type"] = type(exc).__name__
                verdict = classify_error("다운로드" if result["stage"] == "transfer" else "파싱", str(exc))
                result["failure_kind"] = verdict.kind
                result["reason"] = verdict.summary
                result["deletion_confirmed"] = False
                result["parse_succeeded"] = result.get("parse_succeeded", False)
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    (output / f"{identifier}.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links", type=Path, required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--id", type=int)
    selection.add_argument("--parallel-ids", help="Explicit comma-separated IDs, at most three; parse serially first")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tree-root", type=Path, help="Aggregate evidence tree shared by every host check")
    parser.add_argument("--reserved-bytes", type=int, default=0, help="Bytes already retained in other validation trees")
    args = parser.parse_args()
    rows = json.loads(args.links.read_text())
    budget = TreeBudget(args.tree_root or args.output, args.reserved_bytes)
    if args.id:
        row = next(row for row in rows if row["id"] == args.id)
        verify(row, args.output, budget=budget)
    else:
        from core.host_policy import host_key_for_url
        ids = [int(value) for value in args.parallel_ids.split(",")]
        if not 2 <= len(ids) <= 3 or len(set(ids)) != len(ids):
            raise ValueError("Select two or three distinct source IDs")
        selected = [next(row for row in rows if row["id"] == identifier) for identifier in ids]
        hosts = {host_key_for_url(row["download_url"]) for row in selected}
        if len(hosts) != 1:
            raise ValueError("Parallel verification must concern one canonical host")
        args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        previous = [json.loads(p.read_text()) for p in args.output.glob("*.json")]
        if not any(r.get("outcome") == "complete_file" and host_key_for_url("https://" + r.get("host", "")) in hosts for r in previous):
            raise ValueError("A complete single-file check is required before a parallel check")
        prepared = []
        for row in selected:
            # Prepare URLs sequentially. Never start a simultaneous captcha/
            # metadata batch, or retry a failed preparation in this command.
            with (args.output / f'{row["id"]}-prepare.log').open("x") as log:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    try:
                        parsed = parse_special_hoster_sync(row["download_url"])
                        prepared.append((row, parsed))
                    except Exception as exc:
                        print(type(exc).__name__, str(exc))
                        report = {"source_id": row["id"], "host": urlparse(row["download_url"]).hostname,
                                  "stage": "parse", "outcome": "failed", "bytes": 0,
                                  "automatic_retries": 0, "file_requests": 0}
                        (args.output / f'{row["id"]}.json').write_text(json.dumps(report, indent=2))
                        break  # a refusal stops preparation of more host links
            time.sleep(2)
        if len(prepared) < 2:
            print(json.dumps({"parallel_checked": False, "prepared_files": len(prepared)}))
        else:
            # Conservatively reserve each transfer's entire per-file budget,
            # so parallel writes cannot race the aggregate check.
            usage = sum(p.stat().st_size for p in args.output.rglob("*") if p.is_file())
            if usage + len(prepared) * FILE_LIMIT > TREE_LIMIT:
                raise ValueError("Parallel checks would exceed the aggregate 4 GiB reservation")
            gate = threading.Barrier(len(prepared))
            with ThreadPoolExecutor(max_workers=len(prepared)) as pool:
                futures = [pool.submit(verify, row, args.output, parsed, gate, budget) for row, parsed in prepared]
                reports = [future.result() for future in futures]
            print(json.dumps({"parallel_checked": True, "files": len(reports),
                              "complete_files": sum(r["outcome"] == "complete_file" for r in reports)}))
