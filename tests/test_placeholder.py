def test_imports():
    import kb_mcp_lite

    # Dynamic check — version comes from the package itself, not a hardcoded string
    assert kb_mcp_lite.__version__ != ""
    assert kb_mcp_lite.__version__.count(".") == 2
