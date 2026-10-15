import datetime
def utcnow(): return datetime.datetime.now(datetime.timezone.utc)
def now(): return datetime.datetime.now()
def parse_datetime(text):
    try: return datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError): return None
def as_local(d): return d
