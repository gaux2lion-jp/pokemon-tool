"""Last-observed shop prices; cached observations are never live quotes."""
import json
import os
import math
from datetime import datetime, timedelta, timezone
from html import escape

FAILURE_STATUSES = frozenset(('error', 'partial', 'unexpected_empty'))


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def load_previous(report_dir):
    try:
        with open(os.path.join(report_dir, 'prices.json'), encoding='utf-8') as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path, value):
    """A failed write must not destroy the previous successful snapshot."""
    temp_path = path + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)


def reconcile_prices(rows, statuses, previous, product_key, checked_at, valid_products=None):
    """Retain missing rows only when the *shop* failed, not on normal removals.

    Zero unclassified rows are anomalous. Explicit `empty` is allowed only when
    the source parser has confirmed no currently eligible listings (e.g. X's
    24-hour window). Cached X prices cannot outlive that original window.
    """
    checked = timestamp(checked_at)
    if checked is None:
        raise ValueError('checked_at must include a timezone')
    statuses = {site: dict(info) for site, info in statuses.items()}
    current = {}
    for raw in rows:
        row = dict(raw)
        site = row.get('site')
        price = row.get('price')
        name = row.get(product_key)
        if not site or not name or isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            continue
        if valid_products is not None and name not in valid_products:
            continue
        row.update(stale=False, fetched_at=checked_at)
        row.pop('stale_reason', None)
        current.setdefault(site, []).append(row)
        statuses.setdefault(site, {'status': 'ok', 'count': 0, 'message': ''})

    old_by_site = {}
    old_statuses = previous.get('sites', {})
    old_statuses = old_statuses if isinstance(old_statuses, dict) else {}
    old_results = previous.get('results', [])
    for raw in old_results if isinstance(old_results, list) else []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        site = row.get('site')
        if site not in statuses or not row.get(product_key):
            continue
        if valid_products is not None and row[product_key] not in valid_products:
            continue
        price = row.get('price')
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            continue
        # Legacy JSON has no per-row timestamp. Bootstrap only a confirmed
        # successful shop, using its actual report timestamp, never today's date.
        fetched_at = row.get('fetched_at')
        if not fetched_at and (old_statuses.get(site) if isinstance(old_statuses.get(site), dict) else {}).get('status') == 'ok':
            fetched_at = previous.get('updated_at')
        observed = timestamp(fetched_at)
        if observed is None or observed > checked:
            continue
        if row.get('published_at'):
            published = timestamp(row['published_at'])
            if published is None or not timedelta(0) <= checked - published <= timedelta(hours=24):
                continue
        row['fetched_at'] = fetched_at
        old_by_site.setdefault(site, []).append(row)

    result = []
    for site, info in statuses.items():
        fresh = current.get(site, [])
        old = old_by_site.get(site, [])
        state = info.get('status', 'ok' if fresh else 'unexpected_empty')
        if state == 'ok' and not fresh and not info.get('source_count', info.get('count', 0)):
            state = 'unexpected_empty'
        info.update(status=state, checked_at=checked_at, current_count=len(fresh), cached_count=0)
        # Full successes replace the snapshot. Missing individual products do
        # not reappear unless the scraper explicitly reports a shop failure.
        if state in ('ok', 'empty'):
            info['last_success_at'] = checked_at
        elif (old_statuses.get(site) if isinstance(old_statuses.get(site), dict) else {}).get('last_success_at'):
            info['last_success_at'] = old_statuses[site]['last_success_at']
        elif old:
            info['last_success_at'] = max(old, key=lambda row: timestamp(row['fetched_at']))['fetched_at']
        result.extend(fresh)
        if state in FAILURE_STATUSES:
            # Identity includes condition, so we never attach a guarantee from
            # a different condition to a newly observed quote.
            keys = {(row[product_key], row.get('variant', '')) for row in fresh}
            for row in old:
                key = (row[product_key], row.get('variant', ''))
                if key in keys:
                    continue
                row.update(stale=True, stale_reason='更新失敗', prev_price=None, diff_from_prev=None, diff_from_cost=None)
                result.append(row)
                info['cached_count'] += 1
            if not info.get('message'):
                info['message'] = '取得0件・掲載元の変更や通信障害を確認してください' if state == 'unexpected_empty' else '価格を更新できませんでした'
        info['count'] = len(fresh)
    return result, statuses


def report_payload(rows, statuses, category, checked_at):
    observed = [row['fetched_at'] for row in rows if timestamp(row.get('fetched_at'))]
    return {
        'version': 1,
        'checked_at': checked_at,
        'updated_at': max(observed, key=timestamp) if observed else None,
        'category': category,
        'sites': statuses,
        'results': [{key: value for key, value in row.items() if key not in ('cost_price', 'diff_from_cost')} for row in rows],
    }


def display_time(value):
    parsed = timestamp(value)
    return parsed.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M 日本時間') if parsed else '取得日時不明'


def observation_html(row):
    if row.get('stale'):
        return '<span class="stale-label">前回取得価格・更新失敗</span><small class="observed">取得日時: ' + escape(display_time(row.get('fetched_at'))) + '</small>'
    if row.get('fetched_at'):
        return '<small class="observed">取得日時: ' + escape(display_time(row['fetched_at'])) + '</small>'
    return ''


def failure_summary(statuses):
    failures = [(site, info) for site, info in statuses.items() if info.get('status') in FAILURE_STATUSES]
    if not failures:
        return ''
    parts = []
    for site, info in failures:
        count = info.get('cached_count', 0)
        detail = f'前回取得価格 {count}件を参考表示' if count else '前回取得データなし'
        parts.append(escape(site) + ': ' + detail)
    return '<p class="failure-summary" role="status">更新失敗: ' + ' / '.join(parts) + '。前回取得価格は現在の価格・最高値比較・変動通知には使いません。</p>'


RESILIENCE_CSS = '''
.stale-row { background:#fffbeb; }
.stale-label { display:block; color:#92400e; font-weight:700; font-size:12px; }
.observed { display:block; color:#666; font-size:10px; font-weight:normal; white-space:normal; }
.failure-summary { padding:12px; border:1px solid #f59e0b; background:#fffbeb; font-size:13px; line-height:1.6; }
'''


def atomic_text(path, text):
    temp_path = path + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)
