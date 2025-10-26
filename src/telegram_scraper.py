import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import AsyncIterator, Iterable, Optional, Sequence, Set, List, Tuple

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.errors.rpcerrorlist import MsgIdInvalidError, FloodWaitError
from telethon.tl.functions.messages import GetDiscussionMessageRequest
from telethon.tl.custom.message import Message
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer


@dataclass
class ScrapedMessage:
    id: int
    date: Optional[str]  # ISO format
    message: Optional[str]
    sender_id: Optional[int]
    views: Optional[int]
    forwards: Optional[int]
    replies: Optional[int]
    url: Optional[str]


def to_iso(dt: datetime) -> str:
    return dt.replace(tzinfo=None).isoformat()


async def iter_messages(
    client: TelegramClient,
    entity: str,
    limit: Optional[int] = None,
    offset_date: Optional[datetime] = None,
) -> AsyncIterator[Message]:
    async for msg in client.iter_messages(entity, limit=limit, offset_date=offset_date):
        yield msg


def message_to_record(msg: Message, channel_username: str) -> ScrapedMessage:
    return ScrapedMessage(
        id=msg.id,
        date=to_iso(msg.date) if msg.date else None,
        message=msg.message,
        sender_id=getattr(msg.sender_id, 'value', msg.sender_id) if hasattr(msg, 'sender_id') else None,
        views=getattr(msg, 'views', None),
        forwards=getattr(msg, 'forwards', None),
        replies=(msg.replies.replies if getattr(msg, 'replies', None) else None),
        url=f"https://t.me/{channel_username}/{msg.id}" if channel_username else None,
    )


async def ensure_login(client: TelegramClient, phone: Optional[str] = None, twofa_password: Optional[str] = None):
    # Connect and log in, prompting interactively if needed
    await client.connect()
    if not await client.is_user_authorized():
        if not phone:
            phone = input("Enter your phone number (with country code): ")
        await client.send_code_request(phone)
        code = input("Enter the login code you received: ")
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            if twofa_password is None:
                twofa_password = input("Two-step verification enabled. Enter your password: ")
            await client.sign_in(password=twofa_password)


async def scrape_channel(
    channel: str,
    output: str,
    limit: Optional[int] = None,
    offset_date: Optional[str] = None,  # deprecated in favor of start_date
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    append: bool = False,
    session_name: str = "telegram",
    phone: Optional[str] = None,
    twofa_password: Optional[str] = None,
):
    load_dotenv()
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_name = os.getenv("TELEGRAM_SESSION_NAME", session_name)

    if not api_id or not api_hash:
        raise RuntimeError("Missing TELEGRAM_API_ID/TELEGRAM_API_HASH in environment. See .env.example")

    # Some providers store api_id as string; Telethon expects int
    try:
        api_id_int = int(api_id)
    except Exception as e:
        raise RuntimeError("TELEGRAM_API_ID must be an integer") from e

    client = TelegramClient(session_name, api_id_int, api_hash)

    # Parse date filters
    parsed_start = None
    parsed_end = None
    if start_date:
        parsed_start = datetime.fromisoformat(start_date)
    elif offset_date:  # backward compatibility
        parsed_start = datetime.fromisoformat(offset_date)
    if end_date:
        parsed_end = datetime.fromisoformat(end_date)

    await ensure_login(client, phone=phone, twofa_password=twofa_password)

    # Determine output format based on extension
    ext = os.path.splitext(output)[1].lower()
    is_jsonl = ext in (".jsonl", ".ndjson")
    is_csv = ext == ".csv"

    if not (is_jsonl or is_csv):
        raise ValueError("Output file must end with .jsonl or .csv")

    # Prepare output writers
    csv_file = None
    csv_writer = None
    jsonl_file = None
    if is_csv:
        import csv
        mode = "a" if append else "w"
        csv_file = open(output, mode, newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "id",
                "date",
                "message",
                "sender_id",
                "views",
                "forwards",
                "replies",
                "url",
            ],
        )
        # Write header if not appending, or file is empty
        need_header = True
        try:
            if append and os.path.exists(output) and os.path.getsize(output) > 0:
                need_header = False
        except Exception:
            pass
        if need_header:
            csv_writer.writeheader()
    elif is_jsonl:
        # Open once; append or overwrite
        mode = "a" if append else "w"
        jsonl_file = open(output, mode, encoding="utf-8")

    written = 0
    try:
        async for msg in iter_messages(client, channel, limit=None, offset_date=None):
            # Telethon returns tz-aware datetimes; normalize for comparison
            msg_dt = msg.date
            if msg_dt is not None:
                msg_dt = msg_dt.replace(tzinfo=None)

            # Date range filter: include if within [parsed_start, parsed_end] (inclusive)
            if parsed_start and msg_dt and msg_dt < parsed_start:
                # Since we're iterating newest-first, once older than start we can stop
                break
            if parsed_end and msg_dt and msg_dt > parsed_end:
                continue

            rec = message_to_record(msg, channel_username=channel.lstrip("@"))
            if is_jsonl and jsonl_file is not None:
                jsonl_file.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
            else:
                csv_writer.writerow(asdict(rec))  # type: ignore
            written += 1
            if limit is not None and written >= limit:
                break
    finally:
        if csv_file:
            csv_file.close()
        if jsonl_file:
            jsonl_file.close()
        await client.disconnect()

    return written


