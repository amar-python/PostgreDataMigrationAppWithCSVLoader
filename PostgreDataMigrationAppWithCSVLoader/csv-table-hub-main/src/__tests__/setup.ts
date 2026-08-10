import "@testing-library/jest-dom";
// suppress Notification API warnings in jsdom
if (!("Notification" in globalThis)) {
  Object.defineProperty(globalThis, "Notification", {
    value: class { static permission = "default"; static requestPermission = async () => "default"; },
    writable: true,
  });
}
// localStorage is available in jsdom; nothing extra needed.
