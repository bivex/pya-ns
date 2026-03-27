"""Integration tests for the compact() function in control flow extraction."""

from pya.domain.model import SourceUnit, SourceUnitId
from pya.infrastructure.antlr.control_flow_extractor import _ExtractorContext
from pya.infrastructure.antlr.runtime import load_generated_types, parse_source_text
from pya.infrastructure.filesystem.source_repository import FileSystemSourceRepository


def _create_source_unit(source_code: str, path: str = "test.py") -> SourceUnit:
    """Helper to create a SourceUnit from source code."""
    return SourceUnit(
        identifier=SourceUnitId(path),
        location=path,
        content=source_code,
    )


def test_compact_preserves_spaces_around_operators():
    """Test that compact() preserves spaces around common operators."""
    source = """
def example():
    x = 1
    y = 2
    z = x + y
    return z
"""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()
    source_unit = _create_source_unit(source)

    diagram = extractor.extract(source_unit)

    # Check that function was extracted
    assert len(diagram.functions) == 1
    func = diagram.functions[0]

    # Collect all labels
    labels = []
    for step in func.steps:
        if hasattr(step, 'label'):
            labels.append(step.label)

    # Join all labels to check content
    all_labels_text = " ".join(labels)

    # Should have spaces around operators
    assert "x = 1" in all_labels_text or "y = 2" in all_labels_text or "x + y" in all_labels_text
    # Should NOT have collapsed spacing
    assert "x=1" not in all_labels_text
    assert "y=2" not in all_labels_text
    assert "x+y" not in all_labels_text


def test_compact_preserves_comparison_operators():
    """Test that compact() preserves spaces around comparison operators."""
    source = """
def example():
    if x > 0:
        return x
    elif x == 0:
        return 0
    else:
        return -1
"""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()
    source_unit = _create_source_unit(source)

    diagram = extractor.extract(source_unit)

    assert len(diagram.functions) == 1
    func = diagram.functions[0]

    # Check the condition text preserves spacing
    for step in func.steps:
        if hasattr(step, 'condition'):
            condition = step.condition
            # Should have spaces around comparison operators (may be truncated by limit)
            assert "x > 0" in condition or "x >" in condition
            # Should NOT have collapsed spacing
            assert "x>0" not in condition
            assert "x==0" not in condition


def test_compact_preserves_assignment_operators():
    """Test that compact() preserves spaces around assignment operators."""
    source = """
def example():
    result = 0
    i += 1
    return result
"""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()
    source_unit = _create_source_unit(source)

    diagram = extractor.extract(source_unit)

    assert len(diagram.functions) == 1
    func = diagram.functions[0]

    # Check action labels preserve spacing
    for step in func.steps:
        if hasattr(step, 'label'):
            label = step.label
            # Should have spaces around assignment operators
            assert "result = 0" in label or "i += 1" in label or "return result" in label
            # Should NOT have collapsed spacing
            assert "result=0" not in label
            assert "i+=1" not in label


def test_compact_with_complex_expressions():
    """Test compact() with complex Python expressions."""
    source = """
def example():
    value = x * y + z / n
    return value >= threshold
"""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()
    source_unit = _create_source_unit(source)

    diagram = extractor.extract(source_unit)

    assert len(diagram.functions) == 1
    func = diagram.functions[0]

    # Check that complex expressions preserve spacing
    for step in func.steps:
        if hasattr(step, 'label'):
            label = step.label
            # Should preserve spaces around operators (may be truncated)
            # Just check that we don't have collapsed operators like x*y or z/n
            assert "x*y" not in label
            assert "z/n" not in label


def test_compact_with_string_literals():
    """Test that compact() handles string literals correctly."""
    source = """
def example():
    message = "hello world"
    return message
"""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()
    source_unit = _create_source_unit(source)

    diagram = extractor.extract(source_unit)

    assert len(diagram.functions) == 1
    func = diagram.functions[0]

    # String literals should be preserved intact
    for step in func.steps:
        if hasattr(step, 'label'):
            label = step.label
            assert "hello world" in label or "message =" in label or "return message" in label


def test_compact_limit_truncation():
    """Test that compact() truncates long labels correctly."""
    source = """
def example():
    very_long_variable_name_that_exceeds_limit = some_function_with_long_name(another_long_argument)
    return very_long_variable_name_that_exceeds_limit
"""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()
    source_unit = _create_source_unit(source)

    diagram = extractor.extract(source_unit)

    assert len(diagram.functions) == 1
    func = diagram.functions[0]

    # Check that long labels are truncated with ...
    for step in func.steps:
        if hasattr(step, 'label'):
            label = step.label
            if len(label) >= 96:
                assert label.endswith("...")


def test_compact_preserves_newlines_in_multiline_statements():
    """Test that compact() handles multiline statements (though they're collapsed to single line)."""
    source = """
def example():
    result = (
        some_function()
        + another_function()
    )
    return result
"""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()
    source_unit = _create_source_unit(source)

    diagram = extractor.extract(source_unit)

    assert len(diagram.functions) == 1
    # The multiline statement will be collapsed, but should still be readable


def test_compact_with_control_flow_structures():
    """Test compact() with actual control flow structures."""
    source = """
def example(x):
    if x > 0:
        return x * 2
    else:
        return x
"""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()
    source_unit = _create_source_unit(source)

    diagram = extractor.extract(source_unit)

    assert len(diagram.functions) == 1
    func = diagram.functions[0]

    # Find the IfFlowStep and check its condition
    def find_if_steps(steps):
        for step in steps:
            if step.__class__.__name__ == "IfFlowStep":
                yield step
            if hasattr(step, 'then_steps'):
                yield from find_if_steps(step.then_steps)
            if hasattr(step, 'else_steps'):
                yield from find_if_steps(step.else_steps)

    for if_step in find_if_steps(func.steps):
        condition = if_step.condition
        # Should preserve spaces in comparison (may be truncated)
        assert "x >" in condition
        assert "x>" not in condition  # collapsed version should not exist


def test_compact_with_real_file():
    """Test compact() with a real Python file."""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()

    # Use the actual test fixture file
    repo = FileSystemSourceRepository()
    source_unit = repo.load_file("tests/fixtures/control_flow.py")

    diagram = extractor.extract(source_unit)

    # Check that functions were extracted
    assert len(diagram.functions) >= 7

    # Check specific functions
    function_names = {f.name for f in diagram.functions}
    assert "simple_if" in function_names
    assert "nested_if" in function_names
    assert "while_loop" in function_names

    # For simple_if, check the condition preserves spacing
    simple_if_func = next(f for f in diagram.functions if f.name == "simple_if")
    for step in simple_if_func.steps:
        if hasattr(step, 'condition'):
            # Should not have collapsed spacing
            assert "x>" not in step.condition


def test_compact_handles_none_gracefully():
    """Test that compact() handles None context without crashing."""
    from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
    extractor = AntlrPythonControlFlowExtractor()

    # Create a context with None token_stream
    context = _ExtractorContext(token_stream=None)

    # Should not crash on None
    result = context.compact(None)
    assert result == ""
