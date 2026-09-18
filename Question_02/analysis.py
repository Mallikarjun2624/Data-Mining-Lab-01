from __future__ import annotations
import os, re, json, sqlite3, time, math
from collections import Counter
import pandas as pd
import numpy as np

BASE = r'c:\Users\ub02-glab-041\Downloads\data_2\data_2'
NOISE = {
    'tender','notice','procurement','government','state','national','department','service','cell','agency',
    'bid','bidding','contract','work','project','estimated','cost','reference','number','date','closing',
    'published','publish','qualifying','eligible','document','details','corrigendum','disclaimer','terms',
    'shall','all','and','for','from','with','this','that','there','their','into','through','moreover','kindly'
}


def load_notices():
    files = sorted(os.path.join(BASE, 'notices', f) for f in os.listdir(os.path.join(BASE, 'notices')) if f.endswith('.csv'))
    return pd.concat([pd.read_csv(f) for f in files], ignore_index=True)


def load_labels():
    return pd.read_csv(os.path.join(BASE, 'labelled_pairs.csv'))


def normalize_text(s):
    if pd.isna(s):
        return ''
    s = str(s).lower()
    s = s.replace('&', ' and ')
    s = re.sub(r'\d+(?:[.,/:-]\d+)*', ' ', s)
    s = re.sub(r'[^a-z]+', ' ', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def tokens_full(row):
    text = (str(row.get('title', '')) + ' ' + str(row.get('body', '')))
    return normalize_text(text).split()


def tokens_filtered(row):
    toks = tokens_full(row)
    return [t for t in toks if len(t) > 2 and t not in NOISE]


def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def score_pair(row_a, row_b, mode='filtered'):
    t1 = tokens_filtered(row_a) if mode == 'filtered' else tokens_full(row_a)
    t2 = tokens_filtered(row_b) if mode == 'filtered' else tokens_full(row_b)
    return jaccard(t1, t2)


def print_label_skew(labels):
    counts = labels['label'].value_counts().to_dict()
    print('label_counts', counts)
    print('same_rate', labels['label'].eq('same').mean())
    print('different_rate', labels['label'].eq('different').mean())
    with open(os.path.join(BASE, '_truth', 'truth.json'), 'r', encoding='utf-8') as f:
        truth = json.load(f)
    print('truth_summary', {k: truth[k] for k in ['opportunities', 'true_duplicate_pairs', 'base_rate_in_corpus', 'base_rate_in_labels']})


def show_pair_examples(labels, notices):
    same = labels[labels['label'] == 'same'].iloc[0]
    diff = labels[labels['label'] == 'different'].iloc[0]
    a = notices[notices['notice_id'] == same['notice_id_a']].iloc[0]
    b = notices[notices['notice_id'] == same['notice_id_b']].iloc[0]
    c = notices[notices['notice_id'] == diff['notice_id_a']].iloc[0]
    d = notices[notices['notice_id'] == diff['notice_id_b']].iloc[0]
    print('same_pair_example', same['notice_id_a'], same['notice_id_b'])
    print('same_pair_filtered', score_pair(a, b, 'filtered'))
    print('same_pair_full', score_pair(a, b, 'full'))
    print('different_pair_example', diff['notice_id_a'], diff['notice_id_b'])
    print('different_pair_filtered', score_pair(c, d, 'filtered'))
    print('different_pair_full', score_pair(c, d, 'full'))


def evidence_over_labels(labels, notices):
    rows = []
    for _, r in labels.iterrows():
        a = notices[notices['notice_id'] == r['notice_id_a']].iloc[0]
        b = notices[notices['notice_id'] == r['notice_id_b']].iloc[0]
        rows.append({'label': r['label'], 'filtered': score_pair(a, b, 'filtered'), 'full': score_pair(a, b, 'full')})
    df = pd.DataFrame(rows)
    same = df[df['label'] == 'same']
    diff = df[df['label'] == 'different']
    print('filtered_summary', {
        'same_mean': float(same['filtered'].mean()),
        'same_min': float(same['filtered'].min()),
        'same_max': float(same['filtered'].max()),
        'different_mean': float(diff['filtered'].mean()),
        'different_min': float(diff['filtered'].min()),
        'different_max': float(diff['filtered'].max()),
    })
    print('full_summary', {
        'same_mean': float(same['full'].mean()),
        'different_mean': float(diff['full'].mean()),
    })


def portal_profile_summary(notices):
    counts = notices['portal_id'].value_counts().head(15).to_dict()
    print('portal_counts_top15', counts)
    nodal = {'P001', 'P002', 'P003', 'P004', 'P005', 'P006'}
    print('nodal_notices_share', float(notices['portal_id'].isin(nodal).mean()))
    print('nodal_portal_counts', notices[notices['portal_id'].isin(nodal)]['portal_id'].value_counts().to_dict())


def build_sqlite_candidates(notices):
    db = os.path.join(BASE, 'dedupe.sqlite')
    if os.path.exists(db):
        os.remove(db)
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute('CREATE TABLE notices (notice_id TEXT PRIMARY KEY, portal_id TEXT, title TEXT, body TEXT, estimated_value TEXT, closing_date TEXT)')
    cur.execute('CREATE TABLE notice_tokens (notice_id TEXT, token TEXT, tf INTEGER, PRIMARY KEY (notice_id, token))')
    cur.execute('CREATE INDEX idx_notice_tokens_token ON notice_tokens(token)')
    cur.execute('CREATE INDEX idx_notice_portal ON notices(portal_id)')
    rows = [(r.notice_id, r.portal_id, r.title, r.body, r.estimated_value, r.closing_date) for _, r in notices.iterrows()]
    cur.executemany('INSERT INTO notices VALUES (?, ?, ?, ?, ?, ?)', rows)
    token_rows = []
    for _, r in notices.iterrows():
        c = Counter(tokens_filtered(r))
        for tok, tf in c.items():
            token_rows.append((r.notice_id, tok, tf))
    cur.executemany('INSERT INTO notice_tokens VALUES (?, ?, ?)', token_rows)
    conn.commit()
    return conn


def candidate_lookup_timing(conn, notices, limit=30):
    cur = conn.cursor()
    sample_ids = notices['notice_id'].head(limit).tolist()
    full_scan = []
    inverted = []
    for nid in sample_ids:
        toks = cur.execute('SELECT token, tf FROM notice_tokens WHERE notice_id = ?', (nid,)).fetchall()
        if not toks:
            continue
        top_tokens = [tok for tok, tf in sorted(toks, key=lambda x: x[1], reverse=True)[:10]]
        t0 = time.perf_counter()
        cur.execute('SELECT COUNT(*) FROM notices WHERE notice_id != ?', (nid,))
        full_scan.append((time.perf_counter() - t0) * 1000)
        q = 'SELECT notice_id FROM notice_tokens WHERE token IN ({}) AND notice_id != ? GROUP BY notice_id ORDER BY SUM(tf) DESC LIMIT 50'.format(','.join(['?']*len(top_tokens)))
        t0 = time.perf_counter()
        cur.execute(q, top_tokens + [nid])
        inverted.append((time.perf_counter() - t0) * 1000)
    print('lookup_ms_full_scan_mean', float(np.mean(full_scan)))
    print('lookup_ms_inverted_mean', float(np.mean(inverted)))


def candidate_retrieval_quality(labels, notices, conn):
    cur = conn.cursor()
    survives = []
    for _, r in labels.iterrows():
        nid_a = r['notice_id_a']; nid_b = r['notice_id_b']; label = r['label']
        toks = cur.execute('SELECT token, tf FROM notice_tokens WHERE notice_id = ?', (nid_a,)).fetchall()
        if not toks:
            continue
        top = [tok for tok, tf in sorted(toks, key=lambda x: x[1], reverse=True)[:10]]
        q = 'SELECT notice_id FROM notice_tokens WHERE token IN ({}) AND notice_id != ? GROUP BY notice_id ORDER BY SUM(tf) DESC LIMIT 50'.format(','.join(['?'] * len(top)))
        candidates = {row[0] for row in cur.execute(q, top + [nid_a])}
        survives.append((label, nid_b in candidates))
    same_surv = [v for label, v in survives if label == 'same']
    diff_surv = [v for label, v in survives if label == 'different']
    print('survival_same_rate', float(np.mean(same_surv)))
    print('survival_different_rate', float(np.mean(diff_surv)))
    return survives


def main():
    notices = load_notices()
    labels = load_labels()
    print('notices_total', len(notices))
    print('body_len_summary', notices['body'].fillna('').str.len().describe().to_dict())
    print('notice_id_sample', notices[['notice_id', 'portal_id', 'title', 'estimated_value']].head(2).to_dict('records'))
    print_label_skew(labels)
    show_pair_examples(labels, notices)
    evidence_over_labels(labels, notices)
    portal_profile_summary(notices)
    conn = build_sqlite_candidates(notices)
    candidate_lookup_timing(conn, notices)
    candidate_retrieval_quality(labels, notices, conn)
    conn.close()


if __name__ == '__main__':
    main()
