from ts_cli.databricks.mv_emit_expr import UntranslatableError


class TestModuleContract:
    def test_untranslatable_error_is_exception(self):
        assert issubclass(UntranslatableError, Exception)
