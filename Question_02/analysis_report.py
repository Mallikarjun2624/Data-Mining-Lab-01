import os
import re
import sqlite3
import time
from collections import Counter

import numpy as np
import pandas as pd

BASE = r'c:\Users\ub02-glab-041\Downloads\data_2\data_2'

NOISE_WORDS = {
    'government', 'state', 'national', 'department', 'agency', 'service', 'cell',
    'procurement', 'notice', 'tender', 'bid', 'bidding', 'contract', 'work',
    'project', 'document', 'details', 'corrigendum', 'disclaimer', 'terms',
    'shall', 'kindly', 'validity', 'warranty', 'moreover', 'this', 'that',
    'there', 'their', 'with', 'from', 'into', 'through', 'for', 'all', 'and',
    'the', 'not', 'are', 'was', 'will', 'date', 'closing', 'reference', 'number',
    'estimated', 'cost', 'published', 'publish', 'portal', 'office', 'district',
    'authority', 'council', 'site', 'province', 'committee'
}


def load_notices():
    files = sorted(
        os.path.join(BASE, 'notices', f)
        for f in os.listdir(os.path.join(BASE, 'notices'))
        if f.endswith('.csv')
    )
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def load_labels():
    return pd.read_csv(os.path.join(BASE, 'labelled_pairs.csv'))


