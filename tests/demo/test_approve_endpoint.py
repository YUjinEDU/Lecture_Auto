from lecture_auto.demo.state import create_job, upsert_slide, get_job


def test_slide_tts_status_defaults_to_pending():
    create_job("test-001", "test.pdf", "Test", 8)
    upsert_slide("test-001", 1, {"script": "Hello world"})
    job = get_job("test-001")
    slide = next(s for s in job["slides"] if s["slide_number"] == 1)
    assert slide.get("tts_status") == "pending"


def test_upsert_slide_preserves_existing_fields():
    create_job("test-002", "test.pdf", "Test", 8)
    upsert_slide("test-002", 1, {"script": "Hello", "tts_status": "done"})
    upsert_slide("test-002", 1, {"script": "Updated"})
    job = get_job("test-002")
    slide = next(s for s in job["slides"] if s["slide_number"] == 1)
    assert slide["tts_status"] == "done"   # preserved
    assert slide["script"] == "Updated"    # updated
