"""Execution semantics shared by discovery verification and replay."""
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import quote
from automation.capabilities.models import ElementVisibleCondition, TextContainsCondition, UrlMatchesCondition, ExtractedValueMatchesCondition
from automation.surface.errors import TargetResolutionError

REFERENCE = re.compile(r"\$\{(?:inputs\.)?([a-zA-Z_][a-zA-Z0-9_]*)\}")


def resolve_template(template, values, *, url=False):
    def replace(match):
        if match[1] not in values:
            raise ValueError("missing template input")
        value = str(values[match[1]])
        return quote(value, safe="") if url else value
    return REFERENCE.sub(replace, template)


def validate_inputs(parameters, values):
    declared = {p.name: p for p in parameters}
    if set(values) - set(declared):
        raise ValueError("unknown invocation parameters")
    result = {}
    for name, parameter in declared.items():
        value = values.get(name, parameter.default)
        if value is None:
            if parameter.required:
                raise ValueError(f"missing required invocation parameter: {name}")
            continue
        kind = parameter.value_type
        valid = ((kind == "string" and isinstance(value, str)) or
                 (kind == "integer" and type(value) is int) or
                 (kind == "boolean" and type(value) is bool) or
                 (kind == "decimal" and isinstance(value, (Decimal, str, int)) and type(value) is not bool))
        if not valid:
            raise ValueError(f"invalid input type: {name}")
        if kind == "decimal":
            try:
                value = Decimal(value)
            except InvalidOperation as error:
                raise ValueError(f"invalid decimal input: {name}") from error
            if not value.is_finite():
                raise ValueError(f"nonfinite input: {name}")
        pattern = getattr(parameter, "pattern", None)
        if pattern and re.fullmatch(pattern, value) is None:
            raise ValueError(f"input pattern mismatch: {name}")
        for bound, compare in [("minimum", lambda a,b:a<b), ("maximum", lambda a,b:a>b)]:
            limit = getattr(parameter, bound, None)
            if limit is not None and compare(value, limit):
                raise ValueError(f"input outside {bound}: {name}")
        result[name] = value
    return result


def parse_outputs(declarations, raw):
    result = {}
    for output in declarations:
        if output.name not in raw:
            if output.required:
                raise ValueError(f"missing required output: {output.name}")
            continue
        text = str(raw[output.name]).strip()
        try:
            if output.parser == "raw_text":
                value = text
            elif output.parser == "integer":
                if not re.fullmatch(r"[+-]?\d+", text):
                    raise ValueError()
                value = int(text)
            elif output.parser in {"decimal", "currency"}:
                if output.parser == "currency":
                    if not re.fullmatch(r"\$?-?(?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2}", text):
                        raise ValueError()
                    text = text.replace("$", "").replace(",", "")
                value = Decimal(text)
                if not value.is_finite():
                    raise ValueError()
            else:
                if text.casefold() not in {"true", "false"}:
                    raise ValueError()
                value = text.casefold() == "true"
        except (ValueError, InvalidOperation) as error:
            raise ValueError(f"output could not be parsed: {output.name}") from error
        result[output.name] = value
    return result


def condition_matches(surface, condition, outputs, values):
    if isinstance(condition, ExtractedValueMatchesCondition):
        value = outputs.get(condition.output_name)
        return value is not None and re.search(condition.pattern, str(value)) is not None
    if isinstance(condition, UrlMatchesCondition):
        pattern = REFERENCE.sub(lambda m: re.escape(quote(str(values[m[1]]), safe="")), condition.pattern)
        return re.search(pattern, surface.observe().current_location) is not None
    try:
        if isinstance(condition, ElementVisibleCondition):
            surface.wait_for_state(condition, 0.1)
            return True
        if isinstance(condition, TextContainsCondition):
            surface.wait_for_state(ElementVisibleCondition(target=condition.target), 0.1)
            return resolve_template(condition.expected_text, values) in surface.read_text_or_value(condition.target)
    except TargetResolutionError:
        return False
    return False
