"""Fake Lambda context for `python -m <module>.handler` local runs.

Powertools' Logger.inject_lambda_context reads function_name/memory_limit_in_mb/
invoked_function_arn/aws_request_id straight off the context object, so `handler(event, None)`
-- what every handler's __main__ block used before Phase 7 -- would raise AttributeError.
"""


class LocalLambdaContext:
    function_name = "local"
    memory_limit_in_mb = 256
    invoked_function_arn = "arn:aws:lambda:local:000000000000:function:local"
    aws_request_id = "local-run"

    def get_remaining_time_in_millis(self) -> int:
        return 60_000