async def fetch_replies(
    channel: str,
    parent_ids: Sequence[int],
    output_csv: str,
    append: bool = False,
    session_name: str = "telegram",
    phone: Optional[str] = None,
    twofa_password: Optional[str] = None,
    concurrency: int = 5,
    existing_pairs: Optional[Set[Tuple[int, int]]] = None,
):
    load_dotenv()
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_name = os.getenv("TELEGRAM_SESSION_NAME", session_name)

    if not api_id or not api_hash:
        raise RuntimeError("Missing TELEGRAM_API_ID/TELEGRAM_API_HASH in environment. See .env.example")
    client = TelegramClient(session_name, int(api_id), api_hash)
    await ensure_login(client, phone=phone, twofa_password=twofa_password)

    import csv

    # Rate limiting counters
    flood_hits = 0
    flood_wait_seconds = 0

    analyzer = SentimentIntensityAnalyzer()
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    mode = "a" if append else "w"
    with open(output_csv, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["parent_id", "id", "date", "message", "sender_id", "sentiment_compound", "url"],
        )
        # Write header only if not appending or file empty
        need_header = True
        try:
            if append and os.path.exists(output_csv) and os.path.getsize(output_csv) > 0:
                need_header = False
        except Exception:
            pass
        if need_header:
            writer.writeheader()

        write_lock = asyncio.Lock()
        sem = asyncio.Semaphore(max(1, int(concurrency)))

        async def handle_parent(pid: int) -> List[dict]:
            rows: List[dict] = []
            # First try replies within the same channel (works for groups/supergroups)
            attempts = 0
            while attempts < 3:
                try:
                    async for reply in client.iter_messages(channel, reply_to=pid):
                        dt = reply.date.replace(tzinfo=None) if reply.date else None
                        url = f"https://t.me/{channel.lstrip('@')}/{reply.id}" if reply.id else None
                        text = reply.message or ""
                        sent = analyzer.polarity_scores(text).get("compound")
                        rows.append(
                            {
                                "parent_id": pid,
                                "id": reply.id,
                                "date": to_iso(dt) if dt else None,
                                "message": text,
                                "sender_id": getattr(reply, "sender_id", None),
                                "sentiment_compound": sent,
                                "url": url,
                            }
                        )
                    break
                except FloodWaitError as e:
                    secs = int(getattr(e, 'seconds', 5))
                    flood_hits += 1
                    flood_wait_seconds += secs
                    print(f"[rate-limit] FloodWait while scanning replies in-channel for parent {pid}; waiting {secs}s", flush=True)
                    await asyncio.sleep(secs + 1)
                    attempts += 1
                    continue
                except MsgIdInvalidError:
                    # Likely a channel with a linked discussion group; fall back below
                    rows.clear()
                    break
                except Exception:
                    break

            if rows:
                return rows

            # Fallback: for channels with comments in a linked discussion group
            try:
                res = await client(GetDiscussionMessageRequest(peer=channel, msg_id=pid))
            except Exception:
                # No discussion thread found or not accessible
                return rows

            # Identify the discussion chat and the root message id in that chat
            disc_chat = None
            if getattr(res, "chats", None):
                # Prefer the first chat returned as the discussion chat
                disc_chat = res.chats[0]

            disc_root_id = None
            for m in getattr(res, "messages", []) or []:
                try:
                    peer_id = getattr(m, "peer_id", None)
                    if not peer_id or not disc_chat:
                        continue
                    ch_id = getattr(peer_id, "channel_id", None) or getattr(peer_id, "chat_id", None)
                    if ch_id == getattr(disc_chat, "id", None):
                        disc_root_id = m.id
                        break
                except Exception:
                    continue

            if not disc_chat or not disc_root_id:
                return rows

            group_username = getattr(disc_chat, "username", None)
            attempts = 0
            while attempts < 3:
                try:
                    async for reply in client.iter_messages(disc_chat, reply_to=disc_root_id):
                        dt = reply.date.replace(tzinfo=None) if reply.date else None
                        text = reply.message or ""
                        sent = analyzer.polarity_scores(text).get("compound")
                        # Construct URL only if the discussion group has a public username
                        url = None
                        if group_username and reply.id:
                            url = f"https://t.me/{group_username}/{reply.id}"
                        rows.append(
                            {
                                "parent_id": pid,
                                "id": reply.id,
                                "date": to_iso(dt) if dt else None,
                                "message": text,
                                "sender_id": getattr(reply, "sender_id", None),
                                "sentiment_compound": sent,
                                "url": url,
                            }
                        )
                    break
                except FloodWaitError as e:
                    secs = int(getattr(e, 'seconds', 5))
                    flood_hits += 1
                    flood_wait_seconds += secs
                    print(f"[rate-limit] FloodWait while scanning discussion group for parent {pid}; waiting {secs}s", flush=True)
                    await asyncio.sleep(secs + 1)
                    attempts += 1
                    continue
                except Exception:
                    break
            return rows

        total_written = 0
        processed = 0
        total = len(list(parent_ids)) if hasattr(parent_ids, '__len__') else None

        async def worker(pid: int):
            nonlocal total_written, processed
            async with sem:
                rows = await handle_parent(int(pid))
            async with write_lock:
                if rows:
                    # Dedupe against existing pairs if provided (resume mode)
                    if existing_pairs is not None:
                        filtered: List[dict] = []
                        for r in rows:
                            try:
                                key = (int(r.get("parent_id")), int(r.get("id")))
                            except Exception:
                                continue
                            if key in existing_pairs:
                                continue
                            existing_pairs.add(key)
                            filtered.append(r)
                        rows = filtered
                    if rows:
                        writer.writerows(rows)
                        total_written += len(rows)
                processed += 1
                if processed % 10 == 0 or (rows and len(rows) > 0):
                    if total is not None:
                        print(f"[replies] processed {processed}/{total} parents; last parent {pid} wrote {len(rows)} replies; total replies {total_written}", flush=True)
                    else:
                        print(f"[replies] processed {processed} parents; last parent {pid} wrote {len(rows)} replies; total replies {total_written}", flush=True)

        tasks = [asyncio.create_task(worker(pid)) for pid in parent_ids]
        await asyncio.gather(*tasks)

    await client.disconnect()
    if flood_hits:
        print(f"[rate-limit] Summary: {flood_hits} FloodWait events; total waited ~{flood_wait_seconds}s", flush=True)


