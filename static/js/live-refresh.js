(function () {
  setInterval(function () {
    if (document.visibilityState === "visible") {
      window.location.reload();
    }
  }, 60000);
})();