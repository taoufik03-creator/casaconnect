(function () {
  "use strict";

  // Scroll the conversation to the latest message.
  var thread = document.getElementById("thread");
  if (thread) thread.scrollTop = thread.scrollHeight;

  // Star buttons: toggle without reloading the page.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.classList.contains("star-form")) return;
    e.preventDefault();
    var btn = form.querySelector(".star");
    fetch(form.action, {
      method: "POST", body: new FormData(form),
      headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin",
    }).then(function (r) { return r.json(); }).then(function (d) {
      btn.classList.toggle("on", d.starred);
      btn.textContent = d.starred ? "★" : "☆";
    }).catch(function () { form.submit(); });
  });

  var composer = document.querySelector("form.composer");
  if (!composer) return;

  // Recipients: live filter, counter, group hint.
  var filter = composer.querySelector(".recipient-filter");
  var boxes = composer.querySelectorAll(".recipient input[type=checkbox]");
  var counter = composer.querySelector(".recipient-count");
  var groupHint = composer.querySelector(".group-hint");

 

  function refreshCount() {
    if (!counter) return;
    var n = composer.querySelectorAll(".recipient input:checked").length;
    counter.textContent = n;
    groupHint.hidden = n < 2;
  }
  if (filter) {
    filter.addEventListener("input", function () {
      var q = filter.value.trim().toLowerCase();
      composer.querySelectorAll(".recipient").forEach(function (l) {

        var checked = l.querySelector("input").checked;
        l.hidden = !checked && (!q || l.textContent.toLowerCase().indexOf(q) === -1);
      });
    });

    boxes.forEach(function (b) {
      b.addEventListener("change", function () {
        if (!b.checked) b.closest(".recipient").hidden = true;   // unticked -> disappears
        refreshCount();
      });
    });

    refreshCount();
    filter.dispatchEvent(new Event("input"));
  }

  // Automatic drafts: save ~1.5 s after the user stops typing / changing recipients.
  var url = composer.dataset.autosave;
  var status = composer.querySelector(".autosave-status");
  var idField = composer.querySelector("input[name=draft_id]");
  var timer = null, inFlight = false, dirty = false, submitting = false;

  // Status texts come from the template (translated into the active language).
  var msgSaving = composer.dataset.msgSaving || "Enregistrement…";
  var msgSaved = composer.dataset.msgSaved || "Brouillon enregistré à";
  var msgFailed = composer.dataset.msgFailed || "Brouillon non enregistré";

  function save() {
    if (submitting) return;
    if (inFlight) { dirty = true; return; }   // never run two saves at once (avoids duplicate drafts)
    inFlight = true; dirty = false;
    status.textContent = msgSaving;
    var fd = new FormData(composer);
    fetch(url, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
      .then(function (d) {
        idField.value = d.draft_id || "";
        status.textContent = d.draft_id ? msgSaved + " " + d.saved_at : "";
      })
      .catch(function () { status.textContent = msgFailed; })
      .finally(function () { inFlight = false; if (dirty) save(); });
  }
  function schedule() { clearTimeout(timer); timer = setTimeout(save, 1500); }

  composer.querySelector("textarea").addEventListener("input", schedule);
  boxes.forEach(function (b) { b.addEventListener("change", schedule); });
  composer.addEventListener("submit", function () { submitting = true; clearTimeout(timer); });
})();