async def fetch_forwards(
    channel: str,
    parent_ids: Set[int],
    output_csv: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    scan_limit: Optional[int] = None,
    append: bool = False,
    session_name: str = "telegram",
    phone: Optional[str] = None,
    twofa_password: Optional[str] = None,
    concurrency: int = 5,
    chunk_size: int = 1000,
):
    """Best-effort: find forwarded messages within the SAME channel that reference the given parent_ids.
    Telegram API does not provide a global reverse-lookup of forwards across all channels; we therefore scan
    this channel's history and collect messages with fwd_from.channel_post matching a parent id.
    """
    load_dotenv()
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_name = os.getenv("TELEGRAM_SESSION_NAME", session_name)
    if not api_id or not api_hash:
        raise RuntimeError("Missing TELEGRAM_API_ID/TELEGRAM_API_HASH in environment. See .env.example")
    client = TelegramClient(session_name, int(api_id), api_hash)
    await ensure_login(client, phone=phone, twofa_password=twofa_password)

    import csv

    # Rate limiting counters
    flood_hits = 0
    import csv

    analyzer = SentimentIntensityAnalyzer()
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    mode = "a" if append else "w"
    write_lock = asyncio.Lock()
    with open(output_csv, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["parent_id", "id", "date", "message", "sender_id", "sentiment_compound", "url"],
        )
        need_header = True
        try:
            if append and os.path.exists(output_csv) and os.path.getsize(output_csv) > 0:
                need_header = False
        except Exception:
            pass
        if need_header:
            writer.writeheader()

        parsed_start = datetime.fromisoformat(start_date) if start_date else None
        parsed_end = datetime.fromisoformat(end_date) if end_date else None

        # If no scan_limit provided, fall back to sequential scan to avoid unbounded concurrency
        if scan_limit is None:
            scanned = 0
            matched = 0
            async for msg in client.iter_messages(channel, limit=None):
                dt = msg.date.replace(tzinfo=None) if msg.date else None
                if parsed_start and dt and dt < parsed_start:
                    break
                if parsed_end and dt and dt > parsed_end:
                    continue
                fwd = getattr(msg, "fwd_from", None)
                if not fwd:
                    continue
                ch_post = getattr(fwd, "channel_post", None)
                if ch_post and int(ch_post) in parent_ids:
                    text = msg.message or ""
                    sent = analyzer.polarity_scores(text).get("compound")
                    url = f"https://t.me/{channel.lstrip('@')}/{msg.id}" if msg.id else None
                    writer.writerow(
                        {
                            "parent_id": int(ch_post),
                            "id": msg.id,
                            "date": to_iso(dt) if dt else None,
                            "message": text,
                            "sender_id": getattr(msg, "sender_id", None),
                            "sentiment_compound": sent,
                            "url": url,
                        }
                    )
                    matched += 1
                scanned += 1
                if scanned % 1000 == 0:
                    print(f"[forwards] scanned ~{scanned} messages; total forwards {matched}", flush=True)
        else:
            # Concurrent chunked scanning by id ranges
            # Rate limiting counters
            flood_hits = 0
            flood_wait_seconds = 0
            sem = asyncio.Semaphore(max(1, int(concurrency)))
            progress_lock = asyncio.Lock()
            matched_total = 0
            completed_chunks = 0

            # Determine latest message id
            latest_msg = await client.get_messages(channel, limit=1)
            latest_id = None
            try:
                latest_id = getattr(latest_msg, 'id', None) or (latest_msg[0].id if latest_msg else None)
            except Exception:
                latest_id = None
            if not latest_id:
                await client.disconnect()
                return

            total_chunks = max(1, (int(scan_limit) + int(chunk_size) - 1) // int(chunk_size))

            async def process_chunk(idx: int):
                nonlocal flood_hits, flood_wait_seconds
                nonlocal matched_total, completed_chunks
                max_id = latest_id - idx * int(chunk_size)
                min_id = max(0, max_id - int(chunk_size))
                attempts = 0
                local_matches = 0
                while attempts < 3:
                    try:
                        async with sem:
                            async for msg in client.iter_messages(channel, min_id=min_id, max_id=max_id):
                                dt = msg.date.replace(tzinfo=None) if msg.date else None
                                if parsed_start and dt and dt < parsed_start:
                                    # This range reached before start; skip remaining in this chunk
                                    break
                                if parsed_end and dt and dt > parsed_end:
                                    continue
                                fwd = getattr(msg, "fwd_from", None)
                                if not fwd:
                                    continue
                                ch_post = getattr(fwd, "channel_post", None)
                                if ch_post and int(ch_post) in parent_ids:
                                    text = msg.message or ""
                                    sent = analyzer.polarity_scores(text).get("compound")
                                    url = f"https://t.me/{channel.lstrip('@')}/{msg.id}" if msg.id else None
                                    async with write_lock:
                                        writer.writerow(
                                            {
                                                "parent_id": int(ch_post),
                                                "id": msg.id,
                                                "date": to_iso(dt) if dt else None,
                                                "message": text,
                                                "sender_id": getattr(msg, "sender_id", None),
                                                "sentiment_compound": sent,
                                                "url": url,
                                            }
                                        )
                                        local_matches += 1
                        break
                    except FloodWaitError as e:
                        secs = int(getattr(e, 'seconds', 5))
                        flood_hits += 1
                        flood_wait_seconds += secs
                        print(f"[rate-limit] FloodWait while scanning ids {min_id}-{max_id}; waiting {secs}s", flush=True)
                        await asyncio.sleep(secs + 1)
                        attempts += 1
                        continue
                    except Exception:
                        # best-effort; skip this chunk
                        break
                async with progress_lock:
                    matched_total += local_matches
                    completed_chunks += 1
                    print(
                        f"[forwards] chunks {completed_chunks}/{total_chunks}; last {min_id}-{max_id} wrote {local_matches} forwards; total forwards {matched_total}",
                        flush=True,
                    )

            tasks = [asyncio.create_task(process_chunk(i)) for i in range(total_chunks)]
            await asyncio.gather(*tasks)

    await client.disconnect()
    # Print summary if we used concurrent chunking
    try:
        if scan_limit is not None and 'flood_hits' in locals() and flood_hits:
            print(f"[rate-limit] Summary: {flood_hits} FloodWait events; total waited ~{flood_wait_seconds}s", flush=True)
    except Exception:
        pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Telegram scraper utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    # Subcommand: scrape channel history
    p_scrape = sub.add_parser("scrape", help="Scrape messages from a channel")
    p_scrape.add_argument("channel", help="Channel username or t.me link, e.g. @python, https://t.me/python")
    p_scrape.add_argument("--output", "-o", required=True, help="Output file (.jsonl or .csv)")
    p_scrape.add_argument("--limit", type=int, default=None, help="Max number of messages to save after filtering")
    p_scrape.add_argument("--offset-date", dest="offset_date", default=None, help="Deprecated: use --start-date instead. ISO date (inclusive)")
    p_scrape.add_argument("--start-date", dest="start_date", default=None, help="ISO start date (inclusive)")
    p_scrape.add_argument("--end-date", dest="end_date", default=None, help="ISO end date (inclusive)")
    p_scrape.add_argument("--append", action="store_true", help="Append to the output file instead of overwriting")
    p_scrape.add_argument("--session-name", default=os.getenv("TELEGRAM_SESSION_NAME", "telegram"))
    p_scrape.add_argument("--phone", default=None)
    p_scrape.add_argument("--twofa-password", default=os.getenv("TELEGRAM_2FA_PASSWORD"))

    # Subcommand: fetch replies for specific message ids
    p_rep = sub.add_parser("replies", help="Fetch replies for given message IDs and save to CSV")
    p_rep.add_argument("channel", help="Channel username or t.me link")
    src = p_rep.add_mutually_exclusive_group(required=True)
    src.add_argument("--ids", help="Comma-separated parent message IDs")
    src.add_argument("--from-csv", dest="from_csv", help="Path to CSV with an 'id' column to use as parent IDs")
    p_rep.add_argument("--output", "-o", required=True, help="Output CSV path (e.g., data/replies_channel.csv)")
    p_rep.add_argument("--append", action="store_true", help="Append to the output file instead of overwriting")
    p_rep.add_argument("--session-name", default=os.getenv("TELEGRAM_SESSION_NAME", "telegram"))
    p_rep.add_argument("--phone", default=None)
    p_rep.add_argument("--twofa-password", default=os.getenv("TELEGRAM_2FA_PASSWORD"))
    p_rep.add_argument("--concurrency", type=int, default=5, help="Number of parent IDs to process in parallel (default 5)")
    p_rep.add_argument("--min-replies", type=int, default=None, help="When using --from-csv, only process parents with replies >= this value")
    p_rep.add_argument("--resume", action="store_true", help="Resume mode: skip parent_id,id pairs already present in the output CSV")

    # Subcommand: fetch forwards (same-channel forwards referencing parent ids)
    p_fwd = sub.add_parser("forwards", help="Best-effort: find forwards within the same channel for given parent IDs")
    p_fwd.add_argument("channel", help="Channel username or t.me link")
    src2 = p_fwd.add_mutually_exclusive_group(required=True)
    src2.add_argument("--ids", help="Comma-separated parent message IDs")
    src2.add_argument("--from-csv", dest="from_csv", help="Path to CSV with an 'id' column to use as parent IDs")
    p_fwd.add_argument("--output", "-o", required=True, help="Output CSV path (e.g., data/forwards_channel.csv)")
    p_fwd.add_argument("--start-date", dest="start_date", default=None)
    p_fwd.add_argument("--end-date", dest="end_date", default=None)
    p_fwd.add_argument("--scan-limit", dest="scan_limit", type=int, default=None, help="Max messages to scan in channel history")
    p_fwd.add_argument("--concurrency", type=int, default=5, help="Number of id-chunks to scan in parallel (requires --scan-limit)")
    p_fwd.add_argument("--chunk-size", dest="chunk_size", type=int, default=1000, help="Approx. messages per chunk (ids)")
    p_fwd.add_argument("--append", action="store_true", help="Append to the output file instead of overwriting")
    p_fwd.add_argument("--session-name", default=os.getenv("TELEGRAM_SESSION_NAME", "telegram"))
    p_fwd.add_argument("--phone", default=None)
    p_fwd.add_argument("--twofa-password", default=os.getenv("TELEGRAM_2FA_PASSWORD"))

    args = parser.parse_args()

    # Normalize channel
    channel = getattr(args, "channel", None)
    if channel and channel.startswith("https://t.me/"):
        channel = channel.replace("https://t.me/", "@")

    def _normalize_handle(ch: Optional[str]) -> Optional[str]:
        if not ch:
            return ch
        # Expect inputs like '@name' or 'name'; return lowercase without leading '@'
        return ch.lstrip('@').lower()

    def _extract_handle_from_url(url: str) -> Optional[str]:
        try:
            if not url:
                return None
            # Accept forms like https://t.me/Name/123 or http(s)://t.me/c/<id>/<msg>
            # Only public usernames (not /c/ links) can be compared reliably
            if "/t.me/" in url:
                # crude parse without urlparse to avoid dependency
                after = url.split("t.me/")[-1]
                parts = after.split('/')
                if parts and parts[0] and parts[0] != 'c':
                    return parts[0]
        except Exception:
            return None
        return None

    if args.command == "scrape":
        written = asyncio.run(
            scrape_channel(
                channel=channel,
                output=args.output,
                limit=args.limit,
                offset_date=args.offset_date,
                start_date=args.start_date,
                end_date=args.end_date,
                append=getattr(args, "append", False),
                session_name=args.session_name,
                phone=args.phone,
                twofa_password=args.twofa_password,
            )
        )
        print(f"Wrote {written} messages to {args.output}")
    elif args.command == "replies":
        # If using --from-csv, try to infer channel from URLs and warn on mismatch
        try:
            if getattr(args, 'from_csv', None):
                import pandas as _pd  # local import to keep startup light
                # Read a small sample of URL column to detect handle
                sample = _pd.read_csv(args.from_csv, usecols=['url'], nrows=20)
                url_handles = [
                    _extract_handle_from_url(str(u)) for u in sample['url'].dropna().tolist() if isinstance(u, (str,))
                ]
                inferred = next((h for h in url_handles if h), None)
                provided = _normalize_handle(channel)
                if inferred and provided and _normalize_handle(inferred) != provided:
                    print(
                        f"[warning] CSV appears to be from @{_normalize_handle(inferred)} but you passed -c @{provided}. "
                        f"Replies may be empty. Consider using -c https://t.me/{inferred}",
                        flush=True,
                    )
        except Exception:
            # Best-effort only; ignore any issues reading/inspecting CSV
            pass
        parent_ids: Set[int]
        if getattr(args, "ids", None):
            parent_ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
        else:
            import pandas as pd  # local import
            usecols = ['id']
            if args.min_replies is not None:
                usecols.append('replies')
            df = pd.read_csv(args.from_csv, usecols=usecols)
            if args.min_replies is not None and 'replies' in df.columns:
                df = df[df['replies'].fillna(0).astype(int) >= int(args.min_replies)]
            parent_ids = set(int(x) for x in df['id'].dropna().astype(int).tolist())
        existing_pairs = None
        if args.resume and os.path.exists(args.output):
            try:
                import csv as _csv
                existing_pairs = set()
                with open(args.output, "r", encoding="utf-8") as _f:
                    reader = _csv.DictReader(_f)
                    for row in reader:
                        try:
                            existing_pairs.add((int(row.get("parent_id")), int(row.get("id"))))
                        except Exception:
                            continue
            except Exception:
                existing_pairs = None

        asyncio.run(
            fetch_replies(
                channel=channel,
                parent_ids=sorted(parent_ids),
                output_csv=args.output,
                append=getattr(args, "append", False),
                session_name=args.session_name,
                phone=args.phone,
                twofa_password=args.twofa_password,
                concurrency=max(1, int(getattr(args, 'concurrency', 5))),
                existing_pairs=existing_pairs,
            )
        )
        print(f"Saved replies to {args.output}")
    elif args.command == "forwards":
        parent_ids: Set[int]
        if getattr(args, "ids", None):
            parent_ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
        else:
            import pandas as pd
            df = pd.read_csv(args.from_csv)
            parent_ids = set(int(x) for x in df['id'].dropna().astype(int).tolist())
        asyncio.run(
            fetch_forwards(
                channel=channel,
                parent_ids=parent_ids,
                output_csv=args.output,
                start_date=args.start_date,
                end_date=args.end_date,
                scan_limit=args.scan_limit,
                concurrency=max(1, int(getattr(args, 'concurrency', 5))),
                chunk_size=max(1, int(getattr(args, 'chunk_size', 1000))),
                append=getattr(args, "append", False),
                session_name=args.session_name,
                phone=args.phone,
                twofa_password=args.twofa_password,
            )
        )
        print(f"Saved forwards to {args.output}")


if __name__ == "__main__":
    main()