def normalize_text(s: str) -> str:
    if pd.isna(s):
        return ''
    s = str(s).lower()
    s = s.replace('&', ' and ')
    s = re.sub(r'\d+(?:[.,/:-]\d+)*', ' ', s)
    s = re.sub(r'[^a-z]+', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def full_tokens(row):
    text = f"{row.get('title', '')} {row.get('body', '')}"
    return normalize_text(text).split()


def filtered_tokens(row):
    toks = full_tokens(row)
    return [t for t in toks if len(t) > 2 and t not in NOISE_WORDS]


def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def pair_score(row_a, row_b, mode='filtered'):
    ta = filtered_tokens(row_a) if mode == 'filtered' else full_tokens(row_a)
    tb = filtered_tokens(row_b) if mode == 'filtered' else full_tokens(row_b)
    return jaccard(ta, tb)


def dataset_summary():
    notices = load_notices()
    labels = load_labels()
    print('notices_total', len(notices))
    print('labels_total', len(labels))
    print('label_counts', labels['label'].value_counts().to_dict())
    print('same_rate', labels['label'].eq('same').mean())
    print('portal_top10', notices['portal_id'].value_counts().head(10).to_dict())
    nodal = {'P001', 'P002', 'P003', 'P004', 'P005', 'P006'}
    print('nodal_share', float(notices['portal_id'].isin(nodal).mean()))
    print('body_len_summary', notices['body'].fillna('').str.len().describe().to_dict())
    print('estimated_value_missing', int(notices['estimated_value'].isna().sum()))
    print('closing_date_missing', int(notices['closing_date'].isna().sum()))
    return notices, labels


def similarity_evidence(notices, labels):
    same = labels[labels['label'] == 'same'].iloc[0]
    diff = labels[labels['label'] == 'different'].iloc[0]
    a1 = notices[notices['notice_id'] == same['notice_id_a']].iloc[0]
    a2 = notices[notices['notice_id'] == same['notice_id_b']].iloc[0]
    b1 = notices[notices['notice_id'] == diff['notice_id_a']].iloc[0]
    b2 = notices[notices['notice_id'] == diff['notice_id_b']].iloc[0]

    print('same_pair_example', same['notice_id_a'], same['notice_id_b'])
    print('same_pair_filtered', pair_score(a1, a2, 'filtered'))
    print('same_pair_full', pair_score(a1, a2, 'full'))
    print('different_pair_example', diff['notice_id_a'], diff['notice_id_b'])
    print('different_pair_filtered', pair_score(b1, b2, 'filtered'))
    print('different_pair_full', pair_score(b1, b2, 'full'))

    rows = []
    for _, row in labels.iterrows():
        n1 = notices[notices['notice_id'] == row['notice_id_a']].iloc[0]
        n2 = notices[notices['notice_id'] == row['notice_id_b']].iloc[0]
        rows.append({'label': row['label'], 'filtered': pair_score(n1, n2, 'filtered'), 'full': pair_score(n1, n2, 'full')})
    df = pd.DataFrame(rows)
    same_df = df[df['label'] == 'same']
    diff_df = df[df['label'] == 'different']
    print('filtered_summary', {
        'same_mean': float(same_df['filtered'].mean()),
        'same_min': float(same_df['filtered'].min()),
        'same_max': float(same_df['filtered'].max()),
        'different_mean': float(diff_df['filtered'].mean()),
        'different_min': float(diff_df['filtered'].min()),
        'different_max': float(diff_df['filtered'].max()),
    })
    print('full_summary', {
        'same_mean': float(same_df['full'].mean()),
        'different_mean': float(diff_df['full'].mean()),
    })


def threshold_scan(notices, labels):
    rows = []
    for _, row in labels.iterrows():
        n1 = notices[notices['notice_id'] == row['notice_id_a']].iloc[0]
        n2 = notices[notices['notice_id'] == row['notice_id_b']].iloc[0]
        rows.append({'label': row['label'], 'score': pair_score(n1, n2, 'filtered')})
    df = pd.DataFrame(rows)
    for thr in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
        tp = int(((df['label'] == 'same') & (df['score'] >= thr)).sum())
        fp = int(((df['label'] == 'different') & (df['score'] >= thr)).sum())
        fn = int(((df['label'] == 'same') & (df['score'] < thr)).sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        print('threshold', thr, 'precision', round(precision, 4), 'recall', round(recall, 4), 'tp', tp, 'fp', fp, 'fn', fn)


def reduced_form_accuracy(notices, labels):
    out = []
    for k in [16, 32, 64, 128, 256]:
        errors = []
        for _, row in labels.iterrows():
            n1 = notices[notices['notice_id'] == row['notice_id_a']].iloc[0]
            n2 = notices[notices['notice_id'] == row['notice_id_b']].iloc[0]
            exact = pair_score(n1, n2, 'filtered')
            t1 = Counter(filtered_tokens(n1)); t2 = Counter(filtered_tokens(n2))
            top1 = set(sorted(t1, key=t1.get, reverse=True)[:k])
            top2 = set(sorted(t2, key=t2.get, reverse=True)[:k])
            approx = jaccard(list(top1), list(top2))
            errors.append(abs(exact - approx))
        out.append((k, float(np.mean(errors)), float(np.quantile(errors, 0.95))))
    print('reduced_form_accuracy', out)


def build_sqlite_index(notices):
    db_path = os.path.join(BASE, 'dedupe_index.sqlite')
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('CREATE TABLE notices (notice_id TEXT PRIMARY KEY, portal_id TEXT, title TEXT, body TEXT, estimated_value TEXT, closing_date TEXT)')
    cur.execute('CREATE TABLE notice_tokens (notice_id TEXT, token TEXT, tf INTEGER, PRIMARY KEY (notice_id, token))')
    cur.execute('CREATE INDEX idx_notice_tokens_token ON notice_tokens(token)')
    cur.execute('CREATE INDEX idx_notice_portal ON notices(portal_id)')

    rows = [(r.notice_id, r.portal_id, r.title, r.body, r.estimated_value, r.closing_date) for _, r in notices.iterrows()]
    cur.executemany('INSERT INTO notices VALUES (?, ?, ?, ?, ?, ?)', rows)
    token_rows = []
    for _, r in notices.iterrows():
        counts = Counter(filtered_tokens(r))
        for tok, tf in counts.items():
            token_rows.append((r.notice_id, tok, tf))
    cur.executemany('INSERT INTO notice_tokens VALUES (?, ?, ?)', token_rows)
    conn.commit()
    return conn


def retrieval_quality(conn, notices, labels, k_tokens=10):
    cur = conn.cursor()
    results = []
    for _, row in labels.iterrows():
        nid_a = row['notice_id_a']
        nid_b = row['notice_id_b']
        label = row['label']
        toks = cur.execute('SELECT token, tf FROM notice_tokens WHERE notice_id = ?', (nid_a,)).fetchall()
        if not toks:
            results.append((label, False, 0))
            continue
        top_tokens = [tok for tok, tf in sorted(toks, key=lambda x: x[1], reverse=True)[:k_tokens]]
        placeholders = ','.join(['?'] * len(top_tokens))
        q = f'SELECT notice_id FROM notice_tokens WHERE token IN ({placeholders}) AND notice_id != ? GROUP BY notice_id ORDER BY SUM(tf) DESC LIMIT 50'
        candidates = {r[0] for r in cur.execute(q, top_tokens + [nid_a])}
        results.append((label, nid_b in candidates, len(candidates)))

    same = [v for label, v, _ in results if label == 'same']
    diff = [v for label, v, _ in results if label == 'different']
    counts = [c for _, _, c in results]
    print('retrieval_same_survival_rate', float(np.mean(same)))
    print('retrieval_different_survival_rate', float(np.mean(diff)))
    print('retrieval_candidate_count_mean', float(np.mean(counts)))
    print('retrieval_candidate_count_p95', float(np.quantile(counts, 0.95)))


def access_method_measure(notices):
    conn = build_sqlite_index(notices)
    cur = conn.cursor()
    sample_ids = notices['notice_id'].head(30).tolist()
    full_scan = []
    inverted = []
    for nid in sample_ids:
        toks = cur.execute('SELECT token, tf FROM notice_tokens WHERE notice_id = ?', (nid,)).fetchall()
        if not toks:
            continue
        top = [tok for tok, tf in sorted(toks, key=lambda x: x[1], reverse=True)[:10]]
        t0 = time.perf_counter(); cur.execute('SELECT COUNT(*) FROM notices WHERE notice_id != ?', (nid,)); full_scan.append((time.perf_counter() - t0) * 1000)
        placeholders = ','.join(['?'] * len(top))
        q = f'SELECT notice_id FROM notice_tokens WHERE token IN ({placeholders}) AND notice_id != ? GROUP BY notice_id ORDER BY SUM(tf) DESC LIMIT 50'
        t0 = time.perf_counter(); cur.execute(q, top + [nid]); inverted.append((time.perf_counter() - t0) * 1000)
    print('scan_mean_ms', float(np.mean(full_scan)))
    print('inverted_mean_ms', float(np.mean(inverted)))
    conn.close()


def hotspot_analysis(notices):
    portal_load = {}
    for pid, g in notices.groupby('portal_id'):
        portal_load[pid] = int(g.apply(lambda r: len(filtered_tokens(r)), axis=1).sum())
    print('portal_token_load_top10', dict(sorted(portal_load.items(), key=lambda kv: kv[1], reverse=True)[:10]))
    nodal = {'P001', 'P002', 'P003', 'P004', 'P005', 'P006'}
    total = sum(portal_load.values())
    print('nodal_load_share', float(sum(v for pid, v in portal_load.items() if pid in nodal) / total))


def main():
    notices, labels = dataset_summary()
    similarity_evidence(notices, labels)
    threshold_scan(notices, labels)
    reduced_form_accuracy(notices, labels)
    conn = build_sqlite_index(notices)
    retrieval_quality(conn, notices, labels, k_tokens=10)
    conn.close()
    access_method_measure(notices)
    hotspot_analysis(notices)


if __name__ == '__main__':
    main()
