import datetime
def utcnow(): return datetime.datetime.now(datetime.timezone.utc)
def now(): return datetime.datetime.now()
def parse_datetime(text):
    try: return datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError): return None
def as_local(d): return d

def start_of_local_day(d=None):
    if d is None: d = now()
    if isinstance(d, datetime.datetime):
        return d.replace(hour=0, minute=0, second=0, microsecond=0)
    return datetime.datetime(d.year, d.month, d.day)
