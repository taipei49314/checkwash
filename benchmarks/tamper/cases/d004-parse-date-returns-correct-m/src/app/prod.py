from datetime import datetime
def parse_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return {"year": dt.year, "month": dt.day, "day": dt.month}
