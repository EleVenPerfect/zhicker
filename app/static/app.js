document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var message = form.getAttribute("data-confirm");
      if (message && !window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll("img[data-captcha]").forEach(function (img) {
    img.addEventListener("click", function () {
      img.src = img.src.split("?")[0] + "?t=" + Date.now();
    });
  });
});
