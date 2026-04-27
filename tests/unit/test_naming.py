from ast2python.naming import NamingRegistry, escape_python_name, snake_case


def test_snake_case_and_escape_are_deterministic():
    assert snake_case("effMinBodyATR") == "eff_min_body_atr"
    assert snake_case("XLMMode") == "xlm_mode"
    assert escape_python_name("class") == "class_"
    assert escape_python_name("sum") == "sum_"


def test_naming_registry_unique_and_discard_names():
    registry = NamingRegistry()
    assert registry.reserve("sum") == "sum_"
    assert registry.reserve("sum") == "sum__2"
    assert registry.discard_name() == "_discard_1"
    assert registry.discard_name() == "_discard_2"
