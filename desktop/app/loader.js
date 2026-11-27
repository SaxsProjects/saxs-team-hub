// Opens the Team Hub once it can be reached; until then says so, and tries again by itself.
(function () {
  var HUB = "https://hub.saxsprojects.co.za/";
  var title = document.getElementById("title");
  var message = document.getElementById("message");
  var retry = document.getElementById("retry");
  var timer;

  function offline() {
    title.textContent = "You're offline";
    message.textContent = "The Team Hub needs the internet. It opens by itself when you're back online.";
    retry.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(tryOpen, 15000);
  }

  function tryOpen() {
    title.textContent = "Opening the Team Hub…";
    message.textContent = "Connecting to hub.saxsprojects.co.za";
    retry.hidden = true;
    var controller = new AbortController();
    var giveUp = setTimeout(function () { controller.abort(); }, 10000);
    fetch(HUB + "manifest.webmanifest", { mode: "no-cors", cache: "no-store", signal: controller.signal })
      .then(function () { clearTimeout(giveUp); location.replace(HUB); })
      .catch(function () { clearTimeout(giveUp); offline(); });
  }

  retry.addEventListener("click", tryOpen);
  window.addEventListener("online", tryOpen);
  tryOpen();
})();
