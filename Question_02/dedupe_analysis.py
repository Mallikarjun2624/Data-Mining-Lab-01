from __future__ import annotations
import os, re, math, sqlite3
from collections import Counter, defaultdict
import numpy as np
import pandas as pd

BASE = r'c:\Users\ub02-glab-041\Downloads\data_2\data_2'

# --- Corpus loading ---

def load_notices():
    notice_files = sorted(os.path.join(BASE, 'notices', f) for f in os.listdir(os.path.join(BASE, 'notices')) if f.endswith('.csv'))
    frames = [pd.read_csv(f) for f in notice_files]
    df = pd.concat(frames, ignore_index=True)
    return df


def load_labels():
    return pd.read_csv(os.path.join(BASE, 'labelled_pairs.csv'))


# --- Text normalization ---
PORTAL_BOILERPLATE = {
    'p001', 'p002', 'p005', 'p003', 'p004', 'p006',
    'government', 'state', 'national', 'procurement', 'cell', 'service',
    'department', 'shall', 'tender', 'notice', 'bid', 'bidding', 'contract',
    'document', 'work', 'details', 'corrigendum', 'disclaimer', 'warranty',
    'reference', 'number', 'estimated', 'cost', 'closing', 'date', 'published',
    'time', 'validity', 'moreover', 'shall', 'all', 'entity', 'agency'
}


