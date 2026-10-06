"""Resolver deadline + luat gop voi ket qua cua model.

resolve(text, header_iso)  -> (deadline_iso|None, status, ghi_chu)
apply_deadline_resolution(item, meeting_date_iso) -> item da sua deadline / deadline_status
"""
import re, datetime, unicodedata

WD_WORD = {"hai":0,"ba":1,"tư":2,"năm":3,"sáu":4,"bảy":5}
WD_NUM  = {"2":0,"3":1,"4":2,"5":3,"6":4,"7":5}
RESOLVED_LIKE = {"resolved", "resolved_with_warning", "date_resolved_time_ambiguous"}

def _n(s): return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(s or "")).lower().strip())
def _next_weekday(d0, wd):
    k = (wd - d0.weekday()) % 7
    return d0 + datetime.timedelta(days=k or 7)
def _weekday_next_week(d0, wd):
    mon = d0 - datetime.timedelta(days=d0.weekday())
    return mon + datetime.timedelta(days=7 + wd)

_WD = r"(hai|ba|tư|năm|sáu|bảy|[2-7])"
def _wd(tok): return WD_WORD.get(tok, WD_NUM.get(tok))

def resolve(text, header_iso):
    t = _n(text)
    if not t: return None, "missing", "khong co cum"

    # Cum cho biet deadline CHUA DUOC CHOT -> missing, khong phai ambiguous.
    # Dat truoc cac rule ngay tuong doi de tranh bat nham "hom nay" trong
    # cau nhu "moc cu the minh chua can chot hom nay".
    if re.search(
        r"\b(chưa\s+(?:cần\s+)?chốt|chưa\s+có\s+(?:hạn|deadline|mốc)|"
        r"chưa\s+xác\s+định|chưa\s+nói\s+chắc|mốc[^.]{0,40}chưa\s+chốt)\b",
        t,
    ):
        return None, "missing", "chua co deadline"

    # moc theo cuoc hop khong phai ngay cu the: quy uoc du an la 'missing', giu deadline_text
    if re.search(r"\b(ngay )?sau (cuộc họp|buổi họp|khi họp|họp)\b", t): return None, "missing", "moc theo cuoc hop"
    try: d0 = datetime.date.fromisoformat(header_iso)
    except (TypeError, ValueError): return None, "ambiguous", "khong co ngay hop hop le"
    dates = re.findall(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", t)
    if len(set(dates)) >= 2: return None, "conflict", "nhieu ngay"
    wds = {m for m in re.findall(r"thứ\s*" + _WD, t)}
    if len(wds) >= 2: return None, "conflict", "nhieu thu"
    if re.search(r"\btrong hôm nay\b", t):
        return d0.isoformat(), "resolved", "trong ngay"
    if re.search(r"\b(chiều nay|sáng nay|tối nay|trưa nay|đêm nay)\b", t):
        return d0.isoformat(), "date_resolved_time_ambiguous", "cung ngay, gio mo ho"
    if re.search(r"\bhôm nay\b", t):
        return d0.isoformat(), "resolved", "cung ngay"
    if re.search(r"\b(ngày mai|sáng mai|chiều mai|tối mai)\b", t): return (d0 + datetime.timedelta(days=1)).isoformat(), "resolved", "+1"
    if re.search(r"\bngày kia\b", t): return (d0 + datetime.timedelta(days=2)).isoformat(), "resolved", "+2"
    if dates:
        dd, mm, yy = dates[0]
        y = d0.year if not yy else (2000 + int(yy) if len(yy) == 2 else int(yy))
        try: d = datetime.date(y, int(mm), int(dd))
        except ValueError: return None, "ambiguous", "ngay khong hop le"
        if d < d0: return None, "ambiguous", "ngay da qua"          # an toan: dua vao human_review
        return d.isoformat(), "resolved", "tuyet doi"
    m = re.search(r"thứ\s*" + _WD + r"\s+tuần sau", t)
    if m: return _weekday_next_week(d0, _wd(m.group(1))).isoformat(), "resolved", "tuan sau"
    m = re.search(r"thứ\s*" + _WD + r"(?:\s+(?:tuần này|này|tới))?", t)
    if m: return _next_weekday(d0, _wd(m.group(1))).isoformat(), "resolved", "thu gan nhat"

    # "them mot tuan nua" / "them 2 tuan nua" tinh tu ngay hop.
    m = re.search(r"\bthêm\s+(một|\d+)\s+tuần(?:\s+nữa)?\b", t)
    if m:
        n = 1 if m.group(1) == "một" else int(m.group(1))
        return (d0 + datetime.timedelta(days=7 * n)).isoformat(), "resolved", f"+{n} tuan"

    if re.search(r"tuần này|tuần sau|cuối tuần|đầu tuần|tháng", t): return None, "ambiguous", "khong ro ngay"
    return None, "unparsed", "chua co luat"

def apply_deadline_resolution(item, meeting_date_iso):
    if item.get("content_type") != "task_candidate": return item
    text = (item.get("deadline_text") or "").strip()
    ms = item.get("deadline_status")
    # event_based chi hop le khi co depends_on (quy uoc du an)
    if ms == "event_based" and item.get("depends_on"):
        item["deadline"] = None; return item
    if not text:
        item["deadline"] = None
        if ms in RESOLVED_LIKE: item["deadline_status"] = "ambiguous"     # noi da quy doi ma khong co cum
        elif ms == "event_based": item["deadline_status"] = "missing"      # event_based khong co depends_on
        return item
    dl, rs, _ = resolve(text, meeting_date_iso)
    if ms == "conflict":                       # conflict thuong xuyen qua nhieu luot: model thay ngu canh ma resolver khong thay
        item["deadline"] = None
    elif ms == "ambiguous" and rs in RESOLVED_LIKE:
        # Model co the da nhin thay ngu canh phu dinh / chua chot ma resolver chi thay cum ngay.
        # Khong nang ambiguous thanh resolved mot cach tu dong.
        item["deadline"] = None
        item["deadline_status"] = "ambiguous"
    elif rs == "unparsed":
        item["deadline"], item["deadline_status"] = None, "ambiguous"
    elif rs in ("ambiguous", "conflict", "missing"):
        item["deadline"], item["deadline_status"] = None, rs
    else:                                      # resolved | date_resolved_time_ambiguous
        item["deadline"], item["deadline_status"] = dl, rs
    return item
