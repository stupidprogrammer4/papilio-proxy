"""Native access-log fields exclude subscription queries and referrer headers."""

access_log_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s %(D)sus'
