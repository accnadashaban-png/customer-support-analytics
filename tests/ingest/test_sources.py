

def test_demo_data_has_unique_ids_and_follow_ups_after_replies() -> None:
    from support_analytics.ingest.sources import SyntheticSource
    batch = SyntheticSource(seed=3, members=800, days=200).fetch()
    ids = [m.id for m in batch.messages]
    assert len(ids) == len(set(ids))  # a repeated id would silently overwrite a message
    by_thread: dict[str, list] = {}
    for m in batch.messages:
        by_thread.setdefault(m.conversation_id, []).append(m)
    for msgs in by_thread.values():
        seqs = [int(m.id.rsplit("_", 1)[1]) for m in msgs]
        assert [m.sent_at for m in sorted(msgs, key=lambda m: int(m.id.rsplit("_", 1)[1]))] == sorted(m.sent_at for m in msgs), seqs
