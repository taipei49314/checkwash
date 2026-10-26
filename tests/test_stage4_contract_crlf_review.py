"""Independent authority/rename controls; fixture bytes are never executed."""
import pytest

from checkwash.change import EngineError, FileChange
from checkwash.contract import load_contract
from checkwash.gitio import git as gitio


@pytest.mark.parametrize("glob", ['**"', "**'", "'\"**\"'", '"\'**\'"', "''**''", '"""**"""'])
def test_authority_validator_rejects_quote_forms_that_decoder_would_broaden(glob):
    text = "---\ncheckwash:\n  scope:\n    allow:\n      - " + glob + "\n---\n"
    # Historical strip-all-quotes decoding turns each malformed/unsupported
    # token into **. Authority validation must refuse instead of widening scope.
    with pytest.raises(EngineError):
        load_contract(text, source="synthetic BASE TASK")
