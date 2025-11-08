def pytest_load_initial_conftests(early_config, parser, args):
    """Block third-party plugins that break our test suite."""
    early_config.pluginmanager.set_blocked("web3.tools.pytest_ethereum")
