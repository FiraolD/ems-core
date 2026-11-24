"""Pay rules that administrators can change in the system, each with a start date.

A rule value or a tax schedule applies from its "effective from" date until a later one
replaces it, so a payroll month is always calculated with the rules that were in force then.
Precedence for any date: value entered in the system, then the client's ``client.toml``
``[rules]``, then the country pack's default.
"""
