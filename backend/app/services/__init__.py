"""Business logic, isolated from the HTTP layer.

Each subpackage is a seam for one future capability. They are intentionally
empty: routes should depend on these services, never the other way around, so
the API surface stays stable as implementations land.

    whatsapp/  inbound webhook verification + outbound replies
    analysis/  AI risk assessment of a forwarded message
    url/       link extraction, expansion and reputation checks
    evidence/  persisting reports and building an audit trail
"""
