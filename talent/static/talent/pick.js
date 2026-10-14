(function () {
  function chosenText(select) {
    var option = select.options[select.selectedIndex];
    return option ? option.textContent : "";
  }

  function upgradeSelect(select) {
    if (select.closest(".combo")) return;
    var provinceSelect = document.getElementById(select.getAttribute("data-province-select") || "");
    var categorySelect = document.getElementById(select.getAttribute("data-category-select") || "");
    var all = Array.from(select.options).map(function (option) {
      return {
        value: option.value,
        text: option.textContent,
        province: option.getAttribute("data-province") || "",
        category: option.getAttribute("data-category") || ""
      };
    });
    var box = document.createElement("div");
    box.className = "combo";
    select.parentNode.insertBefore(box, select);
    box.appendChild(select);
    select.classList.add("combo-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");

    var face = document.createElement("button");
    face.type = "button";
    face.className = "combo-face";
    var panel = document.createElement("div");
    panel.className = "combo-panel";
    panel.hidden = true;
    var search = document.createElement("input");
    search.type = "search";
    search.className = "combo-search";
    search.placeholder = "جستجو";
    search.setAttribute("aria-label", "جستجو");
    var list = document.createElement("div");
    list.className = "combo-list";
    panel.appendChild(search);
    panel.appendChild(list);
    box.appendChild(face);
    box.appendChild(panel);

    function allowed(item, query) {
      var province = provinceSelect ? provinceSelect.value : "";
      var category = categorySelect ? categorySelect.value : "";
      if (item.value && province && item.province && item.province !== province) return false;
      if (item.value && category && item.category && item.category !== category) return false;
      if (item.value && query && item.text.indexOf(query) === -1) return false;
      return true;
    }

    function paint() {
      var query = search.value.trim();
      var stillThere = all.some(function (item) {
        return item.value === select.value && allowed(item, "");
      });
      if (!stillThere) select.value = "";
      list.replaceChildren();
      all.forEach(function (item) {
        if (!allowed(item, query)) return;
        var choice = document.createElement("button");
        choice.type = "button";
        choice.className = "combo-item";
        choice.textContent = item.text;
        if (item.value === select.value) choice.classList.add("active");
        choice.addEventListener("click", function () {
          select.value = item.value;
          face.textContent = item.text;
          panel.hidden = true;
          box.classList.remove("open");
          search.value = "";
          paint();
        });
        list.appendChild(choice);
      });
      if (!list.childElementCount) {
        var empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "موردی نیست";
        list.appendChild(empty);
      }
      face.textContent = chosenText(select);
    }

    face.addEventListener("click", function () {
      var opening = panel.hidden;
      closePanels(panel);
      panel.hidden = !opening;
      box.classList.toggle("open", opening);
      if (opening) search.focus();
    });
    search.addEventListener("input", paint);
    if (provinceSelect) provinceSelect.addEventListener("change", paint);
    if (categorySelect) categorySelect.addEventListener("change", paint);
    paint();
  }

  function upgradeChecks(root) {
    if (root.closest(".combo")) return;
    var box = document.createElement("div");
    box.className = "combo";
    root.parentNode.insertBefore(box, root);
    var face = document.createElement("button");
    face.type = "button";
    face.className = "combo-face";
    var panel = document.createElement("div");
    panel.className = "combo-panel";
    panel.hidden = true;
    var search = document.createElement("input");
    search.type = "search";
    search.className = "combo-search";
    search.placeholder = "جستجو";
    search.setAttribute("aria-label", "جستجو");
    box.appendChild(face);
    box.appendChild(panel);
    panel.appendChild(search);
    panel.appendChild(root);

    function summary() {
      var count = root.querySelectorAll("input:checked").length;
      face.textContent = count ? "تخصص‌ها (" + count + ")" : "تخصص‌ها";
    }
    function filter() {
      var query = search.value.trim();
      root.querySelectorAll("[data-role-group]").forEach(function (group) {
        var visible = false;
        group.querySelectorAll("[data-role-name]").forEach(function (label) {
          var name = label.getAttribute("data-role-name") || "";
          var boxInput = label.querySelector("input");
          var show = !query || name.indexOf(query) !== -1 || (boxInput && boxInput.checked);
          label.hidden = !show;
          if (show) visible = true;
        });
        group.hidden = !visible;
      });
      root.querySelectorAll("li").forEach(function (item) {
        var boxInput = item.querySelector("input");
        var checked = boxInput && boxInput.checked;
        item.hidden = Boolean(query) && item.textContent.indexOf(query) === -1 && !checked;
      });
    }
    face.addEventListener("click", function () {
      var opening = panel.hidden;
      closePanels(panel);
      panel.hidden = !opening;
      box.classList.toggle("open", opening);
      if (opening) search.focus();
    });
    search.addEventListener("input", filter);
    root.addEventListener("change", summary);
    summary();
  }

  function closePanels(except) {
    document.querySelectorAll(".combo").forEach(function (combo) {
      var panel = combo.querySelector(".combo-panel");
      if (!panel || panel === except) return;
      panel.hidden = true;
      combo.classList.remove("open");
    });
  }

  function mount() {
    document.querySelectorAll("select.pick-list").forEach(upgradeSelect);
    document.querySelectorAll("ul.role-picks, [data-role-groups]").forEach(upgradeChecks);
    document.addEventListener("click", function (event) {
      if (event.target.closest(".combo")) return;
      closePanels(null);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
