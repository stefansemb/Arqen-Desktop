from arqen.tools.builtins import create_builtin_registry
from arqen.ui.tool_catalog import CATEGORIES, tool_info


def test_every_builtin_tool_has_swedish_display_info():
    """A new tool should get a name and category, not land in "Övrigt"."""
    missing = [
        item["name"]
        for item in create_builtin_registry().describe()
        if tool_info(item["name"]).category == "Övrigt"
    ]
    assert missing == []


def test_unknown_tool_falls_back_to_its_model_description():
    info = tool_info("brand_new_tool", "Does something new.")
    assert (info.category, info.title, info.summary) == ("Övrigt", "brand_new_tool", "Does something new.")
    assert info.category in CATEGORIES
