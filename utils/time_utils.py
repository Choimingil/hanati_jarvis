import datetime

KST = datetime.timezone(datetime.timedelta(hours=9))


def now_iso() -> str:
    return datetime.datetime.now(KST).isoformat()
