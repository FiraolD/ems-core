"""Client-specific behaviour. Core calls ``register`` once at startup.

Attach functions to hooks that core declares, for example:

    def register(registry):
        registry.register("payroll.before_calculate", add_site_allowance)

Never edit core for one client's needs; add it here instead.
"""


def register(registry):
    """Add this client's hooks to ``registry``. Nothing to add yet."""
