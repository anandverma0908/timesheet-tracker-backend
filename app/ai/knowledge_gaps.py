"""
app/ai/knowledge_gaps.py — NOVA knowledge gap detection.

Uses TF-IDF + KMeans to cluster recent ticket titles into topics,
then checks pgvector wiki coverage. Flags topics with no wiki documentation.
"""

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def detect_knowledge_gaps(org_id: str, db) -> list[dict]:
    """
    Cluster recent ticket titles into topics, check wiki coverage.
    Returns gaps where wiki similarity < 0.70.
    """
    from app.models.ticket import JiraTicket
    from app.models.sprint import KnowledgeGap
    from app.models.base import gen_uuid
    from app.ai.search import semantic_search

    # 1. Fetch ticket titles from the last 30 days
    cutoff = datetime.utcnow() - timedelta(days=30)
    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id    == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.synced_at  >= cutoff,
    ).limit(200).all()

    if len(tickets) < 5:
        return []

    titles = [t.summary for t in tickets]
    ticket_keys = [t.jira_key for t in tickets]

    # 2. TF-IDF vectorize
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import KMeans
        import numpy as np

        n_clusters = min(8, len(titles) // 3)
        if n_clusters < 2:
            return []

        vectorizer = TfidfVectorizer(stop_words="english", max_features=500)
        X = vectorizer.fit_transform(titles)

        # 3. KMeans cluster
        km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = km.fit_predict(X)

        feature_names = vectorizer.get_feature_names_out()
        order_centroids = km.cluster_centers_.argsort()[:, ::-1]

        gaps = []

        for cluster_id in range(n_clusters):
            # Top 3 terms as topic label
            top_terms = [feature_names[i] for i in order_centroids[cluster_id, :3]]
            topic = " ".join(top_terms)

            # Indices of tickets in this cluster
            cluster_indices = [i for i, lbl in enumerate(labels) if lbl == cluster_id]
            cluster_tickets = [tickets[i] for i in cluster_indices]
            example_keys    = [t.jira_key for t in cluster_tickets[:5]]

            # 4. Check wiki coverage via semantic search
            try:
                results = await semantic_search(topic, org_id, limit=3)
                wiki_hits = [r for r in results if r.get("source_type") == "wiki"]
                best_sim  = max((r.get("similarity", 0) for r in wiki_hits), default=0.0)
                coverage_pct = int(best_sim * 100)
            except Exception:
                coverage_pct = 0

            # 5. Flag if coverage < 70%
            if coverage_pct < 70:
                suggestion = (
                    f"Consider creating a wiki page covering: {topic}. "
                    f"{len(cluster_tickets)} tickets reference this area with no documentation found."
                )
                gap = KnowledgeGap(
                    id=gen_uuid(),
                    org_id=org_id,
                    topic=topic,
                    ticket_count=len(cluster_tickets),
                    wiki_coverage=coverage_pct,
                    example_tickets=json.dumps(example_keys),
                    suggestion=suggestion,
                )
                db.add(gap)
                gaps.append({
                    "topic":           topic,
                    "ticket_count":    len(cluster_tickets),
                    "wiki_coverage":   coverage_pct,
                    "example_tickets": example_keys,
                    "suggestion":      suggestion,
                })

        db.commit()
        return gaps

    except ImportError as e:
        logger.warning(f"sklearn not available for knowledge gap detection: {e}")
        return []
    except Exception as e:
        logger.warning(f"detect_knowledge_gaps failed: {e}")
        db.rollback()
        return []
