"""Current-run prices and explicitly separate historical observations."""
import json
import os
import math
from datetime import datetime, timedelta, timezone
from html import escape
from urllib3.util.retry import Retry

FAILURE_STATUSES = frozenset(('error', 'partial', 'unexpected_empty'))


class RetryBudgetExceeded(RuntimeError):
    """A server cooldown is too long for this scheduled check."""


class BoundedRetry(Retry):
    """Honor short server cooldowns; fail closed instead of retrying early.

    Retry-After may be hours or days. Waiting that long prevents a scheduled
    report from publishing source failures. A long cooldown stops this source;
    it is not truncated into an earlier retry.
    """
    max_retry_after_wait = 30

    def sleep(self, response=None):
        if self.respect_retry_after_header and response is not None:
            retry_after = self.get_retry_after(response)
            if retry_after and retry_after > self.max_retry_after_wait:
                raise RetryBudgetExceeded('掲載元の待機指定が長いため今回の価格取得を中止します')
        return super().sleep(response)


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
    """Retain missing rows internally for audit/unavailable placeholders only.

    Renderers must hide amounts on stale rows. The public `results` collection
    contains current-run prices only; cached rows have a separate collection.

    Zero unclassified rows are anomalous. Explicit `empty` is allowed only when
    the source parser has confirmed no currently eligible listings (e.g. X's
    24-hour window). Cached X prices cannot outlive that original window.
    """
    checked = timestamp(checked_at)
    if checked is None:
        raise ValueError('checked_at must include a timezone')
    statuses = {site: dict(info) for site, info in statuses.items()}
    current = {}
    rejected_sites = set()
    invalid_unknown_row = False
    for raw in rows:
        if not isinstance(raw, dict):
            invalid_unknown_row = True
            continue
        row = dict(raw)
        site = row.get('site')
        price = row.get('price')
        name = row.get(product_key)
        if row.get('stale') or not site or not name or isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            if site:
                rejected_sites.add(site)
            else:
                invalid_unknown_row = True
            continue
        if valid_products is not None and name not in valid_products:
            continue
        if statuses.get(site, {}).get('status') in ('error', 'unexpected_empty', 'empty', 'unconfigured'):
            continue
        row.update(stale=False, fetched_at=checked_at)
        row.pop('stale_reason', None)
        current.setdefault(site, []).append(row)
        statuses.setdefault(site, {'status': 'ok', 'count': 0, 'message': ''})

    old_by_site = {}
    old_statuses = previous.get('sites', {})
    old_statuses = old_statuses if isinstance(old_statuses, dict) else {}
    old_results = previous.get('results', [])
    historical = previous.get('historical_observations', [])
    # Read both legacy mixed results and the current-only v2 feed. Never
    # relabel historical observations with this run's check timestamp.
    old_results = (old_results if isinstance(old_results, list) else []) + (historical if isinstance(historical, list) else [])
    for raw in old_results:
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
        if state == 'ok' and site in rejected_sites:
            state = 'partial' if fresh else 'unexpected_empty'
        elif state == 'ok' and not fresh and (invalid_unknown_row or not info.get('source_count', 0)):
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
    """Keep cached amounts out of the feed consumed as current prices."""
    current = [row for row in rows if not row.get('stale')]
    historical = [row for row in rows if row.get('stale')]
    observed = [row['fetched_at'] for row in current if timestamp(row.get('fetched_at'))]

    def public_rows(items):
        return [{key: value for key, value in row.items() if key not in ('cost_price', 'diff_from_cost')} for row in items]

    return {
        'version': 2,
        'price_policy': 'current_run_only',
        'checked_at': checked_at,
        'updated_at': max(observed, key=timestamp) if observed else None,
        'category': category,
        'sites': statuses,
        'results': public_rows(current),
        'historical_observations': public_rows(historical),
    }


def display_time(value):
    parsed = timestamp(value)
    return parsed.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M 日本時間') if parsed else '取得日時不明'


def observation_html(row):
    if row.get('stale'):
        return '<span class="stale-label">更新失敗</span><small class="observed">前回の取得日時: ' + escape(display_time(row.get('fetched_at'))) + '</small>'
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
        detail = f'{count}件の価格を非表示' if count else '今回の価格を確認できません'
        parts.append(escape(site) + ': ' + detail)
    return '<p class="failure-summary" role="status">更新失敗: ' + ' / '.join(parts) + '。取得できなかった価格は「取得不可」とし、古い金額は表示しません。次回の定期取得で再確認します。</p>'


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