def normalize_text(s: str) -> str:
    if pd.isna(s):
        return ''
    s = str(s).lower()
    s = s.replace('&', ' and ')
    s = re.sub(r'\b(?:rs|inr|rupees|lakh|crore|cr|rs\.)\b', ' ', s)
    s = re.sub(r'\d+(?:[.,/:-]\d+)*', ' ', s)
    s = re.sub(r'[^a-z0-9]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def full_tokens(row):
    text = f"{row['title']} {row['body']}"
    return normalize_text(text).split()


def filtered_tokens(row):
    toks = full_tokens(row)
    toks = [t for t in toks if len(t) > 2 and t not in PORTAL_BOILERPLATE]
    return toks


def jaccard(a, b):
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def tokens_for_pair(row_a, row_b, mode='filtered'):
    if mode == 'filtered':
        ta, tb = filtered_tokens(row_a), filtered_tokens(row_b)
    else:
        ta, tb = full_tokens(row_a), full_tokens(row_b)
    return ta, tb


# --- Analysis of labelled pairs ---
def label_stats():
    labels = load_labels()
    counts = labels['label'].value_counts().to_dict()
    same_rate = labels['label'].eq('same').mean()
    print('label_counts', counts)
    print('same_rate', same_rate)
    return labels


# --- Similarity evidence ---
def sample_pair_evidence(labels, notices):
    same = labels[labels['label'] == 'same'].iloc[0]
    diff = labels[labels['label'] == 'different'].iloc[0]
    ra = notices[notices['notice_id'] == same['notice_id_a']].iloc[0]
    rb = notices[notices['notice_id'] == same['notice_id_b']].iloc[0]
    da = notices[notices['notice_id'] == diff['notice_id_a']].iloc[0]
    db = notices[notices['notice_id'] == diff['notice_id_b']].iloc[0]

    same_raw = jaccard(*tokens_for_pair(ra, rb, 'raw')) if False else None
    same_filt = jaccard(*tokens_for_pair(ra, rb, 'filtered'))
    diff_raw = jaccard(*tokens_for_pair(da, db, 'raw')) if False else None
    diff_filt = jaccard(*tokens_for_pair(da, db, 'filtered'))

    print('example_same_pair', same['notice_id_a'], same['notice_id_b'])
    print('example_same_filtered_score', same_filt)
    print('example_diff_pair', diff['notice_id_a'], diff['notice_id_b'])
    print('example_diff_filtered_score', diff_filt)

    full_scores = []
    full_scores_diff = []
    for _, row in labels.iterrows():
        a = notices[notices['notice_id'] == row['notice_id_a']].iloc[0]
        b = notices[notices['notice_id'] == row['notice_id_b']].iloc[0]
        full_scores.append((row['label'], jaccard(*tokens_for_pair(a, b, 'filtered'))))

    print('filtered_scores_summary', {
        'same_mean': np.mean([s for lbl, s in full_scores if lbl == 'same']),
        'same_min': np.min([s for lbl, s in full_scores if lbl == 'same']),
        'same_max': np.max([s for lbl, s in full_scores if lbl == 'same']),
        'different_mean': np.mean([s for lbl, s in full_scores if lbl == 'different']),
        'different_max': np.max([s for lbl, s in full_scores if lbl == 'different']),
        'different_min': np.min([s for lbl, s in full_scores if lbl == 'different']),
    })


# --- Build DB schema ---
def build_sqlite_db(notices):
    db_path = os.path.join(BASE, 'dedupe.sqlite')
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('CREATE TABLE notices (notice_id TEXT PRIMARY KEY, portal_id TEXT, title TEXT, body TEXT, estimated_value TEXT, closing_date TEXT)')
    cur.execute('CREATE TABLE notice_tokens (notice_id TEXT, token TEXT, tf INTEGER, PRIMARY KEY (notice_id, token))')
    cur.execute('CREATE INDEX idx_notice_tokens_token ON notice_tokens(token)')
    cur.execute('CREATE INDEX idx_notice_portal ON notices(portal_id)')

    notice_rows = [(
        row['notice_id'], row['portal_id'], row['title'], row['body'], row['estimated_value'], row['closing_date']
    ) for _, row in notices.iterrows()]
    cur.executemany('INSERT INTO notices VALUES (?, ?, ?, ?, ?, ?)', notice_rows)

    token_rows = []
    for _, row in notices.iterrows():
        toks = filtered_tokens(row)
        c = Counter(toks)
        for token, tf in c.items():
            token_rows.append((row['notice_id'], token, tf))
    cur.executemany('INSERT INTO notice_tokens VALUES (?, ?, ?)', token_rows)
    conn.commit()
    return db_path, conn


def query_candidates(db_path, notice_id, k=20):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # fetch tokens for notice
    toks = cur.execute('SELECT token FROM notice_tokens WHERE notice_id = ?', (notice_id,)).fetchall()
    if not toks:
        return []
    toks = [t[0] for t in toks]
    # top tokens by tf
    toks = sorted(Counter(toks).items(), key=lambda x: x[1], reverse=True)[:k]
    tokens = [t for t, _ in toks]
    if not tokens:
        return []
    q = 'SELECT notice_id, COUNT(*) AS hits FROM notice_tokens WHERE token IN ({}) GROUP BY notice_id ORDER BY hits DESC LIMIT 50'.format(','.join(['?']*len(tokens)))
    rows = cur.execute(q, tokens).fetchall()
    return [r[0] for r in rows if r[0] != notice_id]


def compare_access_methods(notices):
    db_path, conn = build_sqlite_db(notices)
    cur = conn.cursor()
    # use a notice with a broad token distribution for candidate lookup workload
    sample_ids = notices['notice_id'].head(50).tolist()
    t_scan = []
    t_index = []
    for nid in sample_ids:
        toks = cur.execute('SELECT token FROM notice_tokens WHERE notice_id = ?', (nid,)).fetchall()
        if not toks:
            continue
        toks = [t[0] for t in toks]
        tokens = sorted(Counter(toks).items(), key=lambda x: x[1], reverse=True)[:15]
        tokens = [t for t, _ in tokens]
        # full scan alternative
        import time
        t0 = time.perf_counter()
        rows = cur.execute('SELECT notice_id FROM notices WHERE notice_id != ? LIMIT 12000', (nid,)).fetchall()
        t_scan.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        q = 'SELECT notice_id, COUNT(*) AS hits FROM notice_tokens WHERE token IN ({}) GROUP BY notice_id ORDER BY hits DESC LIMIT 50'.format(','.join(['?']*len(tokens)))
        cur.execute(q, tokens)
        t_index.append(time.perf_counter() - t0)
    print('candidate_lookup_time_scan_mean_ms', np.mean(t_scan)*1000)
    print('candidate_lookup_time_index_mean_ms', np.mean(t_index)*1000)
    return db_path


# --- Check portal hotspot skew ---
def hotspot_distribution(notices):
    nodal = {'P001','P002','P003','P004','P005','P006'}
    portal_counts = notices['portal_id'].value_counts().reset_index()
    portal_counts.columns = ['portal_id', 'n']
    print('top_portals', portal_counts.head(10).to_dict('records'))
    nodal_counts = notices[notices['portal_id'].isin(nodal)].groupby('portal_id').size()
    print('nodal_counts', nodal_counts.to_dict())
    print('nodal_share_notices', notices['portal_id'].isin(nodal).mean())


# --- Main ---
def main():
    notices = load_notices()
    labels = load_labels()
    print('notices_total', len(notices))
    print('columns', notices.columns.tolist())
    print('sample_row', notices.iloc[0].to_dict())
    print('body_len', notices['body'].fillna('').str.len().describe().to_dict())
    print('estimated_value_missing', notices['estimated_value'].isna().sum())
    print('closing_missing', notices['closing_date'].isna().sum())
    label_stats()
    sample_pair_evidence(labels, notices)
    hotspot_distribution(notices)
    compare_access_methods(notices)


if __name__ == '__main__':
    main()
