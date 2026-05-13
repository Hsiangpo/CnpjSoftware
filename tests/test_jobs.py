from cnpj_tool.jobs import JobStore
from cnpj_tool.models import BatchResult


def test_job_store_creates_job_and_runs_processor():
    store = JobStore()

    job = store.create(["03541629000137"])

    store.run(job.job_id, lambda cnpjs: [
        BatchResult(input_cnpj="03.541.629/0001-37", normalized_cnpj=cnpjs[0], status="success")
    ])

    loaded = store.get(job.job_id)
    assert loaded.status == "completed"
    assert loaded.results[0].normalized_cnpj == "03541629000137"


def test_job_store_cancel_marks_partial_job_canceled():
    store = JobStore()
    job = store.create(["03541629000137", "21746991000126"])

    def processor(cnpjs, existing_results=None, on_result=None, should_stop=None):
        result = BatchResult(input_cnpj="03.541.629/0001-37", normalized_cnpj=cnpjs[0], status="success")
        on_result(result)
        store.cancel(job.job_id)
        assert should_stop()
        return [result]

    store.run(job.job_id, processor)

    loaded = store.get(job.job_id)
    assert loaded.status == "canceled"
    assert loaded.cancel_requested is True
    assert len(loaded.results) == 1
