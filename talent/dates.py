from datetime import date, datetime

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
LATIN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def persian_digits(value):
    return str(value).translate(PERSIAN_DIGITS)


def latin_digits(value):
    return str(value or "").translate(LATIN_DIGITS).strip()


def gregorian_to_jalali(gy, gm, gd):
    g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + (365 * gy)
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        + gd
        + g_days[gm - 1]
    )
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def jalali_to_gregorian(jy, jm, jd):
    jy += 1595
    days = -355668 + (365 * jy) + (jy // 33) * 8 + (((jy % 33) + 3) // 4) + jd
    if jm < 7:
        days += (jm - 1) * 31
    else:
        days += (jm - 7) * 30 + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)
    month_lengths = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 1
    while gm <= 12 and gd > month_lengths[gm]:
        gd -= month_lengths[gm]
        gm += 1
    return date(gy, gm, gd)


def jalali_label(day):
    if day is None:
        return ""
    if isinstance(day, datetime):
        day = day.date()
    jy, jm, jd = gregorian_to_jalali(day.year, day.month, day.day)
    return persian_digits(f"{jy}/{jm:02d}/{jd:02d}")


def jalali_clock(moment):
    if moment is None:
        return ""
    return persian_digits(f"{moment.hour:02d}:{moment.minute:02d}")


def jalali_datetime(moment):
    if moment is None:
        return ""
    if isinstance(moment, date) and not isinstance(moment, datetime):
        return jalali_label(moment)
    return f"{jalali_label(moment)} {jalali_clock(moment)}"


def parse_day(value):
    text = latin_digits(value).replace("-", "/").replace(".", "/")
    parts = [part for part in text.split("/") if part]
    if len(parts) != 3:
        return None
    try:
        year, month, day = (int(part) for part in parts)
    except ValueError:
        return None
    try:
        if year >= 1700:
            return date(year, month, day)
        if 1200 <= year <= 1600:
            return jalali_to_gregorian(year, month, day)
    except ValueError:
        return None
    return None
