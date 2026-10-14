(function () {
  var months = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"];
  var week = ["ش", "ی", "د", "س", "چ", "پ", "ج"];
  var pop = null;
  var field = null;
  var viewYear = 1400;
  var viewMonth = 1;

  function persian(value) {
    return String(value).replace(/\d/g, function (digit) {
      return "۰۱۲۳۴۵۶۷۸۹"[digit];
    });
  }

  function latin(value) {
    return String(value || "")
      .replace(/[۰-۹]/g, function (digit) { return String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)); })
      .replace(/[٠-٩]/g, function (digit) { return String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)); });
  }

  function gregorianToJalali(gy, gm, gd) {
    var gDays = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    var gy2 = gm > 2 ? gy + 1 : gy;
    var days = 355666 + (365 * gy) + Math.floor((gy2 + 3) / 4) - Math.floor((gy2 + 99) / 100) + Math.floor((gy2 + 399) / 400) + gd + gDays[gm - 1];
    var jy = -1595 + (33 * Math.floor(days / 12053));
    days %= 12053;
    jy += 4 * Math.floor(days / 1461);
    days %= 1461;
    if (days > 365) {
      jy += Math.floor((days - 1) / 365);
      days = (days - 1) % 365;
    }
    var jm;
    var jd;
    if (days < 186) {
      jm = 1 + Math.floor(days / 31);
      jd = 1 + (days % 31);
    } else {
      jm = 7 + Math.floor((days - 186) / 30);
      jd = 1 + ((days - 186) % 30);
    }
    return { y: jy, m: jm, d: jd };
  }

  function jalaliToGregorian(jy, jm, jd) {
    jy += 1595;
    var days = -355668 + (365 * jy) + Math.floor(jy / 33) * 8 + Math.floor(((jy % 33) + 3) / 4) + jd;
    if (jm < 7) days += (jm - 1) * 31;
    else days += (jm - 7) * 30 + 186;
    var gy = 400 * Math.floor(days / 146097);
    days %= 146097;
    if (days > 36524) {
      days -= 1;
      gy += 100 * Math.floor(days / 36524);
      days %= 36524;
      if (days >= 365) days += 1;
    }
    gy += 4 * Math.floor(days / 1461);
    days %= 1461;
    if (days > 365) {
      gy += Math.floor((days - 1) / 365);
      days = (days - 1) % 365;
    }
    var gd = days + 1;
    var leap = gy % 4 === 0 && (gy % 100 !== 0 || gy % 400 === 0);
    var lengths = [0, 31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    var gm = 1;
    while (gm <= 12 && gd > lengths[gm]) {
      gd -= lengths[gm];
      gm += 1;
    }
    return { y: gy, m: gm, d: gd };
  }

  function monthLength(year, month) {
    if (month <= 6) return 31;
    if (month <= 11) return 30;
    var remainder = year % 33;
    return [1, 5, 9, 13, 17, 22, 26, 30].indexOf(remainder) >= 0 ? 30 : 29;
  }

  function read(input) {
    var parts = latin(input.value).replace(/-/g, "/").replace(/\./g, "/").split("/").filter(Boolean);
    if (parts.length !== 3) return null;
    var year = Number(parts[0]);
    var month = Number(parts[1]);
    var day = Number(parts[2]);
    if (!year || month < 1 || month > 12 || day < 1) return null;
    if (year >= 1700) return gregorianToJalali(year, month, day);
    if (year < 1200 || year > 1600 || day > monthLength(year, month)) return null;
    return { y: year, m: month, d: day };
  }

  function today() {
    var now = new Date();
    return gregorianToJalali(now.getFullYear(), now.getMonth() + 1, now.getDate());
  }

  function write(day) {
    field.value = persian(day.y + "/" + String(day.m).padStart(2, "0") + "/" + String(day.d).padStart(2, "0"));
    field.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function paint() {
    if (!pop || !field) return;
    var chosen = read(field);
    var current = today();
    var first = jalaliToGregorian(viewYear, viewMonth, 1);
    var weekday = (new Date(first.y, first.m - 1, first.d).getDay() + 1) % 7;
    var days = monthLength(viewYear, viewMonth);
    var cells = week.map(function (name) {
      return '<span class="jalali-week">' + name + "</span>";
    }).join("");
    var i;
    for (i = 0; i < weekday; i += 1) cells += "<span></span>";
    for (i = 1; i <= days; i += 1) {
      var classes = [];
      if (chosen && chosen.y === viewYear && chosen.m === viewMonth && chosen.d === i) classes.push("on");
      if (current.y === viewYear && current.m === viewMonth && current.d === i) classes.push("today");
      cells += '<button type="button" data-day="' + i + '"' + (classes.length ? ' class="' + classes.join(" ") + '"' : "") + ">" + persian(i) + "</button>";
    }
    pop.querySelector("[data-jalali-title]").textContent = months[viewMonth - 1] + " " + persian(viewYear);
    pop.querySelector("[data-jalali-days]").innerHTML = cells;
  }

  function close() {
    if (pop) pop.hidden = true;
    field = null;
  }

  function open(input) {
    field = input;
    var chosen = read(input) || today();
    viewYear = chosen.y;
    viewMonth = chosen.m;
    if (!pop) {
      pop = document.createElement("div");
      pop.className = "jalali-pop";
      pop.hidden = true;
      pop.innerHTML = '<div class="jalali-bar"><button type="button" data-jalali-prev>ماه قبل</button><strong data-jalali-title></strong><button type="button" data-jalali-next>ماه بعد</button></div><div class="jalali-grid" data-jalali-days></div><button type="button" class="quiet" data-jalali-today>امروز</button>';
      document.body.appendChild(pop);
      pop.addEventListener("click", function (event) {
        var day = event.target.getAttribute && event.target.getAttribute("data-day");
        if (day && field) {
          write({ y: viewYear, m: viewMonth, d: Number(day) });
          close();
          return;
        }
        if (event.target.hasAttribute("data-jalali-prev")) {
          viewMonth -= 1;
          if (viewMonth < 1) { viewMonth = 12; viewYear -= 1; }
          paint();
        }
        if (event.target.hasAttribute("data-jalali-next")) {
          viewMonth += 1;
          if (viewMonth > 12) { viewMonth = 1; viewYear += 1; }
          paint();
        }
        if (event.target.hasAttribute("data-jalali-today")) {
          var now = today();
          write(now);
          close();
        }
      });
      document.addEventListener("click", function (event) {
        if (!pop || pop.hidden) return;
        if (pop.contains(event.target) || event.target === field || (field && field.parentNode && field.parentNode.contains(event.target))) return;
        close();
      });
      document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") close();
      });
    }
    var box = input.getBoundingClientRect();
    pop.hidden = false;
    pop.style.top = (window.scrollY + box.bottom + 6) + "px";
    pop.style.left = "auto";
    pop.style.right = (document.documentElement.clientWidth - box.right) + "px";
    paint();
  }

  document.querySelectorAll("[data-jalali]").forEach(function (input) {
    var opener = input.parentNode.querySelector(".jalali-open");
    input.addEventListener("focus", function () { open(input); });
    if (opener) opener.addEventListener("click", function () { open(input); input.focus(); });
  });
})();
