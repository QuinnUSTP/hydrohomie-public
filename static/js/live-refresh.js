(function () {
  setInterval(function () {
    if (document.visibilityState === "visible") {
      window.location.reload();
    }
  }, 30000);
})();