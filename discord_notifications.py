"""Complete, size-bounded price notifications; delivery does not mutate prices."""
import math
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

DISCORD_MAX_LEN = 1900


def discord_length(text):
    """UTF-16 units conservatively account for Japanese text and emoji."""
    return len(text.encode('utf-16-le')) // 2


def _plain(value):
    return str(value).replace('\r', ' ').replace('\n', ' ')


def _take(text, capacity):
    used = 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if used + width > capacity:
            return text[:index], text[index:]
        used += width
    return text, ''


def _pack(lines, capacity):
    pages, current = [], ''
    continuation = '↪ 続き: '
    for line in lines:
        # Ordinary changes stay together. Exceptionally long names continue
        # across messages, never disappearing to make room for the report link.
        if discord_length(line) <= capacity:
            if current and discord_length(current + line) > capacity:
                pages.append(current)
                current = ''
            current += line
            continue
        if current:
            pages.append(current)
            current = ''
        remaining, prefix = line.rstrip('\n'), ''
        while remaining:
            fragment, remaining = _take(remaining, capacity - discord_length(prefix) - 1)
            if not fragment:
                raise ValueError('Discord header and link leave too little room for a change')
            part = prefix + fragment + '\n'
            if remaining:
                pages.append(part)
                prefix = continuation
            else:
                current = part
    if current:
        pages.append(current)
    return pages


def build_change_messages(changes, checked_at, report_url):
    """Render every normalized fresh change, returning an ordered message batch."""
    changes = sorted(
        (item for item in changes if not item.get('stale') and item.get('diff') not in (None, 0)),
        key=lambda item: (str(item['product']), str(item['site']), str(item.get('variant') or ''), item['price'], item['diff']),
    )
    if not changes:
        return []
    lines = []
    for item in changes:
        diff = item['diff']
        icon = '📈' if diff > 0 else '📉'
        condition = f" [{_plain(item['variant'])}]" if item.get('variant') else ''
        lines.append(
            f"{icon} {_plain(item['product'])}{condition}：{item['price'] - diff:,}円 → "
            f"{item['price']:,}円 （{_plain(item['site'])}） {diff:+,}円\n"
        )
    footer = f'\n📋 **全商品・全サイトの詳細一覧はこちら**\n{report_url}'

    def header(page, total):
        return (f'📦 **買取価格チェック（{checked_at} 日本時間）**\n'
                f'🔔 **価格が変わった商品：{len(changes)}件（{page}/{total}）**\n\n')

    digits = 1
    while True:
        placeholder = '9' * digits
        capacity = DISCORD_MAX_LEN - discord_length(header(placeholder, placeholder) + footer)
        if capacity < 32:
            raise ValueError('Discord header and report URL exceed the safe message budget')
        pages = _pack(lines, capacity)
        required_digits = len(str(len(pages)))
        if required_digits <= digits:
            break
        digits = required_digits
    messages = [header(i, len(pages)) + page + footer for i, page in enumerate(pages, 1)]
    if any(discord_length(message) > DISCORD_MAX_LEN for message in messages):
        raise AssertionError('Discord message budget exceeded')
    return messages


def _retry_after(response):
    values = []
    header = response.headers.get('Retry-After')
    if header is not None:
        values.append(header)
    try:
        body = response.json().get('retry_after')
    except (ValueError, AttributeError):
        body = None
    if body is not None:
        values.append(body)
    waits = []
    for value in values:
        if isinstance(value, bool):
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        waits.append(value)
    # Never retry earlier than either server-provided cooldown.
    return max(waits) if waits else None


def send_messages(webhook_url, messages, *, post=None, sleep=None, retry_wait_budget=30):
    """Send in order. Retry only explicit 429 rejection, never an uncertain POST.

    This is not a persistent outbox. A stopped batch is reported honestly so
    callers cannot confuse a partially accepted batch with complete delivery.
    """
    messages = [messages] if isinstance(messages, str) else list(messages)
    result = {'total': len(messages), 'sent': 0, 'status': 'skipped'}
    if not webhook_url or not messages:
        return result
    if any(not isinstance(message, str) or not message or discord_length(message) > DISCORD_MAX_LEN
           for message in messages):
        raise ValueError('Invalid or oversized Discord message; no messages sent')
    parsed_url = urlsplit(webhook_url)
    query = urlencode([(key, value) for key, value in parse_qsl(parsed_url.query, keep_blank_values=True) if key != 'wait'])
    webhook_url = urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, query, parsed_url.fragment))
    post = post or requests.post
    sleep = sleep or time.sleep
    for index, message in enumerate(messages, 1):
        retries = 0
        while True:
            try:
                response = post(
                    webhook_url, params={'wait': 'true'},
                    json={'content': message, 'allowed_mentions': {'parse': []}},
                    timeout=15, allow_redirects=False,
                )
            except requests.RequestException:
                result.update(status='unknown', stopped_at=index)
                print(f"[Discord] {index}/{len(messages)}通目の送信結果は不明です。自動再送しません。"
                      f"確認済み {result['sent']}通、未確認・未送信 {len(messages) - result['sent']}通。")
                return result
            if response.status_code == 200:
                try:
                    message_id = response.json().get('id')
                except (ValueError, AttributeError):
                    message_id = None
                if isinstance(message_id, str) and message_id.isascii() and message_id.isdigit():
                    result['sent'] += 1
                    print(f'[Discord] 通知を送信しました。（{index}/{len(messages)}通目）')
                    break
            if response.status_code < 400 or response.status_code == 408 or response.status_code >= 500:
                result.update(status='unknown', stopped_at=index, http_status=response.status_code)
                print(f"[Discord] {index}/{len(messages)}通目の送信結果を確認できません（HTTP {response.status_code}）。"
                      f"自動再送しません。確認済み {result['sent']}通、未確認・未送信 {len(messages) - result['sent']}通。")
                return result
            if response.status_code == 429:
                wait = _retry_after(response)
                if wait is not None and wait <= retry_wait_budget and retries < 3:
                    sleep(wait)
                    retry_wait_budget -= wait
                    retries += 1
                    continue
            result.update(status='failed', stopped_at=index, http_status=response.status_code)
            print(f"[Discord] {index}/{len(messages)}通目で停止しました（HTTP {response.status_code}）。"
                  f"確認済み {result['sent']}通、未送信 {len(messages) - result['sent']}通。")
            return result
        if index < len(messages):
            sleep(1)
    result['status'] = 'sent'
    return result
