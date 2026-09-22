from hextrack.queues import RANKED_QUEUES, is_ranked, queue_label, queue_labels_json


def test_queue_labels():
    assert queue_label(420) == "Ranked Solo/Duo"
    assert queue_label(440) == "Ranked Flex"
    assert queue_label(450) == "ARAM"
    assert queue_label(1700) == "Arena"
    assert queue_label(0) == "Custom"
    assert queue_label(987654) == "Queue 987654"
    assert RANKED_QUEUES == {420, 440}
    assert is_ranked(420) and not is_ranked(400)
    labels = queue_labels_json()
    assert labels["420"] == "Ranked Solo/Duo" and all(isinstance(k, str) for k in labels)
