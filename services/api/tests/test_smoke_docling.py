import json

from scripts.smoke_docling import warning_payload
from lab.docling_pipeline import ParserWarning


def test_smoke_warning_payload_serializes_nonempty_parser_warning():
    warnings = warning_payload([ParserWarning("partial_success", "One page was incomplete.")])
    assert warnings == [{"code": "partial_success", "message": "One page was incomplete."}]
    assert json.loads(json.dumps(warnings)) == warnings
